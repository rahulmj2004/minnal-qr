"""Optional: run the trained 9-qubit Minnal-Q QAOA circuit on real IBM quantum hardware.

Prerequisite (once):  python save_key.py
Run:                  python run_ibm.py
Writes results/ibm_run.json (job ID, backend, measured route quality), shown in the app's Evidence tab.
"""
import json
import os
from datetime import datetime, timezone

from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2

from minnal_q import demo_scenario, route_label
from minnal_q.classical import brute_force, route_cost
from minnal_q.qaoa import solve_qaoa
from minnal_q.qubo import all_energies, auto_penalty, bits_to_x, decode

LAM, SHOTS = 2.0, 4096
sc = demo_scenario(n=3)
q = auto_penalty(sc, LAM)
best = route_cost(sc, brute_force(sc, LAM).order, LAM)

# 1) train angles on the simulator (classical-quantum loop), p = 1 keeps the hardware circuit shallow
sim = solve_qaoa(q, reps=1, objective="cvar", restarts=3)
circ = sim.circuit.assign_parameters(sim.params)  # parameter order: β..., γ... (same as training)
circ.measure_all()

# 2) run on the least busy real backend
service = QiskitRuntimeService()
backend = service.least_busy(operational=True, simulator=False, min_num_qubits=q.num_qubits)
isa = generate_preset_pass_manager(backend=backend, optimization_level=3).run(circ)
print(f"Backend: {backend.name} · transpiled depth {isa.depth()} · submitting {SHOTS} shots…")
job = SamplerV2(mode=backend).run([isa], shots=SHOTS)
print("Job ID:", job.job_id())
counts = job.result()[0].data.meas.get_counts()

# 3) decode
E = all_energies(q)
valid = opt = 0
best_seen = None
for bs, c in counts.items():
    b = int(bs, 2)
    order = decode(bits_to_x(b, q.num_qubits), q.n)
    if order is None:
        continue
    valid += c
    cost = route_cost(sc, order, LAM)
    if abs(cost - best) < 1e-6:
        opt += c
    if best_seen is None or cost < best_seen[1]:
        best_seen = (order, cost)

out = {
    "backend": backend.name, "job_id": job.job_id(), "shots": SHOTS,
    "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "qubits": q.num_qubits, "qaoa_p": 1, "transpiled_depth": isa.depth(),
    "valid_route_fraction": round(valid / SHOTS, 4), "optimal_route_fraction": round(opt / SHOTS, 4),
    "random_guess_optimal": round(1 / 2 ** q.num_qubits, 5),
    "simulator_optimal_probability": round(sim.p_opt_exact, 4),
    "best_route_sampled": route_label(sc, best_seen[0]) if best_seen else None,
    "best_route_is_optimal": bool(best_seen and abs(best_seen[1] - best) < 1e-6),
}
os.makedirs("results", exist_ok=True)
json.dump(out, open("results/ibm_run.json", "w"), indent=2)
print(json.dumps(out, indent=2))
