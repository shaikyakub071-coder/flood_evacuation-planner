from flask import Flask, render_template, request
import psycopg2
import os

from models import RoadNetwork

app = Flask(__name__)

LOCATIONS = [
    "Nandyal Bus Stand",
    "Government Hospital",
    "Railway Station",
    "Evacuation Center",
]
SHELTERS = ("Evacuation Center",)

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
    ]
    for road in sample_roads:
        cur.execute("""
            INSERT INTO roads (road_name, start_location, end_location,
                               distance_km, flood_level, road_status)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (road_name) DO NOTHING
        """, road)
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
    cur.close()
    conn.close()
    return RoadNetwork.from_rows(rows, SHELTERS)


# ---------------------------------------------------------
# HOME PAGE
# ---------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def home():
    global _db_ready
    route = None
    distance = None
    error = None

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

        if not source or not destination:
            error = "Please select both starting location and destination."
        elif source == destination:
            error = "Starting location and destination cannot be the same."
        else:
            try:
                network = load_network()
                route, distance = network.find_route(source, destination)
                if route is None:
                    error = "No safe route available between these locations."
            except Exception as e:
                error = "Route calculation error: " + str(e)

    return render_template(
        "index.html",
        locations=LOCATIONS,
        route=route,
        distance=distance,
        error=error,
        road_statuses=road_statuses,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

