
from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify)
from functools import wraps
import hashlib
import json
import psycopg2
import os

from models import Road, RoadNetwork, Shelter
from data_loader import load_data

app = Flask(__name__)

# Needed for login sessions. Set SECRET_KEY on Render (any long random text).
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

# ---------------------------------------------------------
# MAP DATA: everything comes from data.json (edit that file to add
# places, shelters, zone populations or roads). It is checked when
# the app starts, so a typo is reported immediately.
# ---------------------------------------------------------
DATA_FILE = os.environ.get(
    "DATA_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json"))
DATA = load_data(DATA_FILE)

COORDS = DATA["locations"]                  # name -> [lat, lon]
SHELTER_INFO = DATA["shelters"]             # name -> capacity (people)
SHELTERS = tuple(SHELTER_INFO.keys())
ZONE_POPULATION = DATA["zone_population"]   # name -> people
SAMPLE_ROADS = [
    (r["name"], r["start"], r["end"], r["distance_km"],
     r["flood_level"], r["status"])
    for r in DATA["roads"]
]

LOCATIONS = list(COORDS.keys())

# The backup route may be at most this many times longer than the best one
ALT_MAX_RATIO = 2.0

_db_ready = False   # database is created only once, not on every page load


# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------
def get_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise Exception("DATABASE_URL is not configured on Render.")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(db_url)


def initialize_database():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS roads (
            id SERIAL PRIMARY KEY,
            road_name VARCHAR(100) UNIQUE NOT NULL,
            start_location VARCHAR(100) NOT NULL,
            end_location VARCHAR(100) NOT NULL,
            distance_km NUMERIC NOT NULL,
            flood_level VARCHAR(20) NOT NULL,
            road_status VARCHAR(20) NOT NULL
        )
    """)
    for road in SAMPLE_ROADS:
        cur.execute("""
            INSERT INTO roads (road_name, start_location, end_location,
                               distance_km, flood_level, road_status)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (road_name) DO NOTHING
        """, road)

    # Shelters table: capacity and how many people are already assigned
    cur.execute("""
        CREATE TABLE IF NOT EXISTS shelters (
            name VARCHAR(100) PRIMARY KEY,
            capacity INTEGER NOT NULL,
            occupied INTEGER NOT NULL DEFAULT 0
        )
    """)
    for name, cap in SHELTER_INFO.items():
        cur.execute("""
            INSERT INTO shelters (name, capacity, occupied)
            VALUES (%s, %s, 0)
            ON CONFLICT (name) DO NOTHING
        """, (name, cap))

    # Zones table: people still waiting to be evacuated.
    # population      = people not yet placed in a shelter
    # base_population = the full number, used when an emergency is reset
    cur.execute("""
        CREATE TABLE IF NOT EXISTS zones (
            name VARCHAR(100) PRIMARY KEY,
            population INTEGER NOT NULL DEFAULT 0,
            base_population INTEGER NOT NULL DEFAULT 0
        )
    """)
    for name, people in ZONE_POPULATION.items():
        cur.execute("""
            INSERT INTO zones (name, population, base_population)
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO NOTHING
        """, (name, people, people))
    conn.commit()
    cur.close()
    conn.close()


def ensure_db():
    """Create the tables once. Safe to call from anywhere."""
    global _db_ready
    if not _db_ready:
        initialize_database()
        _db_ready = True


def get_road_status():
    """Rows for the road table in index.html."""
    ensure_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT road_name, start_location, end_location,
               distance_km, flood_level, road_status
        FROM roads ORDER BY road_name
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_zone_rows():
    """Rows (name, population, base_population) for the admin page."""
    ensure_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT name, population, base_population
        FROM zones ORDER BY name
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def load_network():
    """Read the database and build the OOP RoadNetwork."""
    ensure_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT start_location, end_location, distance_km,
               flood_level, road_status
        FROM roads
    """)
    rows = cur.fetchall()
    cur.execute("SELECT name, capacity, occupied FROM shelters")
    shelter_rows = cur.fetchall()
    cur.execute("SELECT name, population FROM zones")
    zone_rows = cur.fetchall()
    cur.close()
    conn.close()
    network = RoadNetwork.from_rows(rows, SHELTERS)
    for name, cap, occ in shelter_rows:
        network.shelters[name] = Shelter(name, cap, occ)
    network.set_populations(dict(zone_rows))
    return network


