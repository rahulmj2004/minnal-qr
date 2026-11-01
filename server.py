"""Minnal-Q web server (FastAPI).

Run:  uvicorn server:app --port 8077      then open http://localhost:8077
"""
from __future__ import annotations

import threading
import time
from functools import lru_cache
from itertools import permutations
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from minnal_q import DEMO_INCIDENTS, SLOTS, Incident, make_scenario, route_label
from minnal_q.city import NODES, build_graph, travel_matrix
from minnal_q.fleet import auto_assign_qubo, solve_assign
from minnal_q.classical import all_routes, brute_force, greedy_nearest, route_cost, time_only
from minnal_q.qaoa import solve_qaoa
from minnal_q.qubo import all_energies, auto_penalty, bits_to_x, decode, encode, to_ising
from minnal_q.runtime import run_big_stack
from minnal_q.scenario import SEVERITY_LABEL, SEVERITY_WEIGHT, evaluate

BASE = "Ambulance Base (Kalamassery)"
WEB = Path(__file__).parent / "web"

app = FastAPI(title="Minnal-Q", description="Severity- and traffic-aware ambulance routing with QAOA")


class PatientIn(BaseModel):
    location: str
    severity: int = Field(ge=1, le=4)


class OptimizeIn(BaseModel):
    slot: str = "Morning peak (9 AM)"
    hospital: str = "Lakeshore Hospital"
    patients: list[PatientIn]
    lam: float = Field(2.0, ge=0, le=10)
    reps: int = Field(2, ge=1, le=2)
    objective: str = "cvar"


@app.get("/api/meta")
def meta():
    return {
        "base": BASE,
        "nodes": [{"name": k, "lat": v[0], "lon": v[1], "kind": v[2]} for k, v in NODES.items()],
        "slots": SLOTS,
        "severity": {s: {"label": SEVERITY_LABEL[s], "weight": SEVERITY_WEIGHT[s]} for s in SEVERITY_LABEL},
        "demo": {str(n): [{"location": l, "severity": s} for l, s in v] for n, v in DEMO_INCIDENTS.items()},
    }


def _path(sc, g, order):
    """Dense lat/lon/time samples along the actual road path of a route."""
    stops = [sc.base] + [sc.incidents[i].location for i in order] + [sc.hospital]
    pts, now = [], 0.0
    for a, b in zip(stops, stops[1:]):
        nodes = sc.paths[(a, b)]
        for u, v in zip(nodes, nodes[1:]):
            mins = g[u][v]["minutes"]
            for k in range(8):
                f = k / 8
                pts.append([NODES[u][0] + f * (NODES[v][0] - NODES[u][0]),
                            NODES[u][1] + f * (NODES[v][1] - NODES[u][1]), round(now + f * mins, 2)])
            now += mins
    pts.append([NODES[sc.hospital][0], NODES[sc.hospital][1], round(now, 2)])
    return pts


def _route(sc, g, order, lam):
    r = evaluate(sc, order)
    return {"order": list(order), "label": route_label(sc, order), "total": r.total_time,
            "arrivals": r.arrivals, "critical": r.critical_arrival, "weighted": r.weighted_arrival,
            "cost": round(route_cost(sc, order, lam), 2), "path": _path(sc, g, order)}


