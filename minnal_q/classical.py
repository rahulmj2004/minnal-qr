"""Classical baselines: exact brute force, nearest-first greedy, time-only optimum."""
from __future__ import annotations

from itertools import permutations

from .scenario import Scenario, evaluate


def route_cost(sc: Scenario, order, lam: float) -> float:
    """The same objective the QUBO encodes: travel time + lam * sum w_i * position_i."""
    r = evaluate(sc, order)
    pos_pen = sum(sc.incidents[i].weight * p for p, i in enumerate(order))
    return r.total_time + lam * pos_pen


def brute_force(sc: Scenario, lam: float):
    """Exact optimum of the Minnal-Q objective over all n! visiting orders."""
    best = min(permutations(range(sc.n)), key=lambda o: route_cost(sc, o, lam))
    return evaluate(sc, best)


def all_routes(sc: Scenario, lam: float):
    return sorted(((o, route_cost(sc, o, lam)) for o in permutations(range(sc.n))), key=lambda x: x[1])


def greedy_nearest(sc: Scenario):
    """What dispatchers often do: always drive to the nearest unvisited patient."""
    left, prev, order = set(range(sc.n)), sc.base, []
    while left:
        nxt = min(left, key=lambda i: sc.times[(prev, sc.incidents[i].location)])
        order.append(nxt)
        left.remove(nxt)
        prev = sc.incidents[nxt].location
    return evaluate(sc, order)


def time_only(sc: Scenario):
    """Fastest total route, ignoring severity (lam = 0)."""
    return brute_force(sc, 0.0)
