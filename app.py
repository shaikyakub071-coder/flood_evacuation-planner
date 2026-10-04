from flask import Flask, render_template, request, redirect, url_for
import psycopg2
import os

from models import Road, RoadNetwork, Shelter

app = Flask(__name__)

# Simulated coordinates (latitude, longitude) around Nandyal
COORDS = {
    "Nandyal Bus Stand":        [15.4786, 78.4836],
    "Government Hospital":      [15.4815, 78.4855],
    "Railway Station":          [15.4775, 78.4820],
    "Evacuation Center":        [15.4860, 78.4900],
    "Kundu River Bank":         [15.4740, 78.4800],
    "Market Yard":              [15.4800, 78.4800],
    "Gandhi Chowk":             [15.4830, 78.4820],
    "Srinivasa Nagar":          [15.4760, 78.4870],
    "Municipal School Shelter": [15.4850, 78.4840],
    "Community Hall Shelter":   [15.4790, 78.4900],
}

# Designated shelters: name -> capacity (people)
SHELTER_INFO = {
    "Evacuation Center": 1000,
    "Municipal School Shelter": 600,
    "Community Hall Shelter": 400,
}
SHELTERS = tuple(SHELTER_INFO.keys())

LOCATIONS = list(COORDS.keys())

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
    sample_roads = [
        ("Bus Stand - Government Hospital", "Nandyal Bus Stand",
         "Government Hospital", 2.0, "low", "open"),
        ("Government Hospital - Railway Station", "Government Hospital",
         "Railway Station", 1.5, "medium", "open"),
        ("Railway Station - Evacuation Center", "Railway Station",
         "Evacuation Center", 2.0, "low", "open"),
        ("Bus Stand - Railway Station", "Nandyal Bus Stand",
         "Railway Station", 3.5, "high", "open"),
        ("Government Hospital - Evacuation Center", "Government Hospital",
         "Evacuation Center", 3.0, "low", "open"),
        ("Bus Stand - Evacuation Center", "Nandyal Bus Stand",
         "Evacuation Center", 5.0, "medium", "blocked"),
        ("River Bank - Railway Station", "Kundu River Bank",
         "Railway Station", 1.8, "high", "open"),
        ("River Bank - Market Yard", "Kundu River Bank",
         "Market Yard", 2.2, "high", "open"),
        ("Market Yard - Bus Stand", "Market Yard",
         "Nandyal Bus Stand", 1.5, "medium", "open"),
        ("Market Yard - Gandhi Chowk", "Market Yard",
         "Gandhi Chowk", 2.0, "low", "open"),
        ("Gandhi Chowk - Government Hospital", "Gandhi Chowk",
         "Government Hospital", 1.2, "low", "open"),
        ("Gandhi Chowk - Municipal School", "Gandhi Chowk",
         "Municipal School Shelter", 1.5, "low", "open"),
        ("Government Hospital - Municipal School", "Government Hospital",
         "Municipal School Shelter", 1.8, "low", "open"),
        ("Srinivasa Nagar - Bus Stand", "Srinivasa Nagar",
         "Nandyal Bus Stand", 1.4, "medium", "open"),
        ("Srinivasa Nagar - Community Hall", "Srinivasa Nagar",
         "Community Hall Shelter", 2.5, "low", "open"),
        ("Community Hall - Evacuation Center", "Community Hall Shelter",
         "Evacuation Center", 2.0, "low", "open"),
        ("Railway Station - Srinivasa Nagar", "Railway Station",
         "Srinivasa Nagar", 1.6, "medium", "open"),
    ]
    for road in sample_roads:
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
    conn.commit()
    cur.close()
    conn.close()


def get_road_status():
    """Rows for the road table in index.html."""
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


def load_network():
    """Read the roads table and build the OOP RoadNetwork."""
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
    cur.close()
    conn.close()
    network = RoadNetwork.from_rows(rows, SHELTERS)
    for name, cap, occ in shelter_rows:
        network.shelters[name] = Shelter(name, cap, occ)
    return network


def save_shelter_occupancy(shelter):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE shelters SET occupied = %s WHERE name = %s",
                (shelter.occupied, shelter.name))
    conn.commit()
    cur.close()
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
# ADMIN PAGE (authorities update flood / road conditions)
# ---------------------------------------------------------
@app.route("/admin")
def admin():
    message = request.args.get("msg")
    error = request.args.get("err")
    shelters = []
    try:
        roads = get_road_status()
        shelters = list(load_network().shelters.values())
    except Exception as e:
        roads = []
        error = "Database error: " + str(e)
    return render_template("admin.html", roads=roads, shelters=shelters,
                           message=message, error=error)


@app.route("/reset_shelters", methods=["POST"])
def reset_shelters():
    """Empty all shelters (e.g. when an emergency is over)."""
    try:
        network = load_network()
        for shelter in network.shelters.values():
            shelter.reset()
            save_shelter_occupancy(shelter)
        return redirect(url_for("admin", msg="All shelters reset to empty"))
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
# HOME PAGE
# ---------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def home():
    global _db_ready
    route = None
    distance = None
    error = None
    shelter = None
    resolved_destination = None
    zones = []
    people = 1
    message = request.args.get("done")
    if request.args.get("fail"):
        error = request.args.get("fail")

    if not _db_ready:
        try:
            initialize_database()
            _db_ready = True
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
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