@lru_cache(maxsize=64)
def _optimize(slot, hospital, patients, lam, reps, objective):
    incidents = [Incident(l, s) for l, s in patients]
    sc = make_scenario(BASE, hospital, incidents, slot)
    g = build_graph(slot)
    n = sc.n
    greedy, fastest, exact = greedy_nearest(sc), time_only(sc), brute_force(sc, lam)
    q = auto_penalty(sc, lam)

    r1 = solve_qaoa(q, reps=1, objective=objective, restarts=3)
    res = r1
    if reps == 2:
        warm = [r1.params[0], r1.params[0], r1.params[1], r1.params[1]]
        res = solve_qaoa(q, reps=2, objective=objective, restarts=3, warm=warm)

    best_cost = route_cost(sc, exact.order, lam)
    E = all_energies(q)
    g0 = int(np.argmin(E))
    op, const = to_ising(q)
    costs = {o: route_cost(sc, o, lam) for o in permutations(range(n))}
    ops = res.circuit.decompose().count_ops()

    out = {
        "scenario": {"slot": slot, "hospital": hospital, "base": BASE,
                     "patients": [{"location": i.location, "severity": i.severity, "label": SEVERITY_LABEL[i.severity],
                                   "weight": i.weight} for i in incidents]},
        "routes": {"greedy": _route(sc, g, greedy.order, lam), "fastest": _route(sc, g, fastest.order, lam),
                   "optimum": _route(sc, g, exact.order, lam),
                   "minnal": _route(sc, g, res.best_order, lam) if res.best_order else None},
        "all_routes": [{"order": list(o), "label": route_label(sc, o), "cost": round(c, 2),
                        "total": evaluate(sc, o).total_time, "critical": evaluate(sc, o).critical_arrival}
                       for o, c in all_routes(sc, lam)],
        "quantum": {
            "qubits": q.num_qubits, "reps": res.reps, "objective": res.objective, "shots": res.shots,
            "p_opt": res.p_opt_exact, "p_opt_p1": r1.p_opt_exact, "random_p_opt": res.random_p_opt,
            "feasible": res.feasible_frac, "random_feasible": res.random_feasible, "approx_ratio": res.approx_ratio,
            "depth": res.depth, "two_qubit_gates": res.two_qubit_gates, "seconds": res.seconds,
            "history": [round(h, 5) for h in res.history], "penalty": round(q.penalty, 2), "pauli_terms": len(op),
            "gates": {k: int(v) for k, v in ops.items()},
            "sampled": sorted([{"order": list(o), "shots": c, "cost": round(costs[o], 2),
                                "optimal": abs(costs[o] - best_cost) < 1e-6} for o, c in res.route_counts.items()],
                              key=lambda d: d["cost"]),
            "optimal_bits": encode(exact.order, n).tolist(),
        },
        "checks": [
            {"name": "QUBO energy = route cost for every valid route",
             "ok": all(abs(q.energy(encode(o, n)) - costs[o]) < 1e-6 for o in costs)},
            {"name": "QUBO lowest-energy state is a valid route", "ok": decode(bits_to_x(g0, q.num_qubits), n) is not None},
            {"name": "QUBO lowest energy = brute-force optimum", "ok": bool(abs(E[g0] - best_cost) < 1e-6)},
            {"name": "Ising operator = QUBO on all 2^N bitstrings",
             "ok": bool(np.allclose(np.real(op.to_matrix(sparse=True).diagonal()) + const, E))},
            {"name": "QAOA's best sampled route = exact optimum",
             "ok": bool(res.best_order and abs(costs[res.best_order] - best_cost) < 1e-6)},
        ],
    }
    return out


@app.post("/api/optimize")
def optimize(body: OptimizeIn):
    locs = [p.location for p in body.patients]
    if not 2 <= len(locs) <= 4:
        raise HTTPException(400, "Choose 2 to 4 patients (up to 16 qubits).")
    if len(set(locs)) != len(locs):
        raise HTTPException(400, "Each patient needs a different location.")
    bad = [l for l in locs + [body.hospital] if l not in NODES]
    if bad or body.slot not in SLOTS or body.objective not in ("cvar", "expectation"):
        raise HTTPException(400, f"Unknown input: {bad or body.slot or body.objective}")
    key = (body.slot, body.hospital, tuple((p.location, p.severity) for p in body.patients),
           float(body.lam), body.reps, body.objective)
    return run_big_stack(_optimize, *key)


