"""Q-Fleet: two-stage quantum dispatch for several ambulances.

Stage 1 (Q-Assign): a QUBO decides which ambulance takes which patient.
    y[a, i] = 1  <=>  ambulance a takes patient i         (qubit k = a * n + i, so m * n qubits)
    cost = A * sum_i (1 - sum_a y[a,i])^2                  each patient gets exactly one ambulance
         + sum_{a,i} w_i * T(base_a, i) * y[a,i]           severity-weighted drive from that ambulance's base
         + sum_{a, i<j} (w_i + w_j)/2 * T(i, j) * y[a,i] y[a,j]
                                                           two patients on one ambulance: one of them must wait
Stage 2 (Q-Route): each ambulance's stops are ordered with the existing Minnal-Q QAOA.

The assignment QUBO is solved with QAOA (qaoa_ansatz + COBYLA on CVaR + Aer SamplerV2) and checked against an
exhaustive search of all 2^(m*n) bitstrings, like the routing stage.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from qiskit import transpile
from qiskit.circuit.library import qaoa_ansatz
from qiskit.quantum_info import Statevector
from qiskit_aer import AerSimulator
from qiskit_aer.primitives import SamplerV2
from scipy.optimize import minimize

from .qaoa import _cvar
from .qubo import QUBO, all_energies, bits_to_x, to_ising


@dataclass
class AssignQUBO(QUBO):
    m: int = 2  # ambulances

    @property
    def num_qubits(self) -> int:
        return self.m * self.n


def build_assign_qubo(times: dict, bases: list, locs: list, weights: list, penalty: float) -> AssignQUBO:
    m, n = len(bases), len(locs)
    N = m * n
    Q = np.zeros((N, N))
    offset = 0.0

    def add(a, b, v):
        if a > b:
            a, b = b, a
        Q[a, b] += v

    k = lambda a, i: a * n + i
    for a in range(m):
        for i in range(n):
            add(k(a, i), k(a, i), weights[i] * times[(bases[a], locs[i])])
            for j in range(i + 1, n):
                add(k(a, i), k(a, j), 0.5 * (weights[i] + weights[j]) * times[(locs[i], locs[j])])
    for i in range(n):  # A (1 - sum_a y_ai)^2 = A (1 - sum_a y_ai + 2 sum_{a<b} y_ai y_bi)
        offset += penalty
        for a in range(m):
            add(k(a, i), k(a, i), -penalty)
            for b in range(a + 1, m):
                add(k(a, i), k(b, i), 2 * penalty)
    return AssignQUBO(n=n, Q=Q, offset=offset, penalty=penalty, lam=0.0, m=m)


def decode_assign(x, m: int, n: int):
    """Bits -> tuple(ambulance index per patient), or None if a patient has zero or two ambulances."""
    out = []
    for i in range(n):
        owners = [a for a in range(m) if x[a * n + i]]
        if len(owners) != 1:
            return None
        out.append(owners[0])
    return tuple(out)


def encode_assign(assign, m: int, n: int) -> np.ndarray:
    x = np.zeros(m * n, dtype=int)
    for i, a in enumerate(assign):
        x[a * n + i] = 1
    return x


def auto_assign_qubo(times, bases, locs, weights) -> AssignQUBO:
    """Raise the penalty until the lowest-energy bitstring is a valid assignment (checked exhaustively)."""
    m, n = len(bases), len(locs)
    A = max(w * times[(b, l)] for b in bases for l, w in zip(locs, weights)) + 1.0
    for _ in range(30):
        q = build_assign_qubo(times, bases, locs, weights, A)
        E = all_energies(q)
        if decode_assign(bits_to_x(int(np.argmin(E)), q.num_qubits), m, n) is not None:
            return q
        A *= 1.5
    return q


@dataclass
class AssignResult:
    assign: tuple | None       # ambulance index per patient (best valid sample)
    optimal: bool              # equals the exhaustive-search ground state
    qubits: int
    reps: int
    shots: int
    p_opt: float               # exact probability of the optimal assignment in the trained state
    random_p_opt: float
    feasible: float            # share of shots that are valid assignments
    bits: list                 # optimal bitstring (qubit order)
    top: list                  # most-measured valid assignments [(assign, shots, optimal)]
    penalty: float
    seconds: float


def solve_assign(q: AssignQUBO, reps: int = 2, shots: int = 4096, restarts: int = 3, alpha: float = 0.2,
                 seed: int = 7, maxiter: int = 150) -> AssignResult:
    t0 = time.time()
    rng = np.random.default_rng(seed)
    m, n, N = q.m, q.n, q.num_qubits
    op, _ = to_ising(q)
    ansatz = qaoa_ansatz(op / float(np.max(np.abs(op.coeffs))), reps=reps)
    params = list(ansatz.parameters)
    betas = [p for p in params if "β" in p.name]
    gammas = [p for p in params if "γ" in p.name]
    flat = transpile(ansatz, basis_gates=["rz", "rx", "h", "cx", "rzz"], optimization_level=1)

    E = all_energies(q)
    En = (E - E.min()) / (E.max() - E.min())
    opt_set = set(np.flatnonzero(np.isclose(E, E.min())).tolist())

    def bind(theta):
        return {b: theta[k] for k, b in enumerate(betas)} | {g: theta[reps + k] for k, g in enumerate(gammas)}

    def f(theta):
        return _cvar(Statevector(flat.assign_parameters(bind(theta))).probabilities(), En, alpha)

    best = None
    for _ in range(restarts):
        x0 = np.concatenate([rng.uniform(0, np.pi / 2, reps), rng.uniform(0, np.pi, reps)])
        r = minimize(f, x0, method="COBYLA", options={"maxiter": maxiter, "rhobeg": 0.4})
        if best is None or r.fun < best.fun:
            best = r
    p_exact = Statevector(flat.assign_parameters(bind(best.x))).probabilities()

    meas = ansatz.assign_parameters(bind(best.x))
    meas.measure_all()
    sim = AerSimulator(seed_simulator=seed, max_parallel_threads=1)
    tc = transpile(meas, sim, optimization_level=1, seed_transpiler=seed)
    sampler = SamplerV2(seed=seed, options={"backend_options": {"max_parallel_threads": 1}})
    counts = sampler.run([tc], shots=shots).result()[0].data.meas.get_counts()

    tally, feas, best_assign, best_E = {}, 0, None, None
    for bs, c in counts.items():
        b = int(bs, 2)
        a = decode_assign(bits_to_x(b, N), m, n)
        if a is None:
            continue
        feas += c
        tally[a] = tally.get(a, 0) + c
        if best_E is None or E[b] < best_E:
            best_assign, best_E = a, float(E[b])
    g0 = int(np.argmin(E))
    opt_assign = decode_assign(bits_to_x(g0, N), m, n)
    top = sorted(tally.items(), key=lambda kv: -kv[1])[:5]
    return AssignResult(
        assign=best_assign, optimal=bool(best_assign is not None and abs(best_E - E.min()) < 1e-6), qubits=N, reps=reps,
        shots=shots, p_opt=float(sum(p_exact[i] for i in opt_set)), random_p_opt=len(opt_set) / 2 ** N,
        feasible=feas / shots, bits=encode_assign(opt_assign, m, n).tolist() if opt_assign else [],
        top=[(a, int(c), bool(a == opt_assign)) for a, c in top], penalty=q.penalty, seconds=round(time.time() - t0, 2),
    )