def save_shelter_occupancy(shelter):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE shelters SET occupied = %s WHERE name = %s",
                (shelter.occupied, shelter.name))
    conn.commit()
    cur.close()
    conn.close()


def restore_populations():
    """Put every zone back to its full population (emergency reset)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE zones SET population = base_population")
    conn.commit()
    cur.close()
    conn.close()


def save_evacuation(network, plan):
    """Save shelter occupancy AND the people still waiting in each
    zone in ONE transaction, so it is all saved or nothing is."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        for shelter in network.shelters.values():
            cur.execute(
                "UPDATE shelters SET occupied = %s WHERE name = %s",
                (shelter.occupied, shelter.name))
        for item in plan:
            cur.execute(
                "UPDATE zones SET population = %s WHERE name = %s",
                (item["unplaced"], item["zone"]))
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_road_state(road_name, flood_level, status):
    """Change a road's dynamic state using the Road OOP methods,
    then save the new state to the database."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT road_name, start_location, end_location,
               distance_km, flood_level, road_status
        FROM roads WHERE road_name = %s
    """, (road_name,))
    row = cur.fetchone()
    if row is None:
        cur.close()
        conn.close()
        raise ValueError("Road not found: " + road_name)

    road = Road(*row)                    # build the OOP object
    road.set_flood_level(flood_level)    # validates the level
    if status == "blocked":
        road.block()
    else:
        road.open()

    cur.execute("""
        UPDATE roads SET flood_level = %s, road_status = %s
        WHERE road_name = %s
    """, (road.flood_level, road.status, road.name))
    conn.commit()
    cur.close()
    conn.close()


# ---------------------------------------------------------
# LOGIN (protects the admin pages)
# ---------------------------------------------------------
def admin_required(f):
    """Redirect to the login page unless the admin is logged in."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        real = os.environ.get("ADMIN_PASSWORD")
        if not real:
            error = "ADMIN_PASSWORD is not configured on the server."
        elif request.form.get("password") == real:
            session["is_admin"] = True
            # only allow redirects to pages on this site
            nxt = request.args.get("next") or ""
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("admin")
            return redirect(nxt)
        else:
            error = "Wrong password"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ---------------------------------------------------------
# ADMIN PAGE (authorities update flood / road conditions)
# ---------------------------------------------------------
@app.route("/admin")
@admin_required
def admin():
    message = request.args.get("msg")
    error = request.args.get("err")
    shelters = []
    zones = []
    try:
        roads = get_road_status()
        shelters = list(load_network().shelters.values())
        zones = get_zone_rows()
    except Exception as e:
        roads = []
        error = "Database error: " + str(e)
    return render_template("admin.html", roads=roads, shelters=shelters,
                           zones=zones, message=message, error=error)


@app.route("/reset_shelters", methods=["POST"])
@admin_required
def reset_shelters():
    """Emergency over: empty all shelters and put every zone back to
    its full population."""
    try:
        network = load_network()
        for shelter in network.shelters.values():
            shelter.reset()
            save_shelter_occupancy(shelter)
        restore_populations()
        return redirect(url_for(
            "admin",
            msg="All shelters emptied and zone populations restored"))
    except Exception as e:
        return redirect(url_for("admin", err=str(e)))


@app.route("/update_population", methods=["POST"])
@admin_required
def update_population():
    """Set how many people live in a zone (people to evacuate)."""
    name = request.form.get("zone")
    try:
        try:
            people = int(request.form.get("people", ""))
        except ValueError:
            raise ValueError("Enter a whole number of people")
        if people < 0:
            raise ValueError("People cannot be negative")
        ensure_db()
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE zones SET population = %s, base_population = %s
                WHERE name = %s
            """, (people, people, name))
            if cur.rowcount == 0:
                raise ValueError("Unknown zone: " + str(name))
            conn.commit()
            cur.close()
        finally:
            conn.close()
        return redirect(url_for(
            "admin", msg=f"{name}: {people} people to evacuate"))
    except Exception as e:
        return redirect(url_for("admin", err=str(e)))


