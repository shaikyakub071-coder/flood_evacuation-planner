"""
test_models.py - automated tests for models.py

Run from the project folder with:
    pip install pytest
    pytest -v
"""

import pytest

from models import Road, Shelter, HazardZone, RoadNetwork


# ---------------------------------------------------------
# A small test network (no database needed)
#
#   Home --1km low--> Mid --1km low--> Shelter A
#   Home --5km low--------------------> Shelter A  (longer, but also safe)
#   Mid  --1km high--> Shelter B
# ---------------------------------------------------------
def make_network():
    rows = [
        ("Home", "Mid", 1.0, "low", "open"),
        ("Mid", "Shelter A", 1.0, "low", "open"),
        ("Home", "Shelter A", 5.0, "low", "open"),
        ("Mid", "Shelter B", 1.0, "high", "open"),
    ]
    return RoadNetwork.from_rows(rows, ("Shelter A", "Shelter B"))


# =========================================================
# ROAD
# =========================================================
class TestRoad:
    def test_cost_is_distance_plus_penalty(self):
        assert Road("r", "A", "B", 2, "low").cost() == 2
        assert Road("r", "A", "B", 2, "medium").cost() == 12
        assert Road("r", "A", "B", 2, "high").cost() == 52

    def test_open_low_road_is_passable(self):
        assert Road("r", "A", "B", 1, "low", "open").is_passable()

    def test_blocked_road_is_not_passable(self):
        assert not Road("r", "A", "B", 1, "low", "blocked").is_passable()

    def test_submerged_road_is_not_passable(self):
        road = Road("r", "A", "B", 1, "submerged", "open")
        assert road.is_submerged()
        assert not road.is_passable()

    def test_block_and_open_change_state(self):
        road = Road("r", "A", "B", 1)
        road.block()
        assert not road.is_passable()
        road.open()
        assert road.is_passable()

    def test_flood_level_can_change(self):
        road = Road("r", "A", "B", 1, "low")
        road.set_flood_level("submerged")
        assert not road.is_passable()

    def test_text_is_cleaned(self):
        road = Road("r", "A", "B", 1, "  HIGH ", " Open ")
        assert road.flood_level == "high"
        assert road.status == "open"

    def test_bad_flood_level_is_rejected(self):
        with pytest.raises(ValueError):
            Road("r", "A", "B", 1, "hgih")
        with pytest.raises(ValueError):
            Road("r", "A", "B", 1).set_flood_level("rainy")

    def test_bad_status_is_rejected(self):
        with pytest.raises(ValueError):
            Road("r", "A", "B", 1, "low", "closed")

    def test_zero_or_negative_distance_is_rejected(self):
        with pytest.raises(ValueError):
            Road("r", "A", "B", 0)
        with pytest.raises(ValueError):
            Road("r", "A", "B", -3)


# =========================================================
# SHELTER
# =========================================================
class TestShelter:
    def test_available_places(self):
        assert Shelter("S", 100, 30).available() == 70

    def test_assign_reduces_space(self):
        shelter = Shelter("S", 100)
        shelter.assign(40)
        assert shelter.occupied == 40
        assert shelter.available() == 60

    def test_cannot_assign_more_than_capacity(self):
        shelter = Shelter("S", 10)
        with pytest.raises(ValueError):
            shelter.assign(11)
        assert shelter.occupied == 0          # nothing was reserved

    def test_cannot_assign_zero_people(self):
        with pytest.raises(ValueError):
            Shelter("S", 10).assign(0)

    def test_full_shelter(self):
        shelter = Shelter("S", 5)
        shelter.assign(5)
        assert shelter.is_full()
        assert not shelter.can_fit(1)

    def test_reset_empties_shelter(self):
        shelter = Shelter("S", 5, 5)
        shelter.reset()
        assert shelter.occupied == 0
        assert not shelter.is_full()


# =========================================================
# HAZARD ZONE
# =========================================================
class TestHazardZone:
    def test_zone_without_roads_is_low(self):
        assert HazardZone("Z").risk_level() == "low"

    def test_risk_is_worst_road(self):
        zone = HazardZone("Z")
        zone.add_road(Road("a", "Z", "B", 1, "low"))
        zone.add_road(Road("b", "Z", "C", 1, "high"))
        zone.add_road(Road("c", "Z", "D", 1, "medium"))
        assert zone.risk_level() == "high"

    def test_risk_changes_when_road_changes(self):
        road = Road("a", "Z", "B", 1, "low")
        zone = HazardZone("Z")
        zone.add_road(road)
        assert zone.risk_level() == "low"
        road.set_flood_level("submerged")
        assert zone.risk_level() == "submerged"