# ---------------------------------------------------------------------------------------------
# SOS from a phone (prototype). The phone sends GPS + emergency type; the location is snapped to
# the nearest Kochi junction, the patient joins the live dispatch board, and QAOA re-plans.
# ---------------------------------------------------------------------------------------------
EMERGENCY_TYPES = {  # type -> (label, starting severity 1-4)
    "cardiac": ("Chest pain / cardiac", 4), "breathing": ("Breathing difficulty", 4),
    "unconscious": ("Unconscious person", 4), "accident": ("Road accident", 3),
    "injury": ("Fall / injury", 2), "other": ("Other emergency", 2),
}
SOS_SLOT, SOS_HOSPITAL, SOS_REPS = "Morning peak (9 AM)", "Lakeshore Hospital", 1  # p=1: ~3 s at 16 qubits
_sos_lock = threading.Lock()
_sos: dict = {"version": 0, "records": [], "board": None}


def _haversine_km(a, b):
    la1, lo1, la2, lo2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * asin(sqrt(h))


def _nearest_junction(lat, lon):
    best = min((k for k, v in NODES.items() if v[2] == "junction"),
               key=lambda k: _haversine_km((lat, lon), NODES[k][:2]))
    return best, round(_haversine_km((lat, lon), NODES[best][:2]), 2)


class SOSIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy: float | None = None
    kind: str = "other"
    note: str = Field("", max_length=200)
    severity: int | None = Field(None, ge=1, le=4)  # from the on-phone vitals check (JeevaFlow), if done


class TriageIn(BaseModel):
    conscious: bool | None = None
    breathing: bool | None = None


def _board_with(location, severity):
    """Current dispatch board + this patient; at most 4 patients (16 qubits)."""
    board = _sos["board"] or [dict(location=l, severity=s, source="board") for l, s in DEMO_INCIDENTS[3]]
    board = [p for p in board if p["location"] != location]
    board.append(dict(location=location, severity=severity, source="sos"))
    while len(board) > 4:  # drop the least severe non-SOS patient (handed to another ambulance)
        drop = min((p for p in board if p["source"] != "sos"), key=lambda p: p["severity"], default=None)
        if drop is None:
            drop = min(board[:-1], key=lambda p: p["severity"])
        board.remove(drop)
    return board


def _dispatch(rec):
    """Run QAOA for the board containing this SOS and fill the record's ETA fields."""
    board = _board_with(rec["junction"], rec["severity"])
    key = (SOS_SLOT, SOS_HOSPITAL, tuple((p["location"], p["severity"]) for p in board), 2.0, SOS_REPS, "cvar")
    res = run_big_stack(_optimize, *key)
    idx = [p["location"] for p in board].index(rec["junction"])
    minnal, greedy = res["routes"]["minnal"] or res["routes"]["optimum"], res["routes"]["greedy"]
    q = res["quantum"]
    rec.update(
        eta=minnal["arrivals"][idx], eta_greedy=greedy["arrivals"][idx],
        stop=minnal["order"].index(idx) + 1, stops=len(board), route=minnal["label"],
        qubits=q["qubits"], p_opt=q["p_opt"], random_p_opt=q["random_p_opt"], qaoa_seconds=q["seconds"],
        optimal=bool(minnal["cost"] == res["routes"]["optimum"]["cost"]),
        patients=[{"location": p["location"], "severity": p["severity"]} for p in board],
        result=res, status="dispatched",
        quantum=_quantum_view(res, board, idx),
    )
    try:
        fleet = run_big_stack(_fleet, SOS_SLOT, SOS_HOSPITAL, key[2], 2.0)
        rec["fleet"] = _fleet_view(fleet, minnal, idx)
    except Exception as e:  # Q-Fleet is an add-on; single-ambulance dispatch above always stands
        rec["fleet"] = None
        rec.setdefault("log", []).append(f"Q-Fleet unavailable: {e}")
    _sos["board"] = board
    return rec


# ---------------------------------------------------------------------------------------------
# Q-Fleet: two ambulances. Stage 1 QAOA assigns patients to ambulances; stage 2 QAOA orders each one's stops.
# ---------------------------------------------------------------------------------------------
FLEET = [  # (name, base node, map colour)
    ("Ambulance A", BASE, "#F0233B"),
    ("Ambulance B", "Vyttila", "#2563EB"),
]


