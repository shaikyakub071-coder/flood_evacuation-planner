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
- **Shortest vs safest comparison** so users see the trade-off.
- **Travel-time estimates** for every route (flooded roads are slower:
  40 / 25 / 10 km/h for low / medium / high flood).
- **Weighted graph view** of each route and an optional flood-coloured road map.
- **Evacuate All**: plans where *every* person in the dangerous zones goes;
  groups are split when a shelter fills up, and people with no safe road or
  space are reported. Vulnerable people (elderly, disabled, patients) are
  served first.
- **Admin page** (password protected): set flood level / open-blocked status
  of roads, zone populations, and reset shelters after the emergency.
- **Flood history log** of every road change, with time.
- **Live updates**: the page checks for changes every 15 seconds and warns
  when the route on screen may be out of date.
- **English, Telugu and Hindi** on the public pages.
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
| `Road`        | One road; flood level and open/blocked state can change (`block()`, `open()`, `set_flood_level()`). Gives its routing cost. |
| `Shelter`     | Capacity and occupancy; `assign()`, `reset()`, `can_fit()`, `available()`. |
| `HazardZone`  | A flood-prone place. Its risk is the worst flood level on its roads; holds the population and the number of vulnerable people. |
| `RoadNetwork` | The whole graph. Builds it from the current road states, finds safest / shortest / alternative routes, picks the nearest shelter, and plans the evacuation of all zones. |

Because states live on the objects, changing one road (`block()`) changes the
graph and therefore every route computed afterwards.

## Project structure

```
app.py               Flask routes, database access, login, CSRF
models.py            Road, Shelter, HazardZone, RoadNetwork
data_loader.py       Loads and validates data.json
data.json            Places, shelters, populations and roads (edit this)
translations.py      English / Telugu / Hindi text
templates/           index.html, evacuate_all.html, admin.html, login.html
test_models.py       Tests for the OOP model and routing
test_data.py         Tests for data.json validation
test_translations.py Tests for the translations
test_app.py          Tests for the Flask routes (no real database needed)
```

## Setup

You need Python 3.10+ and a PostgreSQL database.

```bash
pip install -r requirements.txt
```

### Environment variables

| Variable         | Required | Meaning |
|------------------|----------|---------|
| `DATABASE_URL`   | yes      | PostgreSQL connection string. |
| `ADMIN_PASSWORD` | yes      | Password for the admin pages. Login is refused if it is not set. |
| `SECRET_KEY`     | yes (production) | Long random text that signs login sessions. A warning is printed if it is missing. |
| `DATA_FILE`      | no       | Path to a different map data file (default: `data.json`). |
| `PORT`           | no       | Port for the development server (default: 5000). |

Example (Linux / macOS):

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/flood"
export ADMIN_PASSWORD="choose-a-strong-password"
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
python app.py
```

Open http://localhost:5000. The tables are created and filled from
`data.json` the first time the app talks to the database.

### Deploying (e.g. Render)

Use `gunicorn app:app` as the start command and set the three environment
variables above in the service settings.

## Using the app

1. **Public page** (`/`): pick a starting place and a destination (or
   "Nearest Safe Shelter"), enter the number of people, and press
   *Find Safe Route*.
2. **Admin** (`/admin`, login required): update a road's flood level or
   open/blocked state, set zone populations, review the flood history, and
   reset everything when the emergency is over. The public page notices the
   change within 15 seconds.
3. **Evacuate All** (`/evacuate-all`): everyone can see the preview plan.
   Only a logged-in admin can *confirm* it, which reserves the shelter places.

### Changing the map

Edit `data.json` (places, shelters, populations, roads) and restart. The file
is checked on start-up and **every** mistake is listed at once. Roads are
added to the database only if their name is new; to change an existing road's
distance, update it in the database too.

## Security

- Admin password is compared in constant time.
- After 5 wrong passwords, login from that address is locked for 5 minutes.
- Every form has a CSRF token; POSTs without a valid token are rejected.
- Session cookies are `HttpOnly` and `SameSite=Lax`; admin sessions expire
  after 8 hours, and the session is renewed at login.
- Reserving shelter places and confirming an evacuation need admin login.
- Shelter booking is a single atomic SQL `UPDATE ... WHERE capacity -
  occupied >= n`, so two people confirming at once cannot overbook a shelter.
- Redirects (`next=`) are only allowed inside this site.

Notes: the login lock-out is kept in memory, so it is per server process.
Serve the site over HTTPS in production.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

No database is needed: `test_app.py` replaces the database functions with
fakes. The tests cover routing, blocked/submerged roads, shelter splitting,
vulnerable-first ordering, data validation, translations, login, CSRF,
admin-only actions, the live-status API and the atomic shelter booking.

## Limitations and ideas

- Zone risk is the worst flood level among its roads, so one flooded side road
  can mark a zone "high" even if it has a safe exit.
- Roads and shelters are changed through `data.json`, not through the admin UI.
- Travel time uses fixed speeds per flood level (`Road.SPEED_KMH`); real
  traffic and road capacity are not modelled.
- Possible next steps: rainfall / river-gauge input,
  SMS alerts to residents, printable evacuation plans, and road capacity.