# =========================================================
# ROAD NETWORK - routing
# =========================================================
class TestRouting:
    def test_finds_shortest_route(self):
        route, km = make_network().find_route("Home", "Shelter A")
        assert route == ["Home", "Mid", "Shelter A"]
        assert km == 2.0

    def test_blocked_road_is_avoided(self):
        net = make_network()
        net.roads[0].block()                  # Home - Mid
        route, km = net.find_route("Home", "Shelter A")
        assert route == ["Home", "Shelter A"]
        assert km == 5.0

    def test_submerged_road_is_avoided(self):
        net = make_network()
        net.roads[1].set_flood_level("submerged")   # Mid - Shelter A
        route, _ = net.find_route("Home", "Shelter A")
        assert route == ["Home", "Shelter A"]

    def test_flooded_road_is_avoided_if_safer_way_exists(self):
        # Make the short way "high" flood: 1+50 + 1 = 52 > 5, so the
        # long safe road wins even though it is more km.
        net = make_network()
        net.roads[0].set_flood_level("high")  # Home - Mid
        route, km = net.find_route("Home", "Shelter A")
        assert route == ["Home", "Shelter A"]
        assert km == 5.0

    def test_no_route_when_everything_is_blocked(self):
        net = make_network()
        for road in net.roads:
            road.block()
        assert net.find_route("Home", "Shelter A") == (None, None)

    def test_unknown_place_gives_no_route(self):
        assert make_network().find_route("Nowhere", "Shelter A") == \
            (None, None)

    def test_road_state_change_changes_the_route(self):
        net = make_network()
        before, _ = net.find_route("Home", "Shelter A")
        net.roads[0].block()
        after, _ = net.find_route("Home", "Shelter A")
        assert before != after

    def test_cheaper_duplicate_road_is_kept(self):
        rows = [
            ("A", "B", 9.0, "low", "open"),
            ("A", "B", 2.0, "low", "open"),
        ]
        net = RoadNetwork.from_rows(rows, ("B",))
        _, km = net.find_route("A", "B")
        assert km == 2.0


# =========================================================
# ROAD NETWORK - alternative route and risk
# =========================================================
class TestAlternativeAndRisk:
    def test_alternative_route_is_different(self):
        net = make_network()
        best, _ = net.find_route("Home", "Shelter A")
        alt = net.find_alternative_route("Home", "Shelter A")
        assert alt is not None
        assert alt[0] != best
        assert alt[0] == ["Home", "Shelter A"]

    def test_alternative_skips_huge_detour(self):
        net = make_network()          # best = 2 km, only other = 5 km
        assert net.find_alternative_route(
            "Home", "Shelter A", max_ratio=2.0) is None

    def test_shortest_route_ignores_flood_penalty(self):
        rows = [
            ("A", "B", 1.0, "high", "open"),     # short but flooded
            ("B", "C", 1.0, "low", "open"),
            ("A", "D", 3.0, "low", "open"),      # longer but dry
            ("D", "C", 3.0, "low", "open"),
        ]
        net = RoadNetwork.from_rows(rows, ("C",))
        safest, _ = net.find_route("A", "C")
        shortest, km, risk = net.find_shortest_route("A", "C")
        assert safest == ["A", "D", "C"]
        assert shortest == ["A", "B", "C"]
        assert km == 2.0
        assert risk == 50

    def test_shortest_route_none_when_no_path(self):
        rows = [("A", "B", 1.0, "low", "open")]
        net = RoadNetwork.from_rows(rows, ("B",))
        assert net.find_shortest_route("A", "Z") is None

    def test_no_alternative_when_only_one_route(self):
        rows = [("A", "B", 1.0, "low", "open")]
        net = RoadNetwork.from_rows(rows, ("B",))
        assert net.find_alternative_route("A", "B") is None

    def test_risk_score_adds_penalties(self):
        rows = [
            ("A", "B", 1.0, "medium", "open"),    # 10
            ("B", "C", 1.0, "high", "open"),      # 50
        ]
        net = RoadNetwork.from_rows(rows, ("C",))
        assert net.route_risk(["A", "B", "C"]) == 60

    def test_safe_route_has_zero_risk(self):
        net = make_network()
        assert net.route_risk(["Home", "Mid", "Shelter A"]) == 0

    def test_risk_labels(self):
        assert RoadNetwork.risk_label(0) == "Very safe"
        assert RoadNetwork.risk_label(10) == "Low risk"
        assert RoadNetwork.risk_label(50) == "Moderate risk"
        assert RoadNetwork.risk_label(60) == "High risk"
        assert RoadNetwork.risk_label(None) == ""