@lru_cache(maxsize=64)
def _fleet(slot, hospital, patients, lam=2.0):
    incidents = [Incident(l, s) for l, s in patients]
    locs, weights = [i.location for i in incidents], [i.weight for i in incidents]
    bases = [b for _, b, _ in FLEET]
    g = build_graph(slot)
    times, _ = travel_matrix(g, list(dict.fromkeys(bases + locs + [hospital])))
    q = auto_assign_qubo(times, bases, locs, weights)
    ar = solve_assign(q, reps=2)
    assign = ar.assign
    if assign is None:  # no valid sample: fall back to the exhaustive optimum (never happened in tests)
        from minnal_q.fleet import decode_assign
        assign = decode_assign(bits_to_x(int(np.argmin(all_energies(q))), q.num_qubits), q.m, q.n)
    arrivals = [0.0] * len(incidents)
    ambulances, route_qubits = [], 0
    for a, (name, base, color) in enumerate(FLEET):
        mine = [i for i in range(len(incidents)) if assign[i] == a]
        amb = {"name": name, "base": base, "color": color, "patients": mine, "route": None, "qubits": 0}
        if mine:
            sc = make_scenario(base, hospital, [incidents[i] for i in mine], slot)
            if len(mine) >= 2:
                r2 = solve_qaoa(auto_penalty(sc, lam), reps=1)
                order = r2.best_order or brute_force(sc, lam).order
                amb["qubits"] = len(mine) ** 2
                route_qubits += len(mine) ** 2
            else:
                order = (0,)
            route = _route(sc, g, order, lam)
            route["label"] = " → ".join([name] + [incidents[mine[j]].location for j in order] + [hospital])
            for j, i in enumerate(mine):
                arrivals[i] = route["arrivals"][j]
            amb["route"] = route
        ambulances.append(amb)
    top = max(range(len(incidents)), key=lambda i: incidents[i].severity)
    names = [n for n, _, _ in FLEET]
    return {
        "ambulances": ambulances, "assign": list(assign), "arrivals": arrivals,
        "critical": arrivals[top], "weighted": round(sum(w * t for w, t in zip(weights, arrivals)), 2),
        "assign_quantum": {
            "qubits": ar.qubits, "reps": ar.reps, "shots": ar.shots, "p_opt": ar.p_opt, "random_p_opt": ar.random_p_opt,
            "feasible": ar.feasible, "optimal": ar.optimal, "bits": ar.bits, "penalty": round(ar.penalty, 1),
            "seconds": ar.seconds, "m": q.m, "n": q.n, "ambulances": names, "patients": locs,
            "top": [{"label": ", ".join(f"{locs[i]}→{names[a][-1]}" for i, a in enumerate(t)), "shots": c, "optimal": o}
                    for t, c, o in ar.top],
        },
        "route_qubits": route_qubits,
    }


def _fleet_view(fleet, single, you):
    """Per-SOS summary of the Q-Fleet plan versus a single ambulance."""
    amb = fleet["ambulances"][fleet["assign"][you]]
    return dict(fleet, you=you, your_ambulance=amb["name"], your_base=amb["base"], your_color=amb["color"],
                eta=fleet["arrivals"][you], eta_single=single["arrivals"][you],
                critical_single=single["critical"], weighted_single=single["weighted"])


def _quantum_view(res, board, you):
    """What the phone shows of the quantum decision: qubit grid, measured routes, confidence."""
    q, names = res["quantum"], [p["location"] for p in board]
    label = lambda order: " → ".join(names[i] for i in order)
    return {
        "n": len(board), "names": names, "you": you, "bits": [int(b) for b in q["optimal_bits"]],
        "shots": q["shots"], "reps": q["reps"], "p_opt": q["p_opt"], "random_p_opt": q["random_p_opt"],
        "feasible": q["feasible"], "random_feasible": q["random_feasible"],
        "top": [{"label": label(d["order"]), "shots": d["shots"], "optimal": d["optimal"]}
                for d in sorted(q["sampled"], key=lambda d: -d["shots"])[:5]],
        "checks_ok": all(c["ok"] for c in res["checks"]),
    }


