"""QAOA solver (Qiskit 2.x): qaoa_ansatz + COBYLA training + Aer SamplerV2 sampling."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from math import factorial

import numpy as np
from qiskit import transpile
from qiskit.circuit.library import qaoa_ansatz
from qiskit.quantum_info import Statevector
from qiskit_aer import AerSimulator
from qiskit_aer.primitives import SamplerV2
from scipy.optimize import minimize

from .qubo import QUBO, all_energies, bits_to_x, decode, to_ising


@dataclass
class QAOAResult:
    reps: int
    objective: str
    best_order: tuple | None          # lowest-cost valid route seen in the samples
    best_cost: float | None
    top_order: tuple | None           # most frequently sampled valid route
    counts: dict                      # bitstring -> shots
    route_counts: dict                # order -> shots (valid only)
    shots: int
    feasible_frac: float              # share of shots that are valid routes
    p_opt_shots: float                # share of shots equal to the exact optimum
    p_opt_exact: float                # exact probability of an optimal route in the trained state
    approx_ratio: float               # E_opt / <E> over valid samples (energies shifted >= 0)
    random_p_opt: float               # (#optimal routes) / 2^N  (uniform random guessing)
    random_feasible: float            # n! / 2^N
    params: list
    history: list = field(default_factory=list)
    depth: int = 0
    two_qubit_gates: int = 0
    seconds: float = 0.0
    circuit: object = None


def _cvar(probs: np.ndarray, energies: np.ndarray, alpha: float) -> float:
    order = np.argsort(energies)
    p, e = probs[order], energies[order]
    cum = np.cumsum(p)
    k = np.searchsorted(cum, alpha) + 1
    w = p[:k].copy()
    w[-1] -= cum[k - 1] - alpha if cum[k - 1] > alpha else 0
    return float(w @ e[:k] / alpha)


def solve_qaoa(q: QUBO, reps: int = 1, restarts: int = 3, shots: int = 4096,
               objective: str = "cvar", alpha: float = 0.2, seed: int = 7, warm: list | None = None,
               maxiter: int = 150) -> QAOAResult:
    t0 = time.time()
    rng = np.random.default_rng(seed)
    op, _ = to_ising(q)
    scale = float(np.max(np.abs(op.coeffs)))
    cost_op = op / scale                       # normalise so angles live in a small range
    ansatz = qaoa_ansatz(cost_op, reps=reps)
    params = list(ansatz.parameters)
    betas = [p for p in params if "β" in p.name]
    gammas = [p for p in params if "γ" in p.name]
    flat = transpile(ansatz, basis_gates=["rz", "rx", "h", "cx", "rzz"], optimization_level=1)

    E = all_energies(q)                        # exact energy of every bitstring
    En = (E - E.min()) / (E.max() - E.min())   # normalised for the objective
    opt_set = set(np.flatnonzero(np.isclose(E, E.min())).tolist())  # all optimal routes (ties allowed)

    def probs_for(theta):
        bind = {b: theta[k] for k, b in enumerate(betas)} | {g: theta[reps + k] for k, g in enumerate(gammas)}
        return Statevector(flat.assign_parameters(bind)).probabilities()

    history: list[float] = []

    def f(theta):
        pr = probs_for(theta)
        val = _cvar(pr, En, alpha) if objective == "cvar" else float(pr @ En)
        history.append(val)
        return val

    starts = []
    if warm is not None:
        starts.append(np.array(warm, dtype=float))
    while len(starts) < restarts:
        starts.append(np.concatenate([rng.uniform(0, np.pi / 2, reps), rng.uniform(0, np.pi, reps)]))
    best = None
    for x0 in starts:
        r = minimize(f, x0, method="COBYLA", options={"maxiter": maxiter, "rhobeg": 0.4})
        if best is None or r.fun < best.fun:
            best = r
    theta = best.x
    p_exact = probs_for(theta)

    # final sampling on the Aer simulator
    bind = {b: theta[k] for k, b in enumerate(betas)} | {g: theta[reps + k] for k, g in enumerate(gammas)}
    meas = ansatz.assign_parameters(bind)
    meas.measure_all()
    sim = AerSimulator(seed_simulator=seed, max_parallel_threads=1)  # thread-safe inside the web app
    tc = transpile(meas, sim, optimization_level=1, seed_transpiler=seed)
    sampler = SamplerV2(seed=seed, options={"backend_options": {"max_parallel_threads": 1}})
    counts = sampler.run([tc], shots=shots).result()[0].data.meas.get_counts()

    N, n = q.num_qubits, q.n
    route_counts: dict = {}
    feas = opt_hits = 0
    best_order, best_cost, valid_E, valid_w = None, None, [], []
    for bs, c in counts.items():
        b = int(bs, 2)
        order = decode(bits_to_x(b, N), n)
        if b in opt_set:
            opt_hits += c
        if order is None:
            continue
        feas += c
        route_counts[order] = route_counts.get(order, 0) + c
        valid_E.append(E[b]); valid_w.append(c)
        if best_cost is None or E[b] < best_cost:
            best_order, best_cost = order, float(E[b])
    top_order = max(route_counts, key=route_counts.get) if route_counts else None
    approx = float(E.min() / np.average(valid_E, weights=valid_w)) if valid_E else 0.0

    ops = flat.count_ops()
    return QAOAResult(
        reps=reps, objective=objective, best_order=best_order, best_cost=best_cost, top_order=top_order,
        counts=counts, route_counts=route_counts, shots=shots, feasible_frac=feas / shots,
        p_opt_shots=opt_hits / shots, p_opt_exact=float(sum(p_exact[i] for i in opt_set)), approx_ratio=approx,
        random_p_opt=len(opt_set) / 2 ** N, random_feasible=factorial(n) / 2 ** N, params=list(map(float, theta)),
        history=history, depth=flat.depth(), two_qubit_gates=int(ops.get("cx", 0) + ops.get("rzz", 0)),
        seconds=round(time.time() - t0, 2), circuit=ansatz,
    )
