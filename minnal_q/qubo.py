"""QUBO formulation of severity- and traffic-aware stop ordering, and conversion to Ising.

Variable x[i,p] = 1 if incident i is visited at position p.  Qubit index k = i*n + p.

H(x) = A * sum_i (1 - sum_p x[i,p])^2 + A * sum_p (1 - sum_i x[i,p])^2      (valid permutation)
     + sum_i T[S,i] x[i,0] + sum_{i!=j} sum_p T[i,j] x[i,p] x[j,p+1]
     + sum_i T[i,H] x[i,n-1]                                                (traffic-adjusted time)
     + lam * sum_i sum_p w_i * p * x[i,p]                                   (critical patients earlier)
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations

import numpy as np
from qiskit.quantum_info import SparsePauliOp

from .scenario import Scenario


@dataclass
class QUBO:
    n: int                 # incidents
    Q: np.ndarray          # upper-triangular (diagonal = linear terms)
    offset: float
    penalty: float
    lam: float

    @property
    def num_qubits(self) -> int:
        return self.n * self.n

    def energy(self, x) -> float:
        x = np.asarray(x, dtype=float)
        return float(self.offset + x @ self.Q @ x)


def idx(n: int, i: int, p: int) -> int:
    return i * n + p


def build_qubo(sc: Scenario, lam: float, penalty: float) -> QUBO:
    n, N = sc.n, sc.n * sc.n
    Q = np.zeros((N, N))
    offset = 0.0
    loc = [inc.location for inc in sc.incidents]

    def add(a, b, v):
        a, b = min(a, b), max(a, b)
        Q[a, b] += v

    # constraints: (1 - sum x)^2 = 1 - sum x + 2 sum_{a<b} x_a x_b
    groups = [[idx(n, i, p) for p in range(n)] for i in range(n)] + \
             [[idx(n, i, p) for i in range(n)] for p in range(n)]
    for g in groups:
        offset += penalty
        for a in g:
            add(a, a, -penalty)
        for u in range(len(g)):
            for v in range(u + 1, len(g)):
                add(g[u], g[v], 2 * penalty)

    # travel time
    for i in range(n):
        add(idx(n, i, 0), idx(n, i, 0), sc.times[(sc.base, loc[i])])
        add(idx(n, i, n - 1), idx(n, i, n - 1), sc.times[(loc[i], sc.hospital)])
        for j in range(n):
            if i != j:
                for p in range(n - 1):
                    add(idx(n, i, p), idx(n, j, p + 1), sc.times[(loc[i], loc[j])])

    # severity: push high-weight patients to early positions
    for i, inc in enumerate(sc.incidents):
        for p in range(n):
            add(idx(n, i, p), idx(n, i, p), lam * inc.weight * p)

    return QUBO(n, Q, offset, penalty, lam)


def all_energies(q: QUBO) -> np.ndarray:
    """Energy of every bitstring; index b has x_k = (b >> k) & 1 (Qiskit qubit order)."""
    N = q.num_qubits
    b = np.arange(2 ** N)
    X = ((b[:, None] >> np.arange(N)) & 1).astype(float)
    return q.offset + np.einsum("bi,ij,bj->b", X, q.Q, X)


def bits_to_x(index: int, N: int) -> np.ndarray:
    return np.array([(index >> k) & 1 for k in range(N)])


def decode(x, n: int):
    """Return visiting order if x is a valid permutation matrix, else None."""
    M = np.asarray(x).reshape(n, n)  # rows = incident, cols = position
    if not (M.sum(0) == 1).all() or not (M.sum(1) == 1).all():
        return None
    return tuple(int(np.argmax(M[:, p])) for p in range(n))


def encode(order, n: int) -> np.ndarray:
    x = np.zeros(n * n, dtype=int)
    for p, i in enumerate(order):
        x[idx(n, i, p)] = 1
    return x


def to_ising(q: QUBO) -> tuple[SparsePauliOp, float]:
    """x_k = (1 - Z_k)/2  ->  H = const + sum h_k Z_k + sum J_kl Z_k Z_l.

    Returns the Pauli operator (without identity) and the constant offset.
    """
    N = q.num_qubits
    const = q.offset
    h = np.zeros(N)
    terms = []
    for a in range(N):
        c = q.Q[a, a]
        const += c / 2
        h[a] -= c / 2
        for b in range(a + 1, N):
            c = q.Q[a, b]
            if c == 0:
                continue
            const += c / 4
            h[a] -= c / 4
            h[b] -= c / 4
            terms.append(("ZZ", [a, b], c / 4))
    terms += [("Z", [k], h[k]) for k in range(N) if h[k] != 0]
    return SparsePauliOp.from_sparse_list(terms, num_qubits=N).simplify(), const


def auto_penalty(sc: Scenario, lam: float, start: float | None = None, max_tries: int = 12) -> QUBO:
    """Smallest penalty (doubling from `start`) whose QUBO ground state is the exact brute-force optimum.

    Exhaustive check over all 2^(n^2) bitstrings (fine for n <= 4).
    """
    from .classical import route_cost
    best = min(route_cost(sc, o, lam) for o in permutations(range(sc.n)))
    A = start or max(sc.times.values())
    for _ in range(max_tries):
        q = build_qubo(sc, lam, A)
        E = all_energies(q)
        g = int(np.argmin(E))
        order = decode(bits_to_x(g, q.num_qubits), sc.n)
        if order is not None and abs(E[g] - best) < 1e-6:
            return q
        A *= 1.5
    raise RuntimeError("Could not find a valid penalty")
