from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def test_index_and_static_served():
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_meta():
    m = client.get("/api/meta").json()
    assert len(m["nodes"]) == 15 and len(m["slots"]) == 4 and m["demo"]["3"]


def test_optimize_demo_finds_optimum_and_passes_checks():
    m = client.get("/api/meta").json()
    d = client.post("/api/optimize", json={"patients": m["demo"]["3"], "reps": 1}).json()
    assert d["routes"]["minnal"]["cost"] == d["routes"]["optimum"]["cost"]
    assert d["routes"]["minnal"]["critical"] < d["routes"]["greedy"]["critical"]
    assert all(c["ok"] for c in d["checks"])
    assert d["quantum"]["p_opt"] > d["quantum"]["random_p_opt"]


def test_rejects_duplicate_locations():
    r = client.post("/api/optimize", json={"patients": [{"location": "Kaloor", "severity": 1},
                                                        {"location": "Kaloor", "severity": 4}]})
    assert r.status_code == 400