# =========================================================
# ROAD NETWORK - shelters
# =========================================================
class TestShelterChoice:
    def test_nearest_shelter_is_chosen(self):
        net = make_network()
        shelter, route, km = net.find_nearest_shelter("Home", 1)
        assert shelter.name == "Shelter A"
        assert route == ["Home", "Mid", "Shelter A"]

    def test_full_shelter_is_skipped(self):
        net = make_network()
        net.shelters["Shelter A"].assign(500)         # fill it
        shelter, route, _ = net.find_nearest_shelter("Home", 1)
        assert shelter.name == "Shelter B"

    def test_shelter_too_small_for_group_is_skipped(self):
        net = make_network()
        net.shelters["Shelter A"].capacity = 10
        shelter, _, _ = net.find_nearest_shelter("Home", 50)
        assert shelter.name == "Shelter B"

    def test_no_shelter_when_all_full(self):
        net = make_network()
        for shelter in net.shelters.values():
            shelter.assign(500)
        assert net.find_nearest_shelter("Home", 1) == (None, None, None)

    def test_no_shelter_when_cut_off(self):
        net = make_network()
        for road in net.roads:
            road.block()
        assert net.find_nearest_shelter("Home", 1) == (None, None, None)


# =========================================================
# ROAD NETWORK - hazard zones and evacuation plan
# =========================================================
class TestEvacuationPlan:
    def test_shelters_are_not_hazard_zones(self):
        net = make_network()
        assert "Shelter A" not in net.zones
        assert "Home" in net.zones

    def test_plan_only_includes_zones_at_or_above_risk(self):
        net = make_network()
        # Mid touches a "high" road, Home only "low" roads.
        names = [p["zone"] for p in net.evacuation_plan("high")]
        assert names == ["Mid"]

    def test_plan_lists_most_dangerous_first(self):
        net = make_network()
        plan = net.evacuation_plan("low")
        assert plan[0]["zone"] == "Mid"               # high risk first

    def test_stranded_zone_has_no_shelter(self):
        net = make_network()
        for road in net.roads:
            road.block()
        plan = net.evacuation_plan("low")
        assert plan
        assert all(p["shelter"] is None for p in plan)

    def test_bad_risk_level_is_rejected(self):
        with pytest.raises(ValueError):
            make_network().evacuation_plan("extreme")


# =========================================================
# BAD DATABASE ROWS
# =========================================================
class TestBadRows:
    def test_bad_row_is_skipped_not_crashing(self):
        rows = [
            ("A", "B", 1.0, "low", "open"),
            ("B", "C", 1.0, "hgih", "open"),          # typo
            ("C", "D", 1.0, "low", "open"),
        ]
        net = RoadNetwork.from_rows(rows, ("D",))
        assert len(net.roads) == 2
        assert len(net.skipped) == 1
        assert "B - C" in net.skipped[0]


# =========================================================
# POPULATIONS AND SHELTER SPLITTING
# (make_network: Home is "low" risk, Mid is "high" risk;
#  Home -> Shelter A is nearest, Shelter B is farther)
# =========================================================
def with_population(**people):
    net = make_network()
    net.set_populations(people)
    return net


class TestPopulation:
    def test_population_starts_at_zero(self):
        assert HazardZone("Z").population == 0

    def test_negative_population_is_rejected(self):
        with pytest.raises(ValueError):
            HazardZone("Z").set_population(-1)

    def test_unknown_zone_name_is_ignored(self):
        net = make_network()
        net.set_populations({"Nowhere": 50, "Home": 7})
        assert net.zones["Home"].population == 7


