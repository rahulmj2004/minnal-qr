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


def test_vitals_severity_raises_sos_severity():
    """A stroke sign found by the on-phone vitals check makes an 'injury' SOS critical."""
    from fastapi.testclient import TestClient
    from server import app
    c = TestClient(app)
    c.post("/api/sos/reset")
    r = c.post("/api/sos", json={"lat": 10.0159, "lon": 76.3419, "kind": "injury", "severity": 4,
                                 "note": "vitals: Stroke signs 1/3"}).json()
    assert r["severity"] == 4 and r["severity_label"] == "Critical"
    assert any("vitals" in line for line in r["log"])
    low = c.post("/api/sos", json={"lat": 10.0159, "lon": 76.3419, "kind": "cardiac", "severity": 1}).json()
    assert low["severity"] == 4  # vitals never lower the emergency type's severity
    assert c.post("/api/sos", json={"lat": 10.0, "lon": 76.3, "severity": 9}).status_code == 422
    c.post("/api/sos/reset")


def test_q_fleet_two_ambulances():
    """Q-Fleet: stage-1 QAOA assigns patients to 2 ambulances (verified optimal); never slower than one ambulance."""
    from fastapi.testclient import TestClient
    from server import app
    c = TestClient(app)
    c.post("/api/sos/reset")
    c.post("/api/sos", json={"lat": 10.0159, "lon": 76.3419, "kind": "cardiac"})
    r = c.post("/api/sos", json={"lat": 9.9970, "lon": 76.2990, "kind": "accident"}).json()
    f = r["fleet"]
    aq = f["assign_quantum"]
    assert aq["qubits"] == 2 * len(aq["patients"]) and aq["optimal"]
    assert aq["p_opt"] > aq["random_p_opt"]                      # QAOA concentrates on the optimum
    assert sorted(i for a in f["ambulances"] for i in a["patients"]) == list(range(len(aq["patients"])))
    assert f["eta"] <= f["eta_single"] and f["weighted"] < f["weighted_single"]
    assert len(aq["bits"]) == aq["qubits"] and sum(aq["bits"]) == len(aq["patients"])
    assert r["quantum"]["bits"] and r["quantum"]["shots"] == 4096
    c.post("/api/sos/reset")


def test_assign_qubo_ground_state_is_best_assignment():
    """The assignment QUBO's lowest energy equals the best assignment found by checking all of them."""
    from itertools import product
    import numpy as np
    from minnal_q import make_scenario, Incident
    from minnal_q.fleet import auto_assign_qubo, encode_assign
    from minnal_q.qubo import all_energies
    pts = [("Edappally", 1), ("Ernakulam North", 2), ("Kakkanad", 4)]
    sc = make_scenario("Ambulance Base (Kalamassery)", "Lakeshore Hospital", [Incident(l, s) for l, s in pts],
                       "Morning peak (9 AM)")
    from minnal_q.city import build_graph, travel_matrix
    bases = ["Ambulance Base (Kalamassery)", "Vyttila"]
    locs = [l for l, _ in pts]
    times, _ = travel_matrix(build_graph("Morning peak (9 AM)"), bases + locs + ["Lakeshore Hospital"])
    q = auto_assign_qubo(times, bases, locs, [i.weight for i in sc.incidents])
    E = all_energies(q)
    best = min(q.energy(encode_assign(a, 2, 3)) for a in product(range(2), repeat=3))
    assert np.isclose(E.min(), best)