@app.route("/confirm_evacuation", methods=["POST"])
def confirm_evacuation():
    """Reserve places in the shelter chosen by the route search."""
    name = request.form.get("shelter")
    try:
        people = int(request.form.get("people", "1"))
        network = load_network()
        shelter = network.shelters.get(name)
        if shelter is None:
            raise ValueError("Unknown shelter")
        shelter.assign(people)               # raises if no room
        save_shelter_occupancy(shelter)
        return redirect(url_for(
            "home", done=f"{people} people assigned to {name}"))
    except Exception as e:
        return redirect(url_for("home", fail=str(e)))


@app.route("/update_road", methods=["POST"])
@admin_required
def update_road():
    road_name = request.form.get("road_name")
    flood_level = request.form.get("flood_level")
    status = request.form.get("status")
    try:
        update_road_state(road_name, flood_level, status)
        return redirect(url_for("admin", msg="Updated: " + road_name))
    except Exception as e:
        return redirect(url_for("admin", err=str(e)))


# ---------------------------------------------------------
# EVACUATE ALL ZONES (authorities see where everyone goes)
# ---------------------------------------------------------
def _clean_risk(value):
    return value if value in ("medium", "high", "submerged") else "high"


@app.route("/evacuate-all")
def evacuate_all():
    min_risk = _clean_risk(request.args.get("risk", "high"))
    plan = []
    shelters = []
    totals = RoadNetwork.plan_totals([])
    error = request.args.get("err")
    try:
        network = load_network()
        plan = network.allocate_evacuation(min_risk)
        totals = RoadNetwork.plan_totals(plan)
        shelters = list(network.shelters.values())   # as if confirmed
    except Exception as e:
        error = "Could not build the evacuation plan: " + str(e)
    stranded = [p for p in plan if p["unplaced"] > 0]
    return render_template("evacuate_all.html", plan=plan, totals=totals,
                           shelters=shelters, min_risk=min_risk,
                           stranded=stranded, error=error,
                           message=request.args.get("msg"),
                           is_admin=bool(session.get("is_admin")))


@app.route("/evacuate-all/confirm", methods=["POST"])
@admin_required
def confirm_evacuate_all():
    """Reserve shelter places for the whole plan and mark those people
    as evacuated. Only people who found a place are marked."""
    min_risk = _clean_risk(request.form.get("risk", "high"))
    try:
        network = load_network()
        plan = network.allocate_evacuation(min_risk)
        totals = RoadNetwork.plan_totals(plan)
        if totals["placed"] == 0:
            raise ValueError("Nobody could be placed, so nothing "
                             "was reserved.")
        save_evacuation(network, plan)
        msg = f"Reserved shelter places for {totals['placed']} people."
        if totals["unplaced"]:
            msg += (f" {totals['unplaced']} people still have no "
                    "shelter space or safe route.")
        return redirect(url_for("evacuate_all", risk=min_risk, msg=msg))
    except Exception as e:
        return redirect(url_for("evacuate_all", risk=min_risk, err=str(e)))


