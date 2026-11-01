from itertools import permutations

import numpy as np
import pytest

from minnal_q import SLOTS, demo_scenario
from minnal_q.classical import brute_force, greedy_nearest, route_cost
from minnal_q.qubo import all_energies, auto_penalty, bits_to_x, decode, encode, to_ising


def index_of(order, n):
    return int(sum(int(b) << k for k, b in enumerate(encode(order, n))))


@pytest.mark.parametrize("n", [3, 4])
def test_encode_decode_roundtrip(n):
    for order in permutations(range(n)):
        assert decode(encode(order, n), n) == order


def test_invalid_bitstring_is_rejected():
    assert decode(np.zeros(9, dtype=int), 3) is None
    assert decode(np.ones(9, dtype=int), 3) is None


@pytest.mark.parametrize("n", [3, 4])
@pytest.mark.parametrize("lam", [0.0, 2.0])
def test_qubo_energy_equals_route_cost_for_every_valid_route(n, lam):
    sc = demo_scenario(n=n)
    q = auto_penalty(sc, lam)
    for order in permutations(range(n)):
        assert q.energy(encode(order, n)) == pytest.approx(route_cost(sc, order, lam))


@pytest.mark.parametrize("n", [3, 4])
@pytest.mark.parametrize("slot", SLOTS)
def test_qubo_ground_state_is_brute_force_optimum(n, slot):
    sc = demo_scenario(slot, n)
    q = auto_penalty(sc, 2.0)
    E = all_energies(q)
    g = int(np.argmin(E))
    order = decode(bits_to_x(g, q.num_qubits), n)
    assert order is not None  # ground state is a valid route
    assert E[g] == pytest.approx(route_cost(sc, brute_force(sc, 2.0).order, 2.0))  # ties allowed


def test_ising_matches_qubo_on_every_bitstring():
    sc = demo_scenario(n=3)
    q = auto_penalty(sc, 2.0)
    op, const = to_ising(q)
    diag = np.real(op.to_matrix(sparse=True).diagonal()) + const
    assert np.allclose(diag, all_energies(q))


def test_demo_shows_greedy_failure():
    sc = demo_scenario(n=3)
    g, m = greedy_nearest(sc), brute_force(sc, 2.0)
    assert m.critical_arrival < g.critical_arrival


def test_qaoa_beats_random_guessing():
    from minnal_q.qaoa import solve_qaoa
    sc = demo_scenario(n=3)
    q = auto_penalty(sc, 2.0)
    opt = brute_force(sc, 2.0).order
    r = solve_qaoa(q, reps=1, restarts=2, shots=2048)
    assert r.best_order == opt
    assert r.p_opt_exact > 5 * r.random_p_opt
