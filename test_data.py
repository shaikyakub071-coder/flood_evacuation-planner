"""
test_data.py - tests for data_loader.py and for the real data.json

Run from the project folder with:
    pytest -v
"""

import copy
import json
import os
import tempfile

import pytest

from data_loader import DataError, load_data, validate_data

HERE = os.path.dirname(os.path.abspath(__file__))


def good():
    """A small, valid data set (a fresh copy every call)."""
    return copy.deepcopy({
        "locations": {
            "Home": [15.0, 78.0],
            "Mid": [15.1, 78.1],
            "Shelter A": [15.2, 78.2],
        },
        "shelters": {"Shelter A": 100},
        "zone_population": {"Home": 40, "Mid": 0},
        "roads": [
            {"name": "Home - Mid", "start": "Home", "end": "Mid",
             "distance_km": 1.5, "flood_level": "low", "status": "open"},
            {"name": "Mid - Shelter A", "start": "Mid", "end": "Shelter A",
             "distance_km": 2, "flood_level": "HIGH", "status": " Open "},
        ],
    })


def problems_of(data):
    """The error text produced by invalid data."""
    with pytest.raises(DataError):
        validate_data(data)
    try:
        validate_data(data)
    except DataError as e:
        return str(e)


# =========================================================
# VALID DATA
# =========================================================
class TestValidData:
    def test_good_data_loads(self):
        clean = validate_data(good())
        assert set(clean["locations"]) == {"Home", "Mid", "Shelter A"}
        assert clean["shelters"] == {"Shelter A": 100}
        assert clean["zone_population"] == {"Home": 40, "Mid": 0}
        assert len(clean["roads"]) == 2

    def test_text_is_cleaned_and_numbers_converted(self):
        road = validate_data(good())["roads"][1]
        assert road["flood_level"] == "high"
        assert road["status"] == "open"
        assert road["distance_km"] == 2.0
        assert isinstance(road["distance_km"], float)

    def test_flood_level_and_status_are_optional(self):
        data = good()
        del data["roads"][0]["flood_level"]
        del data["roads"][0]["status"]
        road = validate_data(data)["roads"][0]
        assert road["flood_level"] == "low"
        assert road["status"] == "open"

    def test_zone_population_is_optional(self):
        data = good()
        del data["zone_population"]
        assert validate_data(data)["zone_population"] == {}


# =========================================================
# LOCATIONS
# =========================================================
class TestLocations:
    def test_missing_locations(self):
        data = good()
        del data["locations"]
        assert '"locations" must be' in problems_of(data)

    def test_coordinates_must_be_a_pair_of_numbers(self):
        for bad in ([1], [1, 2, 3], "15,78", ["a", "b"], [True, False]):
            data = good()
            data["locations"]["Home"] = bad
            assert "latitude, longitude" in problems_of(data)

    def test_coordinates_must_be_on_earth(self):
        data = good()
        data["locations"]["Home"] = [95.0, 78.0]
        assert "-90..90" in problems_of(data)
        data["locations"]["Home"] = [15.0, 200.0]
        assert "-180..180" in problems_of(data)


# =========================================================
# SHELTERS AND ZONES
# =========================================================
class TestShelters:
    def test_shelter_must_be_a_known_location(self):
        data = good()
        data["shelters"]["Nowhere Hall"] = 50
        assert 'shelter "Nowhere Hall"' in problems_of(data)

    def test_capacity_must_be_a_positive_whole_number(self):
        for bad in (0, -5, 10.5, "100", None, True):
            data = good()
            data["shelters"]["Shelter A"] = bad
            assert "capacity" in problems_of(data)

    def test_need_at_least_one_shelter(self):
        data = good()
        data["shelters"] = {}
        assert '"shelters" must be' in problems_of(data)


class TestZones:
    def test_zone_must_be_a_known_location(self):
        data = good()
        data["zone_population"]["Atlantis"] = 10
        assert 'zone "Atlantis"' in problems_of(data)

    def test_a_shelter_cannot_be_a_zone(self):
        data = good()
        data["zone_population"]["Shelter A"] = 10
        assert "is a shelter" in problems_of(data)

    def test_population_must_be_whole_and_not_negative(self):
        for bad in (-1, 2.5, "40", None):
            data = good()
            data["zone_population"]["Home"] = bad
            assert "population" in problems_of(data)


# =========================================================
# ROADS
# =========================================================
class TestRoads:
    def test_need_at_least_one_road(self):
        data = good()
        data["roads"] = []
        assert '"roads" must be' in problems_of(data)

    def test_road_needs_a_name(self):
        data = good()
        del data["roads"][0]["name"]
        assert "needs a text" in problems_of(data)

    def test_road_ends_must_be_known_places(self):
        data = good()
        data["roads"][0]["end"] = "Mdi"            # typo of "Mid"
        text = problems_of(data)
        assert '"end" is "Mdi"' in text

    def test_road_cannot_start_and_end_at_same_place(self):
        data = good()
        data["roads"][0]["end"] = "Home"
        assert "start and end are the same" in problems_of(data)

    def test_distance_must_be_a_positive_number(self):
        for bad in (0, -2, "3", None, True):
            data = good()
            data["roads"][0]["distance_km"] = bad
            assert "distance_km" in problems_of(data)

    def test_flood_level_typo_is_caught(self):
        data = good()
        data["roads"][0]["flood_level"] = "hgih"
        assert "flood_level" in problems_of(data)

    def test_status_typo_is_caught(self):
        data = good()
        data["roads"][0]["status"] = "closed"
        assert "status" in problems_of(data)

    def test_duplicate_road_names_are_caught(self):
        data = good()
        data["roads"][1]["name"] = "Home - Mid"
        assert "used twice" in problems_of(data)


class TestAllProblemsReportedTogether:
    def test_several_mistakes_are_listed_at_once(self):
        data = good()
        data["roads"][0]["flood_level"] = "hgih"
        data["roads"][1]["distance_km"] = -1
        data["shelters"]["Shelter A"] = 0
        text = problems_of(data)
        assert "3 problem(s)" in text


# =========================================================
# FILES
# =========================================================
class TestFiles:
    def test_load_data_reads_a_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "d.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(good(), f)
            assert len(load_data(path)["roads"]) == 2

    def test_missing_file(self):
        with pytest.raises(DataError):
            load_data(os.path.join(HERE, "no_such_file.json"))

    def test_broken_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "d.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"locations": {')           # cut off
            with pytest.raises(DataError):
                load_data(path)

    def test_json_that_is_not_an_object(self):
        with pytest.raises(DataError):
            validate_data([1, 2, 3])


# =========================================================
# THE REAL data.json THAT YOUR APP USES
# =========================================================
class TestRealDataFile:
    def test_data_json_is_valid(self):
        data = load_data(os.path.join(HERE, "data.json"))
        assert data["shelters"]
        assert data["roads"]

    def test_every_zone_has_a_road(self):
        data = load_data(os.path.join(HERE, "data.json"))
        used = set()
        for road in data["roads"]:
            used.update((road["start"], road["end"]))
        for zone in data["zone_population"]:
            assert zone in used, zone + " has no road, so nobody could " \
                "leave it"

    def test_every_shelter_has_a_road(self):
        data = load_data(os.path.join(HERE, "data.json"))
        used = set()
        for road in data["roads"]:
            used.update((road["start"], road["end"]))
        for shelter in data["shelters"]:
            assert shelter in used, shelter + " has no road, so nobody " \
                "could reach it"
