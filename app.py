"""Minnal-Q demo app.   Run:  streamlit run app.py"""
import json
import os
from itertools import permutations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from minnal_q import SLOTS, Incident, make_scenario, route_label
from minnal_q.city import NODES
from minnal_q.classical import all_routes, brute_force, greedy_nearest, route_cost, time_only
from minnal_q.qubo import all_energies, auto_penalty, bits_to_x, decode, encode, to_ising
from minnal_q.qaoa import solve_qaoa
from minnal_q.scenario import SEVERITY_LABEL
from minnal_q import DEMO_INCIDENTS

st.set_page_config(page_title="Minnal-Q · Quantum Ambulance Routing", page_icon="⚡", layout="wide")

JUNCTIONS = [k for k, v in NODES.items() if v[2] == "junction"]
HOSPITALS = [k for k, v in NODES.items() if v[2] == "hospital"]
BASE = "Ambulance Base (Kalamassery)"
COLORS = {"Greedy (nearest first)": "#7b8794", "Fastest (ignores severity)": "#2457a6", "Minnal-Q (QAOA)": "#c0392b"}

# ---------------- sidebar ----------------
st.sidebar.title("⚡ Minnal-Q")
st.sidebar.caption("മിന്നൽ · Lightning-fast quantum routing for life-critical emergencies")
slot = st.sidebar.selectbox("Time of day (traffic)", SLOTS, index=SLOTS.index("Morning peak (9 AM)"))
n = st.sidebar.radio("Patients for this ambulance", [3, 4], horizontal=True,
                     help="3 patients = 9 qubits, 4 patients = 16 qubits")
hospital = st.sidebar.selectbox("Destination hospital", HOSPITALS, index=HOSPITALS.index("Lakeshore Hospital"))
st.sidebar.markdown("**Patients**")
incidents = []
for i, (loc0, sev0) in enumerate(DEMO_INCIDENTS[n]):
    c1, c2 = st.sidebar.columns([3, 2])
    loc = c1.selectbox(f"P{i + 1} location", JUNCTIONS, index=JUNCTIONS.index(loc0), key=f"l{n}{i}")
    sev = c2.selectbox("Severity", [1, 2, 3, 4], index=sev0 - 1, key=f"s{n}{i}",
                       format_func=lambda s: SEVERITY_LABEL[s])
    incidents.append(Incident(loc, sev))
lam = st.sidebar.slider("Severity priority λ", 0.0, 5.0, 2.0, 0.5,
                        help="0 = fastest route only. Higher = reach critical patients earlier.")
reps = st.sidebar.radio("QAOA depth p", [1, 2], index=1, horizontal=True)
objective = st.sidebar.radio("QAOA objective", ["cvar", "expectation"], horizontal=True,
                             help="CVaR (α = 0.2) focuses training on the best samples")
run = st.sidebar.button("⚡ Run Minnal-Q", type="primary", width="stretch")

if len({i.location for i in incidents}) < n:
    st.error("Each patient needs a different location.")
    st.stop()

sc = make_scenario(BASE, hospital, incidents, slot)
greedy, fastest, exact = greedy_nearest(sc), time_only(sc), brute_force(sc, lam)
q = auto_penalty(sc, lam)

key = (slot, n, hospital, tuple((i.location, i.severity) for i in incidents), lam, reps, objective)
if run or st.session_state.get("key") != key:
    if run or "res" not in st.session_state:
        with st.spinner(f"Training QAOA on {q.num_qubits} qubits (AerSimulator)…"):
            warm = None
            if reps == 2:
                r1 = solve_qaoa(q, reps=1, objective=objective, restarts=3)
                warm = [r1.params[0], r1.params[0], r1.params[1], r1.params[1]]
            st.session_state.res = solve_qaoa(q, reps=reps, objective=objective, restarts=3, warm=warm)
            st.session_state.key = key
res = st.session_state.get("res")
stale = st.session_state.get("key") != key
quantum = (res.best_order if res and not stale else None)

