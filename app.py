from flask import Flask, render_template, request
import psycopg2
import networkx as nx
import os

app = Flask(__name__)


# ==========================================
# DATABASE CONNECTION
# ==========================================

def get_connection():
    db_url = os.environ.get("DATABASE_URL")

    if not db_url:
        raise Exception("DATABASE_URL is not configured on Render.")

    # Render may provide postgres://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    return psycopg2.connect(db_url)


# ==========================================
# CREATE DATABASE TABLE + SAMPLE DATA
# ==========================================

def initialize_database():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
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

    # Sample road network
    roads = [
        (
            "Bus Stand - Government Hospital",
            "Nandyal Bus Stand",
            "Government Hospital",
            2.0,
            "low",
            "open"
        ),
        (
            "Government Hospital - Railway Station",
            "Government Hospital",
            "Railway Station",
            1.5,
            "medium",
            "open"
        ),
        (
            "Railway Station - Evacuation Center",
            "Railway Station",
            "Evacuation Center",
            2.0,
            "low",
            "open"
        ),
        (
            "Bus Stand - Railway Station",
            "Nandyal Bus Stand",
            "Railway Station",
            3.5,
            "high",
            "open"
        ),
        (
            "Government Hospital - Evacuation Center",
            "Government Hospital",
            "Evacuation Center",
            3.0,
            "low",
            "open"
        ),
        (
            "Bus Stand - Evacuation Center",
            "Nandyal Bus Stand",
            "Evacuation Center",
            5.0,
            "medium",
            "blocked"
        )
    ]

    for road in roads:

        cursor.execute("""
            INSERT INTO roads
            (
                road_name,
                start_location,
                end_location,
                distance_km,
                flood_level,
                road_status
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (road_name) DO NOTHING
        """, road)

    conn.commit()

    cursor.close()
    conn.close()


# ==========================================
# GET ROAD STATUS
# ==========================================

def get_road_status():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            road_name,
            start_location,
            end_location,
            distance_km,
            flood_level,
            road_status
        FROM roads
        ORDER BY road_name
    """)

    roads = cursor.fetchall()

    cursor.close()
    conn.close()

    return roads


# ==========================================
# FIND SAFE EVACUATION ROUTE
# ==========================================

def find_route(source, destination):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            start_location,
            end_location,
            distance_km,
            flood_level,
            road_status
        FROM roads
    """)

    roads = cursor.fetchall()

    cursor.close()
    conn.close()

    G = nx.Graph()

    for start, end, distance, flood_level, status in roads:

        status = str(status).strip().lower()
        flood_level = str(flood_level).strip().lower()

        # Ignore blocked roads
        if status == "blocked":
            continue

        # Flood-risk penalty
        if flood_level == "low":
            risk_penalty = 0
        elif flood_level == "medium":
            risk_penalty = 10
        elif flood_level == "high":
            risk_penalty = 50
        else:
            risk_penalty = 0

        route_cost = float(distance) + risk_penalty

        G.add_edge(
            start,
            end,
            weight=route_cost,
            distance=float(distance)
        )

    try:

        route = nx.shortest_path(
            G,
            source=source,
            target=destination,
            weight="weight"
        )

        total_cost = nx.shortest_path_length(
            G,
            source=source,
            target=destination,
            weight="weight"
        )

        return route, total_cost

    except (nx.NetworkXNoPath, nx.NodeNotFound):

        return None, None


# ==========================================
# HOME PAGE
# ==========================================

@app.route("/", methods=["GET", "POST"])
def home():

    route = None
    distance = None
    error = None

    locations = [
        "Nandyal Bus Stand",
        "Government Hospital",
        "Railway Station",
        "Evacuation Center"
    ]

    # Initialize database
    try:
        initialize_database()
    except Exception as e:
        error = "Database error: " + str(e)

    # Get road information
    try:
        road_statuses = get_road_status()
    except Exception:
        road_statuses = []

    # Route form
    if request.method == "POST":

        source = request.form.get("source")
        destination = request.form.get("destination")

        if not source or not destination:

            error = "Please select both starting location and destination."

        elif source == destination:

            error = "Starting location and destination cannot be the same."

        else:

            try:

                route, distance = find_route(
                    source,
                    destination
                )

                if route is None:
                    error = "No safe route available between these locations."

            except Exception as e:

                error = "Route calculation error: " + str(e)

    return render_template(
        "index.html",
        locations=locations,
        route=route,
        distance=distance,
        error=error,
        road_statuses=road_statuses
    )


# ==========================================
# START SERVER
# ==========================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
    )
