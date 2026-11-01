from fastapi.testclient import TestClient

from server import app

client = TestClient(app)
KALOOR = (9.9972, 76.2992)


def setup_function():
    client.post("/api/sos/reset")


def test_phone_app_files_served():
    assert client.get("/sos").status_code == 200
    assert client.get("/static/sos.js").status_code == 200
    assert client.get("/manifest.webmanifest").json()["start_url"] == "/sos"
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and sw.headers["service-worker-allowed"] == "/"
    assert client.get("/static/icons/icon-512.png").status_code == 200


def test_sos_snaps_to_junction_and_dispatches_with_qaoa():
    r = client.post("/api/sos", json={"lat": KALOOR[0], "lon": KALOOR[1], "kind": "cardiac"}).json()
    assert r["junction"] == "Kaloor" and r["severity"] == 4 and not r["outside_area"]
    assert r["qubits"] == 16 and r["stops"] == 4 and r["optimal"]
    assert 1 <= r["stop"] <= 2      # board also has a critical patient (Kakkanad); both go first
    assert r["eta"] > 0 and "result" not in r
    feed = client.get("/api/sos/feed").json()
    assert feed["changed"] and feed["active"]["id"] == r["id"] and feed["active"]["result"]["routes"]["minnal"]


def test_triage_raises_severity_and_replans():
    r = client.post("/api/sos", json={"lat": KALOOR[0], "lon": KALOOR[1], "kind": "injury"}).json()
    assert r["severity"] == 2
    t = client.post(f"/api/sos/{r['id']}/triage", json={"conscious": False, "breathing": True}).json()
    assert t["severity"] == 4 and t["severity_changed"] and t["eta"] <= r["eta"]


def test_far_away_gps_is_flagged_and_bad_kind_rejected():
    r = client.post("/api/sos", json={"lat": 12.97, "lon": 77.59, "kind": "accident"}).json()  # Bengaluru
    assert r["outside_area"] and r["junction"]
    assert client.post("/api/sos", json={"lat": 10, "lon": 76.3, "kind": "alien"}).status_code == 400


def test_feed_unchanged_when_up_to_date():
    v = client.get("/api/sos/feed").json()["version"]
    assert client.get(f"/api/sos/feed?since={v}").json()["changed"] is False