st.title("⚡ Minnal-Q: Quantum Ambulance Routing for Kochi")
st.caption("Challenge 1 · Emergency Vehicle Routing · QFF26 Kochi Hack · QAOA on a QUBO, Qiskit 2.x + AerSimulator")
if stale:
    st.info("Settings changed. Press **⚡ Run Minnal-Q** in the sidebar to re-run the quantum solver.")

tabs = st.tabs(["🗺️ Scenario & Routes", "⚛️ Quantum Lab", "📊 Compare", "🧾 Evidence"])

# ---------------- map helpers ----------------
def path_coords(order):
    stops = [BASE] + [sc.incidents[i].location for i in order] + [hospital]
    lat, lon = [], []
    for a, b in zip(stops, stops[1:]):
        for node in sc.paths[(a, b)]:
            lat.append(NODES[node][0]); lon.append(NODES[node][1])
    return lat, lon


def draw_map(routes):
    fig = go.Figure()
    for name, order, width in routes:
        lat, lon = path_coords(order)
        fig.add_trace(go.Scattermap(lat=lat, lon=lon, mode="lines", name=name,
                                    line=dict(width=width, color=COLORS[name])))
    pts = [(BASE, "Ambulance base", "#111111", 14)] + [(hospital, "Hospital", "#1e8449", 16)]
    sev_col = {1: "#f1c40f", 2: "#e67e22", 3: "#d35400", 4: "#c0392b"}
    for name, label, col, size in pts:
        fig.add_trace(go.Scattermap(lat=[NODES[name][0]], lon=[NODES[name][1]], mode="markers+text",
                                    marker=dict(size=size, color=col), text=[f"{label}: {name}"],
                                    textposition="top right", name=label, showlegend=False))
    for k, inc in enumerate(sc.incidents):
        fig.add_trace(go.Scattermap(lat=[NODES[inc.location][0]], lon=[NODES[inc.location][1]], mode="markers+text",
                                    marker=dict(size=10 + 4 * inc.severity, color=sev_col[inc.severity]),
                                    text=[f"P{k + 1} {SEVERITY_LABEL[inc.severity]}"], textposition="bottom right",
                                    showlegend=False))
    fig.update_layout(map=dict(style="open-street-map", center=dict(lat=10.0, lon=76.31), zoom=11.2),
                      margin=dict(l=0, r=0, t=0, b=0), height=520,
                      legend=dict(yanchor="top", y=0.98, xanchor="left", x=0.01, bgcolor="rgba(255,255,255,0.85)"))
    return fig


def row(name, order):
    from minnal_q.scenario import evaluate
    r = evaluate(sc, order)
    d = {"Strategy": name, "Route": route_label(sc, order), "Total time (min)": r.total_time,
         "Critical patient reached (min)": r.critical_arrival, "Severity-weighted wait": r.weighted_arrival}
    for i, inc in enumerate(sc.incidents):
        d[f"P{i + 1} {SEVERITY_LABEL[inc.severity]} @ {inc.location}"] = r.arrivals[i]
    return d


# ---------------- tab 1 ----------------
with tabs[0]:
    routes = [("Greedy (nearest first)", greedy.order, 4), ("Fastest (ignores severity)", fastest.order, 4)]
    if quantum:
        routes.append(("Minnal-Q (QAOA)", quantum, 7))
    c1, c2 = st.columns([3, 2])
    with c1:
        st.plotly_chart(draw_map(routes), width="stretch")
    with c2:
        st.subheader("Who gets reached when?")
        if quantum:
            from minnal_q.scenario import evaluate
            mq = evaluate(sc, quantum)
            saved = greedy.critical_arrival - mq.critical_arrival
            extra = mq.total_time - greedy.total_time
            m1, m2 = st.columns(2)
            m1.metric("Critical patient reached", f"{mq.critical_arrival:.1f} min",
                      f"{-saved:+.1f} min vs greedy", delta_color="inverse")
            m2.metric("Total route time", f"{mq.total_time:.1f} min", f"{extra:+.1f} min vs greedy",
                      delta_color="inverse")
            if saved > 0:
                st.success(f"Minnal-Q reaches the **critical patient {saved:.1f} minutes sooner** than nearest-first "
                           f"dispatch{f', for {extra:.1f} extra minutes of total driving' if extra > 0 else ''}.")
            elif saved == 0:
                st.info("In this scenario the nearest-first route already reaches the critical patient first.")
        df = pd.DataFrame([row("Greedy", greedy.order), row("Fastest", fastest.order)] +
                          ([row("Minnal-Q (QAOA)", quantum)] if quantum else []))
        st.dataframe(df.drop(columns=["Route"]).set_index("Strategy").T, width="stretch")
        for _, r in df.iterrows():
            st.markdown(f"**{r['Strategy']}:** {r['Route']}")
    st.caption("Travel times: Dijkstra on a Kochi junction graph with synthetic time-of-day traffic multipliers. "
               "Coordinates approximate. Time = minutes until the ambulance reaches each patient (first medical contact).")

