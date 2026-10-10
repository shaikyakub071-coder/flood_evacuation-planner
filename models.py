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
    VALID_STATUS = ("open", "blocked")

    def __init__(self, name, start, end, distance_km,
                 flood_level="low", status="open"):
        self.name = name
        self.start = start
        self.end = end
        self.distance_km = float(distance_km)
        if self.distance_km <= 0:
            raise ValueError(f"{name}: distance must be more than 0")
        # Validate here so a typo in the database can never be
        # silently treated as "no risk".
        self.flood_level = "low"
        self.status = "open"
        self.set_flood_level(flood_level)
        self.set_status(status)

    # ---- dynamic state -------------------------------------------------
    def block(self):
        self.status = "blocked"

    def open(self):
        self.status = "open"

    def set_status(self, status):
        status = str(status).strip().lower()
        if status not in self.VALID_STATUS:
            raise ValueError("road status must be open or blocked")
        self.status = status

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
        return self.FLOOD_PENALTY[self.flood_level]

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

    def __init__(self, name, population=0):
        self.name = name
        self.roads = []
        self.population = 0           # people still waiting to be evacuated
        self.set_population(population)

    def set_population(self, people):
        people = int(people)
        if people < 0:
            raise ValueError("population cannot be negative")
        self.population = people

    def add_road(self, road):
        self.roads.append(road)

    def risk_level(self):
        if not self.roads:
            return "low"
        return max((r.flood_level for r in self.roads),
                   key=self.ORDER.index)

    def __repr__(self):
        return f"HazardZone({self.name}, risk={self.risk_level()})"


class RoadNetwork:
    """Holds roads, shelters and zones and computes evacuation routes."""

    def __init__(self, shelter_names=("Evacuation Center",)):
        self.roads = []
        self.shelters = {n: Shelter(n) for n in shelter_names}
        self.zones = {}
        self.skipped = []     # database rows that were invalid

    # ---- building the network ------------------------------------------
    @classmethod
    def from_rows(cls, rows, shelter_names=("Evacuation Center",)):
        """rows = (start, end, distance_km, flood_level, road_status)
        A row with bad data is skipped (and listed in network.skipped)
        instead of crashing the whole app."""
        network = cls(shelter_names)
        for start, end, dist, flood, status in rows:
            try:
                network.add_road(Road(f"{start} - {end}", start, end,
                                      dist, flood, status))
            except ValueError as e:
                network.skipped.append(f"{start} - {end}: {e}")
        return network

    def add_road(self, road):
        self.roads.append(road)
        # Shelters are destinations, not hazard zones, so only the
        # non-shelter end(s) of a road are tracked as zones.
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
            weight = road.cost()
            # If two roads join the same places, keep the cheaper one.
            if graph.has_edge(road.start, road.end) and \
                    graph[road.start][road.end]["weight"] <= weight:
                continue
            graph.add_edge(road.start, road.end,
                           weight=weight,
                           distance=road.distance_km,
                           risk=road.risk_penalty())
        return graph

    # ---- risk helpers ---------------------------------------------------
    def route_risk(self, route, graph=None):
        """Total flood-risk score of a route (sum of road penalties).
        0 means every road on the route has a low flood level."""
        if not route:
            return None
        if graph is None:
            graph = self.build_graph()
        return sum(graph[a][b]["risk"] for a, b in zip(route, route[1:]))

    @staticmethod
    def risk_label(score):
        """Plain-words label for a route risk score."""
        if score is None:
            return ""
        if score == 0:
            return "Very safe"
        if score <= 20:
            return "Low risk"
        if score <= 50:
            return "Moderate risk"
        return "High risk"

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

    def find_shortest_route(self, source, destination, graph=None):
        """Plain shortest route by DISTANCE ONLY (flood penalty ignored).
        Used for comparison with the safest route. It still never uses
        blocked or submerged roads, because those are not in the graph.
        Returns (route, km, risk) or None if there is no route."""
        if graph is None:
            graph = self.build_graph()
        try:
            route = nx.shortest_path(graph, source, destination,
                                     weight="distance")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None
        km = sum(graph[a][b]["distance"] for a, b in zip(route, route[1:]))
        return route, km, self.route_risk(route, graph)

    def find_alternative_route(self, source, destination, graph=None,
                               max_ratio=3.0, max_candidates=10):
        """Next-best route that is different from the best one AND not
        a huge detour: its length may be at most `max_ratio` times the
        best route's length. Looks at up to `max_candidates` routes.
        Returns (route, km, risk) or None if there is no sensible one."""
        if graph is None:
            graph = self.build_graph()
        try:
            paths = nx.shortest_simple_paths(graph, source, destination,
                                             weight="weight")
            best = next(paths)                # skip the best route
            best_km = sum(graph[a][b]["distance"]
                          for a, b in zip(best, best[1:]))
            for _ in range(max_candidates):
                alt = next(paths)
                km = sum(graph[a][b]["distance"]
                         for a, b in zip(alt, alt[1:]))
                if km <= best_km * max_ratio:
                    return alt, km, self.route_risk(alt, graph)
        except (nx.NetworkXNoPath, nx.NodeNotFound, StopIteration):
            pass
        return None

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
        if min_risk not in order:
            raise ValueError("min_risk must be one of " + ", ".join(order))
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

    # ---- populations and shelter splitting ------------------------------
    def set_populations(self, mapping):
        """mapping = {zone_name: people}. Unknown zone names are ignored."""
        for name, people in mapping.items():
            if name in self.zones:
                self.zones[name].set_population(people)

    def allocate_evacuation(self, min_risk="high"):
        """Plan where EVERY person in the dangerous zones goes.

        Zones at or above `min_risk` are served most dangerous first.
        A zone's people go to the nearest shelter with room; if that
        shelter fills up, the rest go to the next nearest, and so on
        (the group is SPLIT). People who cannot be placed (no safe road
        or no space left) are reported as `unplaced`.

        Places are reserved on the Shelter objects in memory ONLY.
        Nothing is saved: the caller decides whether to keep it.

        Returns a list of dicts:
          zone, risk, population, placed, unplaced,
          assignments = [{shelter, people, route, distance}, ...]
        Zones with nobody left to evacuate are left out."""
        order = HazardZone.ORDER
        if min_risk not in order:
            raise ValueError("min_risk must be one of " + ", ".join(order))
        threshold = order.index(min_risk)
        graph = self.build_graph()            # built once for all zones

        chosen = [z for z in self.zones.values()
                  if order.index(z.risk_level()) >= threshold
                  and z.population > 0]
        chosen.sort(key=lambda z: (-order.index(z.risk_level()), z.name))

        plan = []
        for zone in chosen:
            remaining = zone.population
            assignments = []
            while remaining > 0:
                shelter, route, km = self.find_nearest_shelter(
                    zone.name, 1, graph)      # nearest shelter with room
                if shelter is None:
                    break                     # no road or no space left
                take = min(remaining, shelter.available())
                shelter.assign(take)
                assignments.append({
                    "shelter": shelter.name,
                    "people": take,
                    "route": route,
                    "distance": km,
                })
                remaining -= take
            plan.append({
                "zone": zone.name,
                "risk": zone.risk_level(),
                "population": zone.population,
                "placed": zone.population - remaining,
                "unplaced": remaining,
                "assignments": assignments,
            })
        return plan

    @staticmethod
    def plan_totals(plan):
        """Total people, placed and unplaced across a plan."""
        total = sum(p["population"] for p in plan)
        placed = sum(p["placed"] for p in plan)
        return {"total": total, "placed": placed, "unplaced": total - placed}