def _public(rec):
    return {k: v for k, v in rec.items() if k != "result"}


@app.post("/api/sos")
def sos(body: SOSIn):
    if body.kind not in EMERGENCY_TYPES:
        raise HTTPException(400, f"Unknown emergency type: {body.kind}")
    label, sev = EMERGENCY_TYPES[body.kind]
    vitals_sev = body.severity
    if vitals_sev:
        sev = max(sev, vitals_sev)
    junction, km = _nearest_junction(body.lat, body.lon)
    with _sos_lock:
        rec = dict(id=len(_sos["records"]) + 1, created=time.time(), lat=body.lat, lon=body.lon,
                   accuracy=body.accuracy, kind=body.kind, kind_label=label, note=body.note,
                   severity=sev, severity_label=SEVERITY_LABEL[sev], junction=junction, distance_km=km,
                   outside_area=km > 15, triage={}, log=[f"SOS received: {label} near {junction}"]
                   + ([f"Phone vitals check: severity {SEVERITY_LABEL[vitals_sev]} ({body.note})"] if vitals_sev else []))
        _dispatch(rec)
        rec["log"].append(f"QAOA ({rec['qubits']} qubits) dispatched: ETA {rec['eta']} min, stop {rec['stop']}")
        _sos["records"].append(rec)
        _sos["active_id"] = rec["id"]
        _sos["version"] += 1
        return _public(rec)


@app.post("/api/sos/{sid}/triage")
def sos_triage(sid: int, body: TriageIn):
    with _sos_lock:
        rec = next((r for r in _sos["records"] if r["id"] == sid), None)
        if rec is None:
            raise HTTPException(404, "Unknown SOS")
        rec["triage"].update({k: v for k, v in body.model_dump().items() if v is not None})
        old = rec["severity"]
        new = old
        if rec["triage"].get("breathing") is False or rec["triage"].get("conscious") is False:
            new = 4
        elif rec["triage"].get("conscious") and rec["triage"].get("breathing") and old == 4 and rec["kind"] in ("accident", "injury", "other"):
            new = 3
        rec["previous_eta"] = rec["eta"]
        if new != old:
            rec.update(severity=new, severity_label=SEVERITY_LABEL[new])
            rec["log"].append(f"Triage: severity {SEVERITY_LABEL[old]} -> {SEVERITY_LABEL[new]}, re-running QAOA")
            _dispatch(rec)
            rec["log"].append(f"Re-planned: ETA {rec['previous_eta']} -> {rec['eta']} min, stop {rec['stop']}")
        else:
            rec["log"].append(f"Triage confirmed severity {SEVERITY_LABEL[new]}; route unchanged")
        rec["severity_changed"] = new != old
        _sos["active_id"] = rec["id"]
        _sos["version"] += 1
        return _public(rec)


@app.get("/api/sos/feed")
def sos_feed(since: int = 0):
    with _sos_lock:
        if since >= _sos["version"]:
            return {"version": _sos["version"], "changed": False}
        active = next((r for r in _sos["records"] if r["id"] == _sos.get("active_id")), None)
        return {"version": _sos["version"], "changed": True,
                "records": [_public(r) for r in _sos["records"][-10:]],
                "active": dict(_public(active), result=active["result"]) if active else None}


@app.post("/api/sos/reset")
def sos_reset():
    with _sos_lock:
        _sos.update(records=[], board=None, active_id=None)
        _sos["version"] += 1
    return {"ok": True}


app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/sos")
def sos_page():
    return FileResponse(WEB / "sos.html")


@app.get("/sw.js")
def service_worker():  # served from the root so it can control /sos
    return FileResponse(WEB / "sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(WEB / "manifest.webmanifest", media_type="application/manifest+json")