# ---------------- tab 2 ----------------
with tabs[1]:
    if not res or stale:
        st.warning("Run Minnal-Q to see the quantum results.")
    else:
        a, b, c, d = st.columns(4)
        a.metric("Qubits", q.num_qubits)
        b.metric("P(optimal route)", f"{res.p_opt_exact:.2%}", f"{res.p_opt_exact / res.random_p_opt:.0f}× random")
        c.metric("Valid routes in samples", f"{res.feasible_frac:.1%}", f"{res.feasible_frac / res.random_feasible:.0f}× random")
        d.metric("Circuit", f"depth {res.depth}", f"{res.two_qubit_gates} two-qubit gates", delta_color="off")
        st.caption(f"QAOA p = {res.reps}, objective = {res.objective}, {res.shots} shots on AerSimulator, "
                   f"COBYLA training, {res.seconds}s. Random guessing would hit an optimal route with probability "
                   f"{res.random_p_opt:.4%}.")
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Sampled routes (valid only)")
            costs = {o: route_cost(sc, o, lam) for o in permutations(range(n))}
            best = min(costs.values())
            items = sorted(res.route_counts.items(), key=lambda kv: costs[kv[0]])
            labels = [" → ".join(f"P{i + 1}" for i in o) + f"  (cost {costs[o]:.0f})" for o, _ in items]
            fig = go.Figure(go.Bar(x=[v for _, v in items], y=labels, orientation="h",
                                   marker_color=["#c0392b" if abs(costs[o] - best) < 1e-6 else "#9aa5b1" for o, _ in items]))
            fig.update_layout(height=360, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="shots",
                              yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, width="stretch")
            st.caption("Red = optimal route. Sorted from best to worst cost.")
        with c2:
            st.subheader("Training (hybrid loop)")
            fig = go.Figure(go.Scatter(y=res.history, mode="lines", line=dict(color="#6c3fb5")))
            fig.update_layout(height=360, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="optimizer evaluation",
                              yaxis_title=f"normalised {res.objective}")
            st.plotly_chart(fig, width="stretch")
            st.caption("COBYLA (classical) adjusts γ, β; the quantum circuit returns the cost. Restarts show as jumps.")
        with st.expander("How the routing problem maps to qubits"):
            grid = pd.DataFrame([[f"q{i * n + p}" for p in range(n)] for i in range(n)],
                                index=[f"P{i + 1} {SEVERITY_LABEL[inc.severity]}" for i, inc in enumerate(sc.incidents)],
                                columns=[f"Stop {p + 1}" for p in range(n)])
            st.table(grid)
            st.markdown("Qubit **q(i·n+p) = 1** means patient i is visited at stop p. The QUBO adds traffic-adjusted "
                        "travel time, a severity penalty λ·wᵢ·p, and a large penalty for invalid routes. It is converted "
                        "to an Ising operator (`SparsePauliOp`) and solved with `qaoa_ansatz`.")
            op, _ = to_ising(q)
            st.code(f"Ising operator: {len(op)} Pauli terms on {q.num_qubits} qubits · penalty A = {q.penalty:.1f} · λ = {lam}")
        with st.expander("QAOA circuit"):
            try:
                import matplotlib
                matplotlib.use("Agg")
                st.pyplot(res.circuit.decompose().draw("mpl", fold=30, scale=0.6))
            except Exception as e:  # pragma: no cover
                st.text(res.circuit.draw("text"))