class TestAllocation:
    def test_group_goes_to_nearest_shelter(self):
        plan = with_population(Home=100).allocate_evacuation("low")
        home = [p for p in plan if p["zone"] == "Home"][0]
        assert home["placed"] == 100
        assert home["unplaced"] == 0
        assert [(a["shelter"], a["people"]) for a in home["assignments"]] \
            == [("Shelter A", 100)]

    def test_group_is_split_when_nearest_shelter_fills(self):
        net = with_population(Home=100)
        net.shelters["Shelter A"].capacity = 60
        plan = net.allocate_evacuation("low")
        split = [(a["shelter"], a["people"])
                 for a in plan[0]["assignments"]]
        assert split == [("Shelter A", 60), ("Shelter B", 40)]
        assert plan[0]["unplaced"] == 0

    def test_people_left_over_when_shelters_are_too_small(self):
        net = with_population(Home=100)
        net.shelters["Shelter A"].capacity = 10
        net.shelters["Shelter B"].capacity = 10
        plan = net.allocate_evacuation("low")
        assert plan[0]["placed"] == 20
        assert plan[0]["unplaced"] == 80

    def test_cut_off_zone_has_everyone_unplaced(self):
        net = with_population(Home=40)
        for road in net.roads:
            road.block()
        plan = net.allocate_evacuation("low")
        assert plan[0]["assignments"] == []
        assert plan[0]["unplaced"] == 40

    def test_most_dangerous_zone_gets_space_first(self):
        # Only 50 places exist. Mid (high risk) must get them,
        # Home (low risk) is left without.
        net = with_population(Home=50, Mid=50)
        net.shelters["Shelter A"].capacity = 50
        net.shelters["Shelter B"].capacity = 0
        plan = net.allocate_evacuation("low")
        by_zone = {p["zone"]: p for p in plan}
        assert plan[0]["zone"] == "Mid"
        assert by_zone["Mid"]["unplaced"] == 0
        assert by_zone["Home"]["unplaced"] == 50

    def test_vulnerable_zone_goes_first_at_same_risk(self):
        rows = [("A", "S", 1.0, "low", "open"),
                ("B", "S", 1.0, "low", "open")]
        net = RoadNetwork.from_rows(rows, ("S",))
        net.shelters["S"].capacity = 50
        net.set_populations({"A": 50, "B": 50})
        net.set_vulnerable({"B": 20})
        plan = net.allocate_evacuation("low")
        by_zone = {p["zone"]: p for p in plan}
        assert plan[0]["zone"] == "B"
        assert by_zone["B"]["vulnerable"] == 20
        assert by_zone["B"]["unplaced"] == 0
        assert by_zone["A"]["unplaced"] == 50

    def test_danger_still_beats_vulnerable_count(self):
        net = with_population(Home=50, Mid=50)
        net.set_vulnerable({"Home": 50})
        plan = net.allocate_evacuation("low")
        assert plan[0]["zone"] == "Mid"          # high risk first

    def test_vulnerable_are_placed_first_inside_zone(self):
        rows = [("A", "S", 1.0, "low", "open")]
        net = RoadNetwork.from_rows(rows, ("S",))
        net.shelters["S"].capacity = 30
        net.set_populations({"A": 100})
        net.set_vulnerable({"A": 20})
        item = net.allocate_evacuation("low")[0]
        assert item["placed"] == 30
        assert item["vulnerable_left"] == 0      # all 20 got a place
        net.shelters["S"].capacity = 10
        net.shelters["S"].occupied = 0
        item = net.allocate_evacuation("low")[0]
        assert item["vulnerable_left"] == 10     # only 10 of 20 placed

    def test_negative_vulnerable_is_rejected(self):
        with pytest.raises(ValueError):
            HazardZone("Z").set_vulnerable(-1)

    def test_zones_without_people_are_left_out(self):
        plan = with_population(Mid=30).allocate_evacuation("low")
        assert [p["zone"] for p in plan] == ["Mid"]

    def test_risk_filter_is_respected(self):
        net = with_population(Home=10, Mid=10)
        names = [p["zone"] for p in net.allocate_evacuation("high")]
        assert names == ["Mid"]

    def test_places_are_reserved_in_memory(self):
        net = with_population(Home=120)
        net.allocate_evacuation("low")
        assert net.shelters["Shelter A"].occupied == 120

    def test_totals_add_up(self):
        net = with_population(Home=100, Mid=50)
        net.shelters["Shelter A"].capacity = 20
        net.shelters["Shelter B"].capacity = 20
        totals = RoadNetwork.plan_totals(net.allocate_evacuation("low"))
        assert totals == {"total": 150, "placed": 40, "unplaced": 110}

    def test_bad_risk_level_is_rejected(self):
        with pytest.raises(ValueError):
            make_network().allocate_evacuation("extreme")



                    
    
    
