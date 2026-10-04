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

    # "submerged" = road is under water, so it can never be used.
    FLOOD_PENALTY = {"low": 0, "medium": 10, "high": 50, "submerged": 1000}

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
            raise ValueError(
                "flood level must be low, medium, high or submerged")
        self.flood_level = level

    # ---- routing helpers -----------------------------------------------
    def is_submerged(self):
        return self.flood_level == "submerged"

    def is_passable(self):
        """A road is unusable if it is blocked OR submerged."""
        return self.status != "blocked" and not self.is_submerged()

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

    def __init__(self, name, capacity=500, occupied=0):
        self.name = name
        self.capacity = int(capacity)
        self.occupied = int(occupied)

    # ---- dynamic state -------------------------------------------------
    def available(self):
        """Free places left in this shelter."""
        return max(self.capacity - self.occupied, 0)

    def is_full(self):
        return self.available() == 0

    def can_fit(self, people):
        return self.available() >= people

    def assign(self, people):
        """Reserve places for evacuees. Raises if there is no room."""
        if people < 1:
            raise ValueError("number of people must be at least 1")
        if not self.can_fit(people):
            raise ValueError(
                f"{self.name} has only {self.available()} places left")
        self.occupied += people

    def reset(self):
        self.occupied = 0

    def __repr__(self):
        return (f"Shelter({self.name}, {self.occupied}/{self.capacity} "
                f"occupied)")


class HazardZone:
    """A flood-prone location. Its danger = the worst flood on its roads."""

    ORDER = ["low", "medium", "high", "submerged"]

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
    def find_route(self, source, destination, graph=None):
        """Returns (route_list, total_km) or (None, None).
        Pass a pre-built graph to avoid rebuilding it."""
        if graph is None:
            graph = self.build_graph()
        try:
            route = nx.shortest_path(graph, source, destination,
                                     weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None, None
        total = sum(graph[a][b]["distance"]
                    for a, b in zip(route, route[1:]))
        return route, total

    def find_nearest_shelter(self, source, people=1, graph=None):
        """Best reachable shelter with enough free places for `people`:
        returns (shelter, route, km). Full shelters are skipped.
        Pass a pre-built graph to avoid rebuilding it."""
        if graph is None:
            graph = self.build_graph()        # built once, reused below
        best = None
        for shelter in self.shelters.values():
            if not shelter.can_fit(people):
                continue                      # shelter is full / too small
            route, km = self.find_route(source, shelter.name, graph)
            if route is None:
                continue
            cost = nx.path_weight(graph, route, "weight")
            if best is None or cost < best[0]:
                best = (cost, shelter, route, km)
        if best is None:
            return None, None, None
        return best[1], best[2], best[3]

    def evacuation_plan(self, min_risk="high", people=1):
        """Safest route from EVERY hazard zone at or above `min_risk`
        to its best shelter. Returns a list of dicts, most dangerous
        zones first. A zone with no safe route has shelter=None."""
        order = HazardZone.ORDER
        threshold = order.index(min_risk)
        graph = self.build_graph()            # built once for all zones
        plan = []
        for zone in self.zones.values():
            level = zone.risk_level()
            if order.index(level) < threshold:
                continue
            shelter, route, km = self.find_nearest_shelter(
                zone.name, people, graph)
            plan.append({
                "zone": zone.name,
                "risk": level,
                "shelter": shelter.name if shelter else None,
                "route": route,
                "distance": km,
            })
        plan.sort(key=lambda p: (-order.index(p["risk"]), p["zone"]))
        return plan
