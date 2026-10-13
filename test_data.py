"""
test_app.py - tests for the Flask routes in app.py

No real database is needed: the functions that talk to PostgreSQL are
replaced with small fakes.

Run from the project folder with:
    pytest -v
"""

import pytest

import app as app_module
from models import RoadNetwork, Shelter

ADMIN_PASSWORD = "correct horse"


# ---------------------------------------------------------
# Test setup
# ---------------------------------------------------------
def make_network():
    rows = [
        ("Home", "Mid", 1.0, "low", "open"),
        ("Mid", "Shelter A", 1.0, "low", "open"),
        ("Mid", "Shelter B", 1.0, "high", "open"),
    ]
    net = RoadNetwork.from_rows(rows, ("Shelter A", "Shelter B"))
    net.shelters["Shelter A"] = Shelter("Shelter A", 100, 0)
    net.shelters["Shelter B"] = Shelter("Shelter B", 50, 0)
    net.set_populations({"Home": 30, "Mid": 20})
    return net


ROAD_ROWS = [
    ("Home - Mid", "Home", "Mid", 1.0, "low", "open"),
    ("Mid - Shelter A", "Mid", "Shelter A", 1.0, "low", "open"),
]


@pytest.fixture
def client(monkeypatch):
    """A test client with the database replaced by fakes."""
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setattr(app_module, "ensure_db", lambda: None)
    monkeypatch.setattr(app_module, "load_network", make_network)
    monkeypatch.setattr(app_module, "get_road_status", lambda: ROAD_ROWS)
    monkeypatch.setattr(app_module, "get_zone_rows", lambda: [])
    monkeypatch.setattr(app_module, "get_road_history", lambda: [])
    app_module._failed.clear()
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def token(client):
    """Visit a page so the session has a CSRF token, and return it."""
    client.get("/login")
    with client.session_transaction() as sess:
        return sess["csrf_token"]


def log_in(client):
    tok = token(client)
    client.post("/login", data={"password": ADMIN_PASSWORD,
                                "csrf_token": tok})
    return token(client)           # the session is renewed after login


# =========================================================
# PUBLIC PAGES
# =========================================================
class TestPublicPages:
    def test_home_page_loads(self, client):
        assert client.get("/").status_code == 200

    def test_evacuate_all_preview_loads(self, client):
        resp = client.get("/evacuate-all?risk=medium")
        assert resp.status_code == 200
        assert b"Admin login" in resp.data     # preview only for public

    def test_bad_risk_value_falls_back_to_high(self, client):
        assert client.get("/evacuate-all?risk=banana").status_code == 200

    def test_route_search_works(self, client):
        tok = token(client)
        resp = client.post("/", data={
            "source": "Home", "destination": "Shelter A",
            "people": "5", "csrf_token": tok})
        assert resp.status_code == 200
        assert b"Recommended Evacuation Route" in resp.data

    def test_route_shows_estimated_travel_time(self, client):
        tok = token(client)
        resp = client.post("/", data={
            "source": "Home", "destination": "Shelter A",
            "people": "5", "csrf_token": tok})
        # Home-Mid-Shelter A = 2 km of dry road at 40 km/h = 3 minutes
        assert b"Estimated Travel Time: ~3 min" in resp.data

    def test_evacuate_all_shows_travel_time(self, client):
        resp = client.get("/evacuate-all?risk=medium")
        assert "⏱️ ~".encode("utf-8") in resp.data

    def test_same_start_and_destination_is_an_error(self, client):
        tok = token(client)
        resp = client.post("/", data={
            "source": "Home", "destination": "Home",
            "people": "1", "csrf_token": tok})
        assert b"cannot be the same" in resp.data

    def test_confirm_button_hidden_from_public(self, client):
        tok = token(client)
        resp = client.post("/", data={
            "source": "Home", "destination": "Shelter A",
            "people": "5", "csrf_token": tok})
        assert b"/confirm_evacuation" not in resp.data

    def test_confirm_button_shown_to_admin(self, client):
        tok = log_in(client)
        resp = client.post("/", data={
            "source": "Home", "destination": "Shelter A",
            "people": "5", "csrf_token": tok})
        assert b"/confirm_evacuation" in resp.data


# =========================================================
# LANGUAGE
# =========================================================
class TestLanguage:
    def test_language_is_stored_in_session(self, client):
        client.get("/lang/hi?next=/")
        with client.session_transaction() as sess:
            assert sess["lang"] == "hi"

    def test_unknown_language_is_ignored(self, client):
        client.get("/lang/xx")
        with client.session_transaction() as sess:
            assert "lang" not in sess

    def test_redirect_stays_on_this_site(self, client):
        for bad in ("https://evil.example", "//evil.example"):
            resp = client.get("/lang/en", query_string={"next": bad})
            assert resp.headers["Location"] == "/"


