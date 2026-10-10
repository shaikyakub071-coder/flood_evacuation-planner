"""
data_loader.py - load and CHECK the map data stored in data.json.

data.json holds everything that used to be hardcoded in app.py:
    locations        place name -> [latitude, longitude]
    shelters         shelter name -> capacity (people)
    zone_population  zone name -> people living there
    roads            list of roads (name, start, end, distance_km,
                     flood_level, status)

Every value is checked, and ALL mistakes are reported together, so a
typo in the file is found at start-up instead of causing a wrong
evacuation route later.
"""

import json

from models import Road


class DataError(ValueError):
    """data.json contains a mistake."""


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_whole(value):
    return isinstance(value, int) and not isinstance(value, bool)


def load_data(path):
    """Read data.json from `path`, check it, and return clean data."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        raise DataError(f"Data file not found: {path}")
    except json.JSONDecodeError as e:
        raise DataError(f"{path} is not valid JSON: {e}")
    return validate_data(raw)


def validate_data(raw):
    """Check the loaded JSON. Returns clean data or raises DataError
    listing every problem found."""
    if not isinstance(raw, dict):
        raise DataError("data.json must contain a JSON object { ... }")

    problems = []

    # ---- locations ------------------------------------------------------
    locations = {}
    raw_locations = raw.get("locations")
    if not isinstance(raw_locations, dict) or not raw_locations:
        problems.append('"locations" must be a non-empty object')
    else:
        for name, coords in raw_locations.items():
            ok = (isinstance(coords, list) and len(coords) == 2
                  and all(_is_number(c) for c in coords))
            if not ok:
                problems.append(
                    f'location "{name}": must be [latitude, longitude]')
                continue
            lat, lon = float(coords[0]), float(coords[1])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                problems.append(
                    f'location "{name}": latitude must be -90..90 and '
                    "longitude -180..180")
                continue
            locations[name] = [lat, lon]

    # ---- shelters -------------------------------------------------------
    shelters = {}
    raw_shelters = raw.get("shelters")
    if not isinstance(raw_shelters, dict) or not raw_shelters:
        problems.append('"shelters" must be a non-empty object')
    else:
        for name, capacity in raw_shelters.items():
            if name not in raw_locations_names(raw):
                problems.append(
                    f'shelter "{name}" is not listed in "locations"')
            elif not _is_whole(capacity) or capacity <= 0:
                problems.append(
                    f'shelter "{name}": capacity must be a whole number '
                    "above 0")
            else:
                shelters[name] = capacity

    # ---- zone populations -----------------------------------------------
    zone_population = {}
    raw_zones = raw.get("zone_population", {})
    if not isinstance(raw_zones, dict):
        problems.append('"zone_population" must be an object')
    else:
        for name, people in raw_zones.items():
            if name not in raw_locations_names(raw):
                problems.append(
                    f'zone "{name}" is not listed in "locations"')
            elif name in (raw_shelters or {}):
                problems.append(
                    f'zone "{name}" is a shelter; shelters are not '
                    "evacuated")
            elif not _is_whole(people) or people < 0:
                problems.append(
                    f'zone "{name}": population must be a whole number '
                    "0 or more")
            else:
                zone_population[name] = people

    # ---- roads ----------------------------------------------------------
    roads = []
    raw_roads = raw.get("roads")
    seen_names = set()
    if not isinstance(raw_roads, list) or not raw_roads:
        problems.append('"roads" must be a non-empty list')
    else:
        for i, item in enumerate(raw_roads, start=1):
            label = f"road #{i}"
            if not isinstance(item, dict):
                problems.append(f"{label}: must be an object")
                continue
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                label = f'road "{name}"'
            else:
                problems.append(f"{label}: needs a text \"name\"")
                continue

            before = len(problems)
            if name in seen_names:
                problems.append(f"{label}: name is used twice")
            seen_names.add(name)

            start, end = item.get("start"), item.get("end")
            for end_name, value in (("start", start), ("end", end)):
                if value not in raw_locations_names(raw):
                    problems.append(
                        f'{label}: "{end_name}" is "{value}", which is '
                        'not in "locations"')
            if start == end:
                problems.append(f"{label}: start and end are the same")

            distance = item.get("distance_km")
            if not _is_number(distance) or distance <= 0:
                problems.append(
                    f'{label}: "distance_km" must be a number above 0')

            flood = str(item.get("flood_level", "low")).strip().lower()
            if flood not in Road.FLOOD_PENALTY:
                problems.append(
                    f'{label}: flood_level "{item.get("flood_level")}" '
                    "must be low, medium, high or submerged")

            status = str(item.get("status", "open")).strip().lower()
            if status not in Road.VALID_STATUS:
                problems.append(
                    f'{label}: status "{item.get("status")}" must be '
                    "open or blocked")

            if len(problems) == before:
                roads.append({
                    "name": name.strip(),
                    "start": start,
                    "end": end,
                    "distance_km": float(distance),
                    "flood_level": flood,
                    "status": status,
                })

    if problems:
        raise DataError(
            f"data.json has {len(problems)} problem(s):\n - "
            + "\n - ".join(problems))

    return {
        "locations": locations,
        "shelters": shelters,
        "zone_population": zone_population,
        "roads": roads,
    }


def raw_locations_names(raw):
    """Names in raw["locations"], or an empty set if it is malformed."""
    locations = raw.get("locations")
    return set(locations) if isinstance(locations, dict) else set()
