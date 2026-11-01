"""Minnal-Q demo app.   Run:  streamlit run app.py"""
import json
import os
from itertools import permutations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from minnal_q import DEMO_INCIDENTS, SLOTS, Incident, make_scenario, route_label
from minnal_q.city import NODES, build_graph
from minnal_q.classical import all_routes, brute_force, greedy_nearest, route_cost, time_only
from minnal_q.qaoa import solve_qaoa
from minnal_q.qubo import all_energies, auto_penalty, bits_to_x, decode, encode, to_ising
from minnal_q.scenario import SEVERITY_LABEL, evaluate

st.set_page_config(page_title="Minnal-Q · Quantum Ambulance Routing", page_icon="⚡", layout="wide",
                   initial_sidebar_state="expanded")

# ---------------------------------------------------------------- style
NAVY, AMBER, ORANGE, RED, PURPLE, GREY, GREEN = "#0B1D3A", "#FFB703", "#E8590C", "#D62828", "#6D28D9", "#94A3B8", "#15803D"
SEV_COL = {1: "#FACC15", 2: "#FB923C", 3: "#EA580C", 4: "#D62828"}
STRAT = {"Greedy": ("Nearest-first (today)", GREY), "Fastest": ("Fastest, ignores severity", "#3B82F6"),
         "Minnal-Q": ("Minnal-Q (quantum)", ORANGE)}

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stMarkdown, .stText {{ font-family: 'Inter', system-ui, sans-serif; }}
#MainMenu, footer {{ visibility: hidden; }}
.block-container {{ padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1400px; }}
.hero {{ background: radial-gradient(1200px 300px at 10% -20%, #24427a 0%, {NAVY} 55%);
        border-radius: 18px; padding: 22px 28px; color: #fff; position: relative; overflow: hidden;
        box-shadow: 0 10px 30px rgba(11,29,58,.25); margin-bottom: 18px; animation: fadein .6s ease; }}
.hero:after {{ content: "⚡"; position: absolute; right: 26px; top: -18px; font-size: 140px; opacity: .10; }}
.hero h1 {{ margin: 0; font-size: 2.1rem; font-weight: 800; letter-spacing: -.5px; color: #fff; }}
.hero .ml {{ color: {AMBER}; font-weight: 700; font-size: 1.5rem; margin-left: 10px; }}
.hero p {{ margin: 4px 0 12px; color: #cbd5e1; font-size: 1.02rem; }}
.chip {{ display: inline-block; padding: 4px 11px; margin: 0 6px 6px 0; border-radius: 999px; font-size: .78rem;
        background: rgba(255,255,255,.10); border: 1px solid rgba(255,255,255,.18); color: #e2e8f0; }}
.chip.q {{ background: rgba(255,183,3,.18); border-color: rgba(255,183,3,.45); color: {AMBER}; }}
.kpis {{ display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 14px; margin: 4px 0 16px; }}
.kpi {{ background: #fff; border-radius: 14px; padding: 14px 16px; border: 1px solid #E6E9F0;
        box-shadow: 0 2px 10px rgba(20,33,61,.05); transition: transform .15s ease, box-shadow .15s ease;
        animation: rise .5s ease both; }}
.kpi:hover {{ transform: translateY(-2px); box-shadow: 0 8px 22px rgba(20,33,61,.10); }}
.kpi .l {{ font-size: .78rem; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: .4px; }}
.kpi .v {{ font-size: 1.75rem; font-weight: 800; color: {NAVY}; line-height: 1.2; margin-top: 4px; }}
.kpi .s {{ font-size: .82rem; color: #64748b; margin-top: 2px; }}
.kpi.hot {{ border-color: rgba(232,89,12,.35); background: linear-gradient(180deg,#fff, #FFF4EC); }}
.kpi.hot .v {{ color: {ORANGE}; }}
.kpi.q {{ border-color: rgba(109,40,217,.25); background: linear-gradient(180deg,#fff,#F5F0FF); }}
.kpi.q .v {{ color: {PURPLE}; }}
.good {{ color: {GREEN}; font-weight: 700; }} .bad {{ color: {RED}; font-weight: 700; }}
.banner {{ border-radius: 12px; padding: 12px 16px; background: #ECFDF3; border: 1px solid #A7F3D0; color: #065F46;
          font-size: .98rem; margin: 2px 0 12px; animation: fadein .6s ease; }}
.card {{ background: #fff; border: 1px solid #E6E9F0; border-radius: 14px; padding: 14px 16px; margin-bottom: 12px; }}
.route {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 4px 0 10px; }}
.stop {{ padding: 4px 10px; border-radius: 8px; font-size: .82rem; font-weight: 600; background: #F1F5F9; color: {NAVY}; }}
.arrow {{ color: #94a3b8; }}
.sname {{ font-weight: 700; font-size: .9rem; margin-bottom: 2px; }}
.qgrid td, .qgrid th {{ text-align: center; padding: 8px 12px; border: 1px solid #E6E9F0; font-size: .9rem; }}
.qgrid th {{ background: #F8FAFC; color: #475569; }}
.qgrid td.on {{ background: {PURPLE}; color: #fff; font-weight: 700; }}
.check {{ padding: 8px 12px; border-radius: 10px; background: #fff; border: 1px solid #E6E9F0; margin-bottom: 6px; }}
section[data-testid="stSidebar"] {{ background: #FFFFFF; border-right: 1px solid #E6E9F0; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 6px; }}
.stTabs [data-baseweb="tab"] {{ background: #fff; border: 1px solid #E6E9F0; border-radius: 10px 10px 0 0; padding: 8px 16px; }}
.stTabs [aria-selected="true"] {{ border-bottom: 3px solid {ORANGE} !important; }}
@keyframes fadein {{ from {{ opacity: 0 }} to {{ opacity: 1 }} }}
@keyframes rise {{ from {{ opacity: 0; transform: translateY(6px) }} to {{ opacity: 1; transform: none }} }}
@media (max-width: 900px) {{ .kpis {{ grid-template-columns: repeat(2, minmax(0,1fr)); }} }}
</style>""", unsafe_allow_html=True)

JUNCTIONS = [k for k, v in NODES.items() if v[2] == "junction"]
HOSPITALS = [k for k, v in NODES.items() if v[2] == "hospital"]
BASE = "Ambulance Base (Kalamassery)"


def seg(label, options, default, key, **kw):
    """Segmented control that never returns None."""
    v = st.segmented_control(label, options, default=default, key=key, **kw)
    return default if v is None else v


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown(f"<div style='font-size:1.35rem;font-weight:800;color:{NAVY}'>⚡ Minnal-Q "
                f"<span style='color:{ORANGE}'>മിന്നൽ</span></div>"
                "<div style='color:#64748b;font-size:.85rem;margin-bottom:10px'>Scenario controls</div>",
                unsafe_allow_html=True)
    st.markdown("**🚦 Traffic**")
    slot = seg("Time of day", SLOTS, "Morning peak (9 AM)", "slot", label_visibility="collapsed")
    st.markdown("**🚑 Ambulance**")
    n = seg("Patients", [3, 4], 3, "n", format_func=lambda v: f"{v} patients · {v * v} qubits")
    hospital = st.selectbox("Destination hospital", HOSPITALS, index=HOSPITALS.index("Lakeshore Hospital"))
    st.markdown("**🧑‍⚕️ Patients**")
    incidents = []
    for i, (loc0, sev0) in enumerate(DEMO_INCIDENTS[n]):
        c1, c2 = st.columns([1.35, 1])
        loc = c1.selectbox(f"P{i + 1}", JUNCTIONS, index=JUNCTIONS.index(loc0), key=f"l{n}{i}")
        sev = c2.selectbox("Severity", [1, 2, 3, 4], index=sev0 - 1, key=f"s{n}{i}",
                           format_func=lambda s: ["🟡", "🟠", "🟧", "🔴"][s - 1] + " " + SEVERITY_LABEL[s])
        incidents.append(Incident(loc, sev))
    lam = st.slider("Severity priority λ", 0.0, 5.0, 2.0, 0.5,
                    help="0 = fastest route only. Higher = reach critical patients earlier.")
    with st.expander("⚛️ Quantum settings"):
        reps = seg("QAOA depth p", [1, 2], 2, "p")
        objective = seg("Objective", ["cvar", "expectation"], "cvar", "obj",
                        format_func=lambda o: "CVaR (α=0.2)" if o == "cvar" else "Expectation")
        st.caption("Backend: qiskit_aer.AerSimulator · 4,096 shots · COBYLA, 3 restarts · seed 7")

if len({i.location for i in incidents}) < n:
    st.error("Each patient needs a different location.")
    st.stop()

inc_key = tuple((i.location, i.severity) for i in incidents)


# ---------------------------------------------------------------- cached compute
@st.cache_data(show_spinner=False)
def get_scenario(slot, hospital, inc_key):
    return make_scenario(BASE, hospital, [Incident(l, s) for l, s in inc_key], slot)


@st.cache_data(show_spinner=False)
def get_qaoa(slot, hospital, inc_key, lam, reps, objective):
    sc = get_scenario(slot, hospital, inc_key)
    q = auto_penalty(sc, lam)
    r1 = solve_qaoa(q, reps=1, objective=objective, restarts=3)
    if reps == 1:
        return q, r1, r1
    warm = [r1.params[0], r1.params[0], r1.params[1], r1.params[1]]
    return q, r1, solve_qaoa(q, reps=2, objective=objective, restarts=3, warm=warm)


@st.cache_resource
def solver_lock():
    """One quantum simulation at a time, even with several browser tabs open."""
    import threading
    return threading.Lock()


sc = get_scenario(slot, hospital, inc_key)
greedy, fastest, exact = greedy_nearest(sc), time_only(sc), brute_force(sc, lam)
with st.spinner(f"⚡ Training QAOA on {n * n} qubits (AerSimulator)…"):
    with solver_lock():
        q, res_p1, res = get_qaoa(slot, hospital, inc_key, lam, reps, objective)
quantum = res.best_order
mq = evaluate(sc, quantum) if quantum else None

# ---------------------------------------------------------------- hero + KPIs
st.markdown(f"""
<div class="hero">
  <h1>⚡ Minnal-Q<span class="ml">മിന്നൽ</span></h1>
  <p>Lightning-fast quantum routing for life-critical emergencies in Kochi</p>
  <span class="chip">Challenge 1 · Emergency Vehicle Routing</span>
  <span class="chip q">QAOA · {n * n} qubits · p = {res.reps}</span>
  <span class="chip">Qiskit 2.6 · AerSimulator</span>
  <span class="chip">🚦 {slot}</span>
</div>""", unsafe_allow_html=True)

if mq:
    saved = greedy.critical_arrival - mq.critical_arrival
    extra = mq.total_time - greedy.total_time
    amp = res.p_opt_exact / res.random_p_opt
    extra_txt = (f"<span class='bad'>+{extra:.1f} min</span> vs nearest-first" if extra > 0.05 else
                 f"<span class='good'>{extra:.1f} min</span> vs nearest-first")
    st.markdown(f"""
<div class="kpis">
  <div class="kpi hot"><div class="l">Critical patient reached</div><div class="v">{mq.critical_arrival:.1f} min</div>
    <div class="s">nearest-first: {greedy.critical_arrival:.1f} min</div></div>
  <div class="kpi hot"><div class="l">Time saved for critical patient</div><div class="v">{saved:.1f} min</div>
    <div class="s">{'sooner than today' if saved > 0 else 'same as today'}</div></div>
  <div class="kpi"><div class="l">Total route time</div><div class="v">{mq.total_time:.1f} min</div>
    <div class="s">{extra_txt}</div></div>
  <div class="kpi q"><div class="l">QAOA finds best route</div><div class="v">{amp:.0f}× random</div>
    <div class="s">P(optimal) {res.p_opt_exact:.2%} · {res.seconds:.1f}s</div></div>
</div>""", unsafe_allow_html=True)
    if saved > 0:
        st.markdown(f"<div class='banner'>✅ <b>Minnal-Q reaches the critical patient {saved:.1f} minutes sooner</b> "
                    f"than nearest-first dispatch{f', for {extra:.1f} extra minutes of driving' if extra > 0.05 else ', and drives less overall'}.</div>",
                    unsafe_allow_html=True)

tabs = st.tabs(["🗺️ Live route", "⚛️ Quantum lab", "📊 All routes", "🧾 Evidence"])


# ---------------------------------------------------------------- helpers
def stops_of(order):
    return [BASE] + [sc.incidents[i].location for i in order] + [hospital]


def path_points(order, g):
    """Dense lat/lon/time samples along the road path of a route (for drawing and animation)."""
    lat, lon, t, now = [], [], [], 0.0
    stops = stops_of(order)
    for a, b in zip(stops, stops[1:]):
        nodes = sc.paths[(a, b)]
        for u, v in zip(nodes, nodes[1:]):
            mins = g[u][v]["minutes"]
            for k in range(10):
                f = k / 10
                lat.append(NODES[u][0] + f * (NODES[v][0] - NODES[u][0]))
                lon.append(NODES[u][1] + f * (NODES[v][1] - NODES[u][1]))
                t.append(now + f * mins)
            now += mins
    lat.append(NODES[hospital][0]); lon.append(NODES[hospital][1]); t.append(now)
    return lat, lon, t


def route_html(order, color):
    parts = ["<span class='stop'>🚑 Base</span>"]
    for i in order:
        inc = sc.incidents[i]
        parts.append(f"<span class='stop' style='border-left:4px solid {SEV_COL[inc.severity]}'>"
                     f"P{i + 1} · {inc.location}</span>")
    parts.append(f"<span class='stop' style='background:#ECFDF3'>🏥 {hospital}</span>")
    return f"<div class='route'>{'<span class=arrow>→</span>'.join(parts)}</div>"


def map_figure(g):
    fig = go.Figure()
    routes = [("Greedy", greedy.order, 3, 0.75), ("Fastest", fastest.order, 3, 0.75)]
    if quantum:
        routes.append(("Minnal-Q", quantum, 7, 0.95))
    for key, order, w, op in routes:
        lat, lon, _ = path_points(order, g)
        name, col = STRAT[key]
        fig.add_trace(go.Scattermap(lat=lat, lon=lon, mode="lines", name=name, opacity=op,
                                    line=dict(width=w, color=col), hoverinfo="name"))
    # base, hospital, patients
    fig.add_trace(go.Scattermap(lat=[NODES[BASE][0]], lon=[NODES[BASE][1]], mode="markers+text",
                                marker=dict(size=16, color=NAVY), text=["🚑 Base"], textposition="top left",
                                showlegend=False, hovertext=[BASE], hoverinfo="text"))
    fig.add_trace(go.Scattermap(lat=[NODES[hospital][0]], lon=[NODES[hospital][1]], mode="markers+text",
                                marker=dict(size=18, color=GREEN), text=[f"🏥 {hospital}"], textposition="bottom right",
                                showlegend=False, hoverinfo="text", hovertext=[hospital]))
    for k, inc in enumerate(sc.incidents):
        fig.add_trace(go.Scattermap(
            lat=[NODES[inc.location][0]], lon=[NODES[inc.location][1]], mode="markers+text",
            marker=dict(size=12 + 5 * inc.severity, color=SEV_COL[inc.severity]),
            text=[f"P{k + 1} {SEVERITY_LABEL[inc.severity]}"], textposition="top right", showlegend=False,
            hoverinfo="text", hovertext=[f"P{k + 1} · {inc.location} · {SEVERITY_LABEL[inc.severity]}"]))
    # animated ambulance along the quantum route
    if quantum:
        lat, lon, t = path_points(quantum, g)
        amb = len(fig.data)
        fig.add_trace(go.Scattermap(lat=[lat[0]], lon=[lon[0]], mode="markers+text", text=["🚑"],
                                    textfont=dict(size=22), marker=dict(size=26, color="rgba(232,89,12,.25)"),
                                    showlegend=False, hoverinfo="skip"))
        step = max(1, len(lat) // 90)
        idxs = list(range(0, len(lat), step)) + [len(lat) - 1]
        fig.frames = [go.Frame(data=[go.Scattermap(lat=[lat[i]], lon=[lon[i]])], traces=[amb], name=str(i),
                               layout=dict(title=dict(text=f"⏱ {t[i]:.1f} min on the Minnal-Q route")))
                      for i in idxs]
        fig.update_layout(updatemenus=[dict(
            type="buttons", direction="left", x=0.01, y=0.02, xanchor="left", yanchor="bottom",
            bgcolor="#fff", bordercolor="#E6E9F0", font=dict(size=13),
            buttons=[dict(label="▶  Play ambulance", method="animate",
                          args=[None, dict(frame=dict(duration=70, redraw=True), transition=dict(duration=0),
                                           fromcurrent=True, mode="immediate")]),
                     dict(label="⏸", method="animate",
                          args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")])])])
    lats = [v[0] for v in NODES.values()]; lons = [v[1] for v in NODES.values()]
    fig.update_layout(map=dict(style="carto-positron", center=dict(lat=float(np.mean(lats)), lon=float(np.mean(lons))),
                               zoom=11.3),
                      title=dict(text="Press ▶ to watch the ambulance", x=0.5, y=0.98, font=dict(size=14, color=NAVY)),
                      margin=dict(l=0, r=0, t=34, b=0), height=560, paper_bgcolor="rgba(0,0,0,0)",
                      legend=dict(yanchor="top", y=0.97, xanchor="left", x=0.01, bgcolor="rgba(255,255,255,.92)",
                                  bordercolor="#E6E9F0", borderwidth=1))
    return fig


def timeline_figure():
    rows = [("Greedy", greedy), ("Fastest", fastest)] + ([("Minnal-Q", mq)] if mq else [])
    fig = go.Figure()
    for key, r in rows:
        name, col = STRAT[key]
        fig.add_trace(go.Scatter(x=[0, r.total_time], y=[name, name], mode="lines", line=dict(color=col, width=6),
                                 showlegend=False, hoverinfo="skip", opacity=.35))
        for i, inc in enumerate(sc.incidents):
            fig.add_trace(go.Scatter(
                x=[r.arrivals[i]], y=[name], mode="markers+text", text=[f"P{i + 1}"], textposition="top center",
                marker=dict(size=10 + 4 * inc.severity, color=SEV_COL[inc.severity], line=dict(color="#fff", width=2)),
                showlegend=False,
                hovertemplate=f"{name}<br>P{i + 1} {SEVERITY_LABEL[inc.severity]} @ {inc.location}<br>reached at %{{x:.1f}} min<extra></extra>"))
        fig.add_trace(go.Scatter(x=[r.total_time], y=[name], mode="markers+text", text=["🏥"], textposition="middle right",
                                 marker=dict(size=10, color=GREEN, symbol="square"), showlegend=False,
                                 hovertemplate=f"{name}<br>hospital at %{{x:.1f}} min<extra></extra>"))
    fig.update_layout(height=250, margin=dict(l=0, r=20, t=10, b=30), xaxis_title="minutes from dispatch",
                      plot_bgcolor="#fff", paper_bgcolor="rgba(0,0,0,0)",
                      xaxis=dict(gridcolor="#EEF2F7", zeroline=False), yaxis=dict(autorange="reversed"))
    return fig


# ---------------------------------------------------------------- tab 1: live route
with tabs[0]:
    g = build_graph(slot)
    c1, c2 = st.columns([1.7, 1], gap="large")
    with c1:
        st.plotly_chart(map_figure(g), width="stretch", config={"displayModeBar": False, "scrollZoom": True})
    with c2:
        st.markdown("##### 🧭 Routes")
        for key, r in [("Minnal-Q", mq), ("Greedy", greedy), ("Fastest", fastest)]:
            if r is None:
                continue
            name, col = STRAT[key]
            st.markdown(f"<div class='card'><div class='sname' style='color:{col}'>● {name}</div>"
                        f"{route_html(r.order, col)}"
                        f"<div style='font-size:.85rem;color:#475569'>Total <b>{r.total_time:.1f} min</b> · "
                        f"critical patient at <b>{r.critical_arrival:.1f} min</b></div></div>", unsafe_allow_html=True)
    st.markdown("##### ⏱️ When is each patient reached?")
    st.plotly_chart(timeline_figure(), width="stretch", config={"displayModeBar": False})
    st.caption("Bigger, redder dots = more severe patients. Travel times use Dijkstra on a Kochi junction graph with "
               "synthetic time-of-day traffic; coordinates are approximate. Time = minutes until the ambulance reaches "
               "each patient (first medical contact).")

# ---------------------------------------------------------------- tab 2: quantum lab
with tabs[1]:
    st.markdown(f"""
<div class="kpis">
  <div class="kpi q"><div class="l">Qubits</div><div class="v">{q.num_qubits}</div><div class="s">{n} patients × {n} stops</div></div>
  <div class="kpi q"><div class="l">P(optimal route)</div><div class="v">{res.p_opt_exact:.2%}</div>
    <div class="s">random guess: {res.random_p_opt:.3%}</div></div>
  <div class="kpi q"><div class="l">Valid routes sampled</div><div class="v">{res.feasible_frac:.1%}</div>
    <div class="s">random guess: {res.random_feasible:.2%}</div></div>
  <div class="kpi q"><div class="l">Circuit</div><div class="v">depth {res.depth}</div>
    <div class="s">{res.two_qubit_gates} two-qubit gates · p = {res.reps}</div></div>
</div>""", unsafe_allow_html=True)
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("##### 🎯 How often QAOA hits the best route")
        bars = [("Random guess", res.random_p_opt, GREY), ("QAOA p = 1", res_p1.p_opt_exact, "#A78BFA")]
        if res.reps == 2:
            bars.append(("QAOA p = 2", res.p_opt_exact, PURPLE))
        fig = go.Figure(go.Bar(x=[b[0] for b in bars], y=[b[1] * 100 for b in bars], marker_color=[b[2] for b in bars],
                               text=[f"{b[1]:.2%}" for b in bars], textposition="outside"))
        fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="probability (%)",
                          plot_bgcolor="#fff", paper_bgcolor="rgba(0,0,0,0)", yaxis=dict(gridcolor="#EEF2F7"))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        st.caption("Exact probability of measuring an optimal route from the trained circuit. Deeper circuits (p = 2) "
                   "concentrate more probability on the answer.")
    with c2:
        st.markdown("##### 🧪 Routes measured (4,096 shots, valid only)")
        costs = {o: route_cost(sc, o, lam) for o in permutations(range(n))}
        best = min(costs.values())
        items = sorted(res.route_counts.items(), key=lambda kv: costs[kv[0]])[:12]
        labels = [" → ".join(f"P{i + 1}" for i in o) + f"  ·  cost {costs[o]:.0f}" for o, _ in items]
        fig = go.Figure(go.Bar(x=[v for _, v in items], y=labels, orientation="h",
                               marker_color=[ORANGE if abs(costs[o] - best) < 1e-6 else "#CBD5E1" for o, _ in items]))
        fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="shots", plot_bgcolor="#fff",
                          paper_bgcolor="rgba(0,0,0,0)", yaxis=dict(autorange="reversed"), xaxis=dict(gridcolor="#EEF2F7"))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        st.caption("Orange = optimal route. Sorted best to worst cost (top 12).")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown("##### 🔢 Problem → qubits (optimal route lit up)")
        x_opt = encode(exact.order, n)
        head = "".join(f"<th>Stop {p + 1}</th>" for p in range(n))
        body = ""
        for i, inc in enumerate(sc.incidents):
            cells = "".join(f"<td class='{'on' if x_opt[i * n + p] else ''}'>q{i * n + p}</td>" for p in range(n))
            body += f"<tr><th style='text-align:left'>P{i + 1} {SEVERITY_LABEL[inc.severity]}</th>{cells}</tr>"
        st.markdown(f"<table class='qgrid' style='width:100%;border-collapse:collapse'><tr><th></th>{head}</tr>{body}</table>",
                    unsafe_allow_html=True)
        op, _ = to_ising(q)
        st.caption(f"Qubit q(i·n+p) = 1 means patient i is visited at stop p. Ising operator: {len(op)} Pauli terms · "
                   f"penalty A = {q.penalty:.1f} · λ = {lam}.")
    with c2:
        st.markdown("##### 🔁 Hybrid training loop (COBYLA ↔ circuit)")
        fig = go.Figure(go.Scatter(y=res.history, mode="lines", line=dict(color=PURPLE, width=2), fill="tozeroy",
                                   fillcolor="rgba(109,40,217,.08)"))
        fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="optimizer step",
                          yaxis_title=f"normalised {res.objective}", plot_bgcolor="#fff", paper_bgcolor="rgba(0,0,0,0)",
                          xaxis=dict(gridcolor="#EEF2F7"), yaxis=dict(gridcolor="#EEF2F7"))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with st.expander("Show the QAOA circuit"):
        ops = res.circuit.decompose().count_ops()
        st.caption(f"{res.circuit.num_qubits} qubits · p = {res.reps} · gates after one decomposition: "
                   + ", ".join(f"{k} × {v}" for k, v in ops.items()))
        if q.num_qubits > 9:
            st.info("The 16-qubit circuit is too large to draw clearly. Switch to 3 patients to see the full circuit.")
        elif st.toggle("Draw circuit", key="draw_circ"):
            import matplotlib
            matplotlib.use("Agg")
            fig_c = res.circuit.decompose().draw("mpl", fold=40, scale=0.55)
            st.pyplot(fig_c)
            import matplotlib.pyplot as plt
            plt.close(fig_c)

# ---------------------------------------------------------------- tab 3: all routes
with tabs[2]:
    st.markdown(f"##### Every possible visiting order ({len(list(permutations(range(n))))} = {n}!)")
    rows_ = []
    best_cost = route_cost(sc, exact.order, lam)
    for o, cost in all_routes(sc, lam):
        r = evaluate(sc, o)
        tags = " ".join(t for t, ok in [("🏆 optimum", abs(cost - best_cost) < 1e-6), ("⚛️ QAOA", quantum == o),
                                        ("🐢 nearest-first", o == greedy.order), ("🏎 fastest", o == fastest.order)] if ok)
        rows_.append({"Route": route_label(sc, o), "Minnal-Q cost": round(cost, 1), "Total (min)": r.total_time,
                      "Critical reached (min)": r.critical_arrival, "Tags": tags})
    st.dataframe(pd.DataFrame(rows_), width="stretch", hide_index=True,
                 column_config={"Minnal-Q cost": st.column_config.ProgressColumn(
                     "Minnal-Q cost", format="%.1f", min_value=0, max_value=max(r["Minnal-Q cost"] for r in rows_))})
    st.caption("The exact optimum comes from brute force and is the answer key for QAOA. Brute force is instant at this "
               "size; the number of orders grows as n!.")
    if os.path.exists("results/benchmark.csv"):
        st.markdown("##### Benchmark across all traffic slots (`results/benchmark.csv`)")
        bm = pd.read_csv("results/benchmark.csv")
        st.dataframe(bm[["patients", "qubits", "slot", "p", "greedy_critical", "minnal_critical", "greedy_total",
                         "minnal_total", "qaoa_found_optimum", "qaoa_p_opt", "amplification", "feasible_frac",
                         "depth", "two_qubit_gates", "seconds"]], width="stretch", hide_index=True)

# ---------------------------------------------------------------- tab 4: evidence
with tabs[3]:
    c1, c2 = st.columns([1, 1.25], gap="large")
    with c1:
        st.markdown("##### ✅ Live correctness checks")
        E = all_energies(q)
        g0 = int(np.argmin(E))
        op, const = to_ising(q)
        checks = [
            ("QUBO energy = route cost for every valid route",
             all(abs(q.energy(encode(o, n)) - route_cost(sc, o, lam)) < 1e-6 for o in permutations(range(n)))),
            ("QUBO lowest-energy state is a valid route", decode(bits_to_x(g0, q.num_qubits), n) is not None),
            ("QUBO lowest energy = brute-force optimum", abs(E[g0] - best_cost) < 1e-6),
            ("Ising operator = QUBO on all 2^N bitstrings",
             bool(np.allclose(np.real(op.to_matrix(sparse=True).diagonal()) + const, E))),
            ("QAOA's best sampled route = exact optimum",
             bool(quantum and abs(route_cost(sc, quantum, lam) - best_cost) < 1e-6)),
        ]
        for name, ok in checks:
            st.markdown(f"<div class='check'>{'✅' if ok else '❌'} {name}</div>", unsafe_allow_html=True)
        st.caption("Computed live for the current scenario. 18 automated tests run the same checks across all slots (`pytest`).")
        if os.path.exists("results/ibm_run.json"):
            st.markdown("##### 🖥️ Real IBM quantum hardware run")
            st.json(json.load(open("results/ibm_run.json")))
    with c2:
        st.markdown("##### 🔍 Transparency")
        st.table(pd.DataFrame([
            ["Implemented", "Kochi graph + traffic, Dijkstra, QUBO, QUBO→Ising, QAOA (qaoa_ansatz) + COBYLA, Aer sampling, 3 baselines, this app, 18 tests"],
            ["Simulated", "All QAOA results use Qiskit Aer / statevector simulation (no hardware noise)"],
            ["Synthetic", "Travel times, traffic multipliers, patient locations (real Kochi place names, approximate coordinates)"],
            ["Measured", "P(optimal), valid-sample rate, depth, gate counts, runtime (results/benchmark.csv)"],
            ["Modelling note", "QUBO uses a quadratic position penalty λ·w·p for severity; arrival times are recomputed exactly"],
            ["Not claimed", "Quantum advantage. At 3–4 patients brute force is instant; we show a correct, verified quantum pipeline"],
        ], columns=["", "Details"]).set_index(""))
        st.markdown("##### 📚 References (ideas only, no code copied)")
        st.markdown("- [QuRoute](https://github.com/AnuragKannojiya/quroute): multi-stop route QUBO, baselines\n"
                    "- [Severity-Aware Emergency Dispatch Using QAOA](https://github.com/shrisha77-boop/Severity-Aware-Emergency-Dispatch-Using-QAOA): severity weights, CVaR\n"
                    "- [PairCover-Q / Q-Rescue](https://github.com/gautham-code505/PairCover-Q-): transparency and hardware evidence\n"
                    "- Qiskit and Qiskit Aer (IBM, Apache 2.0)")
