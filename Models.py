"""
models.py  -  OOP model for the Flood Evacuation Route Planner.

Classes:
    Road         - one road with a dynamic state (flood level + open/blocked)
    Shelter      - a designated evacuation shelter
    HazardZone   - a flood-prone location, risk comes from its roads
    RoadNetwork  - the whole graph, finds the safest shortest route
"""

import networkx as nx


class Road:
    """A road between two locations. Its state can change at any time."""

    FLOOD_PENALTY = {"low": 0, "medium": 10, "high": 50}

    def __init__(self, name, start, end, distance_km,
                 flood_level="low", status="open"):
        self.name = name
        self.start = start
        self.end = end
        self.distance_km = float(distance_km)
        self.flood_level = str(flood_level).strip().lower()
        self.status = str(status).strip().lower()

    # ---- dynamic state -------------------------------------------------
    def block(self):
        self.status = "blocked"

    def open(self):
        self.status = "open"

    def set_flood_level(self, level):
        level = str(level).strip().lower()
        if level not in self.FLOOD_PENALTY:
            raise ValueError("flood level must be low, medium or high")
        self.flood_level = level
        # A road with a high flood level is treated as submerged
        # only if you block it yourself; high just costs a big penalty.

    # ---- routing helpers -----------------------------------------------
    def is_passable(self):
        return self.status != "blocked"

    def risk_penalty(self):
        return self.FLOOD_PENALTY.get(self.flood_level, 0)

    def cost(self):
        """Cost used by the shortest-path algorithm (distance + risk)."""
        return self.distance_km + self.risk_penalty()

    def __repr__(self):
        return (f"Road({self.start} - {self.end}, {self.distance_km} km, "
                f"{self.flood_level}, {self.status})")


class Shelter:
    """A designated safe place people are evacuated to."""

    def __init__(self, name, capacity=500):
        self.name = name
        self.capacity = capacity

    def __repr__(self):
        return f"Shelter({self.name}, capacity={self.capacity})"


class HazardZone:
    """A flood-prone location. Its danger = the worst flood on its roads."""

    ORDER = ["low", "medium", "high"]

    def __init__(self, name):
        self.name = name
        self.roads = []

    def add_road(self, road):
        self.roads.append(road)

    def risk_level(self):
        if not self.roads:
            return "low"
        return max((r.flood_level for r in self.roads),
                   key=lambda lvl: self.ORDER.index(lvl)
                   if lvl in self.ORDER else 0)

    def __repr__(self):
        return f"HazardZone({self.name}, risk={self.risk_level()})"


class RoadNetwork:
    """Holds roads, shelters and zones and computes evacuation routes."""

    def __init__(self, shelter_names=("Evacuation Center",)):
        self.roads = []
        self.shelters = {n: Shelter(n) for n in shelter_names}
        self.zones = {}

    # ---- building the network ------------------------------------------
    @classmethod
    def from_rows(cls, rows, shelter_names=("Evacuation Center",)):
        """rows = (start, end, distance_km, flood_level, road_status)"""
        network = cls(shelter_names)
        for start, end, dist, flood, status in rows:
            network.add_road(Road(f"{start} - {end}", start, end,
                                  dist, flood, status))
        return network

    def add_road(self, road):
        self.roads.append(road)
        for place in (road.start, road.end):
            if place in self.shelters:
                continue
            zone = self.zones.setdefault(place, HazardZone(place))
            zone.add_road(road)

    # ---- graph ----------------------------------------------------------
    def build_graph(self):
        graph = nx.Graph()
        for road in self.roads:
            if not road.is_passable():
                continue                      # blocked / submerged road
            graph.add_edge(road.start, road.end,
                           weight=road.cost(),
                           distance=road.distance_km)
        return graph

    # ---- routing --------------------------------------------------------
    def find_route(self, source, destination):
        """Returns (route_list, total_km) or (None, None)."""
        graph = self.build_graph()
        try:
            route = nx.shortest_path(graph, source, destination,
                                     weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None, None
        total = sum(graph[a][b]["distance"]
                    for a, b in zip(route, route[1:]))
        return route, total

    def find_nearest_shelter(self, source):
        """Best reachable shelter from a location: (shelter, route, km)."""
        best = None
        for shelter in self.shelters.values():
            route, km = self.find_route(source, shelter.name)
            if route is None:
                continue
            graph = self.build_graph()
            cost = nx.path_weight(graph, route, "weight")
            if best is None or cost < best[0]:
                best = (cost, shelter, route, km)
        if best is None:
            return None, None, None
        return best[1], best[2], best[3]
