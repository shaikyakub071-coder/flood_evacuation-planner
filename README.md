# 🌊 Flood Evacuation Route Planner

A web tool that helps disaster-management authorities find the **fastest safe
evacuation routes** from flood-prone zones to designated shelters, taking
blocked and submerged roads into account. Roads, shelters and hazard zones
are modelled with OOP and have **dynamic states** that authorities can change
while the emergency is happening.

## Features

- **Safest shortest route** between any two places (Dijkstra via `networkx`),
  where road cost = distance + flood penalty.
- **Automatic nearest shelter** that still has room for the group.
- **Backup route** (only shown if it is not a huge detour).
- **Weighted graph view** of each route and an optional flood-coloured road map.
- **Evacuate All**: plans where *every* person in the dangerous zones goes;
  groups are split when a shelter fills up, and people with no safe road or
  space are reported.
- **Admin page** (password protected): set flood level / open-blocked status
  of roads, zone populations, and reset shelters after the emergency.
- **Live updates**: the page checks for changes every 15 seconds and warns
  when the route on screen may be out of date.
- **Map data in `data.json`**, validated at start-up, so a typo is reported
  immediately instead of causing a wrong route.

## How routing works

| Flood level | Penalty added to road distance | Usable? |
|-------------|-------------------------------|---------|
| low         | 0                             | yes     |
| medium      | +10                           | yes     |
| high        | +50                           | yes (avoided if possible) |
| submerged   | -                             | **no** (removed from graph) |
| blocked     | -                             | **no** (removed from graph) |

The route is chosen by the graph in `models.py`. The map uses OSRM only to
draw road shapes between stops; OSRM does not know about floods. The dotted
black line on the map is the exact path the algorithm chose, and a warning
appears if the drawn road differs a lot from the graph distance.

## OOP design (`models.py`)

| Class         | Responsibility |
|---------------|----------------|
| `Road`        | One road; flood level and open/blocked state can change (`block()`, `open()`, `set_flood_level()`). |
| `Shelter`     | Capacity and occu