# =========================================================
# CSRF
# =========================================================
class TestCsrf:
    def test_post_without_token_is_rejected(self, client):
        resp = client.post("/login", data={"password": ADMIN_PASSWORD})
        assert resp.status_code == 400

    def test_post_with_wrong_token_is_rejected(self, client):
        token(client)
        resp = client.post("/login", data={"password": ADMIN_PASSWORD,
                                           "csrf_token": "wrong"})
        assert resp.status_code == 400

    def test_every_form_carries_a_token(self, client):
        log_in(client)
        for page in ("/", "/login", "/admin", "/evacuate-all"):
            html = client.get(page).data.decode("utf-8")
            assert html.count("<form") == html.count('name="csrf_token"'), \
                page


# =========================================================
# LOGIN
# =========================================================
class TestLogin:
    def test_admin_page_needs_login(self, client):
        resp = client.get("/admin")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_wrong_password(self, client):
        tok = token(client)
        resp = client.post("/login", data={"password": "nope",
                                           "csrf_token": tok})
        assert b"Wrong password" in resp.data
        assert client.get("/admin").status_code == 302

    def test_right_password_opens_admin(self, client):
        log_in(client)
        assert client.get("/admin").status_code == 200

    def test_logout_closes_admin(self, client):
        log_in(client)
        client.get("/logout")
        assert client.get("/admin").status_code == 302

    def test_missing_server_password_is_reported(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_PASSWORD")
        tok = token(client)
        resp = client.post("/login", data={"password": "x",
                                           "csrf_token": tok})
        assert b"not configured" in resp.data

    def test_locked_after_too_many_failures(self, client):
        tok = token(client)
        for _ in range(app_module.MAX_FAILS):
            client.post("/login", data={"password": "nope",
                                        "csrf_token": tok})
        # Even the RIGHT password is refused while locked.
        resp = client.post("/login", data={"password": ADMIN_PASSWORD,
                                           "csrf_token": tok})
        assert b"Too many wrong attempts" in resp.data
        assert client.get("/admin").status_code == 302

    def test_login_only_redirects_inside_site(self, client):
        tok = token(client)
        resp = client.post("/login?next=https://evil.example",
                           data={"password": ADMIN_PASSWORD,
                                 "csrf_token": tok})
        assert resp.headers["Location"].endswith("/admin")


# =========================================================
# ADMIN-ONLY ACTIONS
# =========================================================
class TestAdminActions:
    @pytest.mark.parametrize("url", [
        "/update_road", "/update_population", "/reset_shelters",
        "/confirm_evacuation", "/evacuate-all/confirm"])
    def test_public_cannot_post_admin_routes(self, client, url):
        tok = token(client)
        resp = client.post(url, data={"csrf_token": tok})
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_admin_can_update_a_road(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(app_module, "update_road_state",
                            lambda *a: calls.append(a))
        tok = log_in(client)
        client.post("/update_road", data={
            "road_name": "Home - Mid", "flood_level": "high",
            "status": "blocked", "csrf_token": tok})
        assert calls == [("Home - Mid", "high", "blocked")]

    def test_bad_road_update_shows_error(self, client, monkeypatch):
        def boom(*args):
            raise ValueError("Road not found: X")
        monkeypatch.setattr(app_module, "update_road_state", boom)
        tok = log_in(client)
        resp = client.post("/update_road", data={
            "road_name": "X", "flood_level": "low", "status": "open",
            "csrf_token": tok}, follow_redirects=True)
        assert b"Road not found" in resp.data

    def test_confirm_evacuation_reserves_places(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(app_module, "reserve_shelter_places",
                            lambda name, n: calls.append((name, n)))
        monkeypatch.setitem(app_module.SHELTER_INFO, "Shelter A", 100)
        tok = log_in(client)
        client.post("/confirm_evacuation", data={
            "shelter": "Shelter A", "people": "12", "csrf_token": tok})
        assert calls == [("Shelter A", 12)]

    def test_confirm_evacuation_rejects_unknown_shelter(self, client,
                                                        monkeypatch):
        calls = []
        monkeypatch.setattr(app_module, "reserve_shelter_places",
                            lambda name, n: calls.append((name, n)))
        tok = log_in(client)
        resp = client.post("/confirm_evacuation", data={
            "shelter": "Nowhere", "people": "1", "csrf_token": tok},
            follow_redirects=True)
        assert calls == []
        assert b"Unknown shelter" in resp.data

    def test_confirm_all_saves_the_plan(self, client, monkeypatch):
        saved = []
        monkeypatch.setattr(app_module, "save_evacuation",
                            lambda network, plan: saved.append(plan))
        tok = log_in(client)
        resp = client.post("/evacuate-all/confirm", data={
            "risk": "medium", "csrf_token": tok}, follow_redirects=True)
        assert len(saved) == 1
        assert b"Reserved shelter places" in resp.data

    def test_confirm_all_with_nobody_to_place(self, client, monkeypatch):
        saved = []
        monkeypatch.setattr(app_module, "save_evacuation",
                            lambda network, plan: saved.append(plan))
        monkeypatch.setattr(
            app_module, "load_network",
            lambda: RoadNetwork.from_rows(
                [("A", "S", 1.0, "low", "open")], ("S",)))
        tok = log_in(client)
        resp = client.post("/evacuate-all/confirm", data={
            "risk": "medium", "csrf_token": tok}, follow_redirects=True)
        assert saved == []
        assert b"Nobody could be placed" in resp.data


# =========================================================
# ATOMIC SHELTER RESERVATION (fake database connection)
# =========================================================
class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0

    def execute(self, sql, params=()):
        self.conn.statements.append(" ".join(sql.split()))
        if sql.lstrip().startswith("UPDATE"):
            people, _name, _need = params
            free = self.conn.capacity - self.conn.occupied
            if free >= people:
                self.conn.occupied += people
                self.rowcount = 1
            else:
                self.rowcount = 0

    def fetchone(self):
        if self.conn.missing:
            return None
        return (self.conn.capacity - self.conn.occupied,)

    def close(self):
        pass


class FakeConnection:
    def __init__(self, capacity=10, occupied=0, missing=False):
        self.capacity = capacity
        self.occupied = occupied
        self.missing = missing
        self.statements = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class TestReserveShelterPlaces:
    def use(self, monkeypatch, conn):
        monkeypatch.setattr(app_module, "get_connection", lambda: conn)

    def test_reserves_when_there_is_room(self, monkeypatch):
        conn = FakeConnection(capacity=10, occupied=3)
        self.use(monkeypatch, conn)
        app_module.reserve_shelter_places("S", 7)
        assert conn.occupied == 10
        assert conn.committed and conn.closed

    def test_single_statement_checks_room_itself(self, monkeypatch):
        # The room check must be INSIDE the UPDATE (no read-then-write).
        conn = FakeConnection()
        self.use(monkeypatch, conn)
        app_module.reserve_shelter_places("S", 1)
        update = [s for s in conn.statements if s.startswith("UPDATE")][0]
        assert "capacity - occupied >=" in update

    def test_refuses_when_full(self, monkeypatch):
        conn = FakeConnection(capacity=10, occupied=8)
        self.use(monkeypatch, conn)
        with pytest.raises(ValueError, match="only 2 places left"):
            app_module.reserve_shelter_places("S", 5)
        assert conn.occupied == 8
        assert not conn.committed and conn.closed

    def test_second_booking_cannot_overbook(self, monkeypatch):
        conn = FakeConnection(capacity=10, occupied=0)
        self.use(monkeypatch, conn)
        app_module.reserve_shelter_places("S", 6)
        with pytest.raises(ValueError):
            app_module.reserve_shelter_places("S", 6)
        assert conn.occupied == 6

    def test_unknown_shelter(self, monkeypatch):
        conn = FakeConnection(capacity=10, occupied=10, missing=True)
        self.use(monkeypatch, conn)
        with pytest.raises(ValueError, match="Unknown shelter"):
            app_module.reserve_shelter_places("Nowhere", 1)

    def test_zero_people_is_rejected(self, monkeypatch):
        self.use(monkeypatch, FakeConnection())
        with pytest.raises(ValueError):
            app_module.reserve_shelter_places("S", 0)


# =========================================================
# LIVE STATUS API
# =========================================================
class TestApiStatus:
    def test_returns_a_version(self, client):
        data = client.get("/api/status").get_json()
        assert data["ok"] is True
        assert len(data["version"]) == 32

    def test_not_cached(self, client):
        resp = client.get("/api/status")
        assert resp.headers["Cache-Control"] == "no-store"

    def test_same_data_gives_same_version(self, client):
        a = client.get("/api/status").get_json()["version"]
        b = client.get("/api/status").get_json()["version"]
        assert a == b

    def test_version_changes_when_a_road_changes(self, client, monkeypatch):
        before = client.get("/api/status").get_json()["version"]
        changed = [ROAD_ROWS[0][:4] + ("high", "blocked")] + ROAD_ROWS[1:]
        monkeypatch.setattr(app_module, "get_road_status", lambda: changed)
        after = client.get("/api/status").get_json()["version"]
        assert before != after

    def test_version_changes_when_a_shelter_fills(self, client,
                                                  monkeypatch):
        before = client.get("/api/status").get_json()["version"]

        def fuller():
            net = make_network()
            net.shelters["Shelter A"].occupied = 40
            return net
        monkeypatch.setattr(app_module, "load_network", fuller)
        after = client.get("/api/status").get_json()["version"]
        assert before != after

    def test_database_failure_gives_500(self, client, monkeypatch):
        def boom():
            raise RuntimeError("db down")
        monkeypatch.setattr(app_module, "get_road_status", boom)
        resp = client.get("/api/status")
        assert resp.status_code == 500
        assert resp.get_json()["ok"] is False


# =========================================================
# ROUTE EDGES HELPER
# =========================================================
def test_route_edges_lists_distance_penalty_and_weight():
    net = make_network()
    graph = net.build_graph()
    edges = app_module.route_edges(["Home", "Mid", "Shelter A"], graph)
    assert [e["from"] for e in edges] == ["Home", "Mid"]
    assert edges[0] == {"from": "Home", "to": "Mid", "distance": 1.0,
                        "risk": 0, "weight": 1.0}