# ---------------- tab 3 ----------------
with tabs[2]:
    st.subheader("All possible visiting orders")
    rows_ = []
    from minnal_q.scenario import evaluate
    for o, cost in all_routes(sc, lam):
        r = evaluate(sc, o)
        rows_.append({"Route": route_label(sc, o), "Minnal-Q cost": round(cost, 1), "Total time": r.total_time,
                      "Critical reached": r.critical_arrival,
                      "Greedy": "✓" if o == greedy.order else "", "Fastest": "✓" if o == fastest.order else "",
                      "Exact optimum": "✓" if abs(cost - route_cost(sc, exact.order, lam)) < 1e-6 else "",
                      "QAOA pick": "✓" if quantum and o == quantum else ""})
    st.dataframe(pd.DataFrame(rows_), width="stretch", hide_index=True)
    st.caption(f"{len(rows_)} orders (n! = {len(rows_)}). The exact optimum comes from brute force and is the answer "
               "key for QAOA. Brute force is instant at this size; it grows as n! for larger cases.")
    if os.path.exists("results/benchmark.csv"):
        st.subheader("Benchmark across traffic slots (results/benchmark.csv)")
        bm = pd.read_csv("results/benchmark.csv")
        st.dataframe(bm[["patients", "qubits", "slot", "p", "greedy_critical", "minnal_critical", "minnal_total",
                         "greedy_total", "qaoa_found_optimum", "qaoa_p_opt", "amplification", "feasible_frac",
                         "approx_ratio", "depth", "two_qubit_gates"]], width="stretch", hide_index=True)

# ---------------- tab 4 ----------------
with tabs[3]:
    st.subheader("Live correctness checks")
    E = all_energies(q)
    g = int(np.argmin(E))
    op, const = to_ising(q)
    ising_ok = np.allclose(np.real(op.to_matrix(sparse=True).diagonal()) + const, E) if q.num_qubits <= 16 else None
    checks = [
        ("QUBO energy = route cost for every valid route",
         all(abs(q.energy(encode(o, n)) - route_cost(sc, o, lam)) < 1e-6 for o in permutations(range(n)))),
        ("QUBO lowest-energy state is a valid route", decode(bits_to_x(g, q.num_qubits), n) is not None),
        ("QUBO lowest energy = brute-force optimum", abs(E[g] - route_cost(sc, exact.order, lam)) < 1e-6),
        ("Ising operator matches QUBO on all 2^N bitstrings", ising_ok),
        ("QAOA's best sampled route = exact optimum",
         bool(quantum and abs(route_cost(sc, quantum, lam) - route_cost(sc, exact.order, lam)) < 1e-6) if res and not stale else None),
    ]
    for name, ok in checks:
        st.markdown(f"{'✅' if ok else ('⏳' if ok is None else '❌')} {name}")
    st.subheader("Transparency")
    st.table(pd.DataFrame([
        ["Implemented", "Kochi graph + traffic, Dijkstra, QUBO, QUBO→Ising, QAOA (qaoa_ansatz) + COBYLA, Aer sampling, baselines, this app, 18 unit tests"],
        ["Simulated", "All QAOA results come from Qiskit Aer / statevector simulation (no hardware noise)"],
        ["Synthetic", "Travel times, traffic multipliers and patient locations (place names are real Kochi locations)"],
        ["Measured", "P(optimal), valid-sample rate, approximation ratio, depth, gate counts, runtime (results/benchmark.csv)"],
        ["Modelling note", "The QUBO uses a position-based severity penalty (quadratic). Exact arrival times are recomputed classically."],
        ["Not claimed", "Quantum advantage. At 3–4 patients brute force is instant; the demo shows a correct, verified quantum pipeline."],
    ], columns=["", "Details"]).set_index(""))
    if os.path.exists("results/ibm_run.json"):
        st.subheader("Real IBM quantum hardware run")
        st.json(json.load(open("results/ibm_run.json")))
    st.caption("References (patterns only, no code copied): QuRoute, Severity-Aware Emergency Dispatch Using QAOA, "
               "PairCover-Q / Q-Rescue. See README.")
