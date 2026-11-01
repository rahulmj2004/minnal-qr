"""Minnal-Q web server (FastAPI).

Run:  uvicorn server:app --port 8077      then open http://localhost:8077
"""
from __future__ import annotations

from functools import lru_cache
from itertools import permutations
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from minnal_q import DEMO_INCIDENTS, SLOTS, Incident, make_scenario, route_label
from minnal_q.city import NODES, build_graph
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


app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")