# ---------------------------------------------------------
# LIVE STATUS (the browser asks this every few seconds)
# ---------------------------------------------------------
@app.route("/api/status")
def api_status():
    """Returns a short 'version' fingerprint of every road and shelter.
    If the fingerprint changes, a road or shelter changed, so the
    page knows the route on screen may be out of date."""
    try:
        roads = get_road_status()
        network = load_network()
    except Exception as e:
        resp = jsonify({"ok": False, "error": str(e)})
        resp.status_code = 500
        resp.headers["Cache-Control"] = "no-store"
        return resp

    snapshot = {
        "roads": [[r[0], float(r[3]), r[4], r[5]] for r in roads],
        "shelters": [[s.name, s.capacity, s.occupied]
                     for s in network.shelters.values()],
    }
    version = hashlib.md5(
        json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    resp = jsonify({"ok": True, "version": version})
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------------------------------------------------
# WEIGHTED EDGES OF A ROUTE (for the weighted-graph view)
# ---------------------------------------------------------
def route_edges(route, graph):
    """One dict per road on the route: distance, flood penalty and
    the final graph weight (distance + penalty)."""
    edges = []
    for a, b in zip(route, route[1:]):
        data = graph[a][b]
        edges.append({
            "from": a,
            "to": b,
            "distance": data["distance"],
            "risk": data["risk"],
            "weight": data["weight"],
        })
    return edges


# ---------------------------------------------------------
# HOME PAGE
# ---------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def home():
    route = None
    distance = None
    error = None
    shelter = None
    resolved_destination = None
    zones = []
    people = 1
    route_risk = risk_label = None
    alt_route = alt_distance = alt_risk = alt_risk_label = None
    route_edge_list = alt_edge_list = None
    message = request.args.get("done")
    if request.args.get("fail"):
        error = request.args.get("fail")

    try:
        ensure_db()
    except Exception as e:
        error = "Database error: " + str(e)

    try:
        road_statuses = get_road_status()
    except Exception:
        road_statuses = []

    if request.method == "POST":
        source = request.form.get("source")
        destination = request.form.get("destination")
        try:
            people = max(int(request.form.get("people", "1")), 1)
        except ValueError:
            people = 1

        if not source or not destination:
            error = "Please select both starting location and destination."
        elif source == destination:
            error = "Starting location and destination cannot be the same."
        else:
            try:
                network = load_network()
                if destination == "AUTO":
                    shelter, route, distance = network.find_nearest_shelter(
                        source, people)
                    if shelter:
                        resolved_destination = shelter.name
                    else:
                        error = ("No reachable shelter has room for "
                                 f"{people} people.")
                else:
                    target = network.shelters.get(destination)
                    if target is not None and not target.can_fit(people):
                        error = (f"{destination} has only "
                                 f"{target.available()} places left.")
                    else:
                        route, distance = network.find_route(
                            source, destination)
                        resolved_destination = destination
                        shelter = target
                if route is None and not error:
                    error = "No safe route available between these locations."
                if route:
                    graph = network.build_graph()
                    route_risk = network.route_risk(route, graph)
                    risk_label = network.risk_label(route_risk)
                    route_edge_list = route_edges(route, graph)
                    alt = network.find_alternative_route(
                        source, resolved_destination, graph,
                        max_ratio=ALT_MAX_RATIO)
                    if alt:
                        alt_route, alt_distance, alt_risk = alt
                        alt_risk_label = network.risk_label(alt_risk)
                        alt_edge_list = route_edges(alt_route, graph)
            except Exception as e:
                error = "Route calculation error: " + str(e)

    # Hazard zones and shelters table
    shelters = []
    try:
        network = load_network()
        zones = list(network.zones.values())
        shelters = list(network.shelters.values())
    except Exception:
        pass

    return render_template(
        "index.html",
        locations=LOCATIONS,
        route=route,
        distance=distance,
        error=error,
        road_statuses=road_statuses,
        coords=COORDS,
        resolved_destination=resolved_destination,
        shelter=shelter,
        zones=zones,
        shelters=shelters,
        people=people,
        message=message,
        route_risk=route_risk,
        risk_label=risk_label,
        alt_route=alt_route,
        alt_distance=alt_distance,
        alt_risk=alt_risk,
        alt_risk_label=alt_risk_label,
        route_edges=route_edge_list,
        alt_edges=alt_edge_list,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))


        
    


                
