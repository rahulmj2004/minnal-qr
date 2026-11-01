"""Measure Minnal-Q on the demo scenarios. Writes results/benchmark.csv.

Run:  python run_experiments.py
"""
import csv
import os

from minnal_q import SLOTS, demo_scenario, route_label
from minnal_q.classical import brute_force, greedy_nearest, route_cost, time_only
from minnal_q.qaoa import solve_qaoa
from minnal_q.qubo import auto_penalty

LAM = 2.0
os.makedirs("results", exist_ok=True)
rows = []
for n in (3, 4):
    for slot in SLOTS:
        sc = demo_scenario(slot, n)
        g, t, m = greedy_nearest(sc), time_only(sc), brute_force(sc, LAM)
        q = auto_penalty(sc, LAM)
        warm = None
        for reps in (1, 2):
            r = solve_qaoa(q, reps=reps, objective="cvar", restarts=3, warm=warm)
            if reps == 1:  # warm-start p=2 from the p=1 angles
                warm = [r.params[0], r.params[0], r.params[1], r.params[1]]
            found = r.best_order is not None and abs(route_cost(sc, r.best_order, LAM) - route_cost(sc, m.order, LAM)) < 1e-6
            rows.append(dict(
                patients=n, qubits=n * n, slot=slot, p=reps,
                greedy_route=route_label(sc, g.order), greedy_total=g.total_time, greedy_critical=g.critical_arrival,
                time_only_total=t.total_time, time_only_critical=t.critical_arrival,
                minnal_route=route_label(sc, m.order), minnal_total=m.total_time, minnal_critical=m.critical_arrival,
                qaoa_found_optimum=found, qaoa_p_opt=round(r.p_opt_exact, 4), random_p_opt=round(r.random_p_opt, 5),
                amplification=round(r.p_opt_exact / r.random_p_opt, 1), feasible_frac=round(r.feasible_frac, 3),
                random_feasible=round(r.random_feasible, 4), approx_ratio=round(r.approx_ratio, 3),
                depth=r.depth, two_qubit_gates=r.two_qubit_gates, seconds=r.seconds))
            print(f"n={n} {slot:22s} p={reps}  found={found}  P(opt)={r.p_opt_exact:.4f} "
                  f"(x{r.p_opt_exact / r.random_p_opt:.0f} vs random)  valid={r.feasible_frac:.2f}  {r.seconds}s")

with open("results/benchmark.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows)
print("wrote results/benchmark.csv")
