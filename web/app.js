/* Minnal-Q web client: map, controls, results, charts. */
const SEV = {
  1: { label: "Minor", color: "#FACC15" }, 2: { label: "Moderate", color: "#FB923C" },
  3: { label: "Serious", color: "#EA580C" }, 4: { label: "Critical", color: "#D62828" },
};
const COL = { minnal: "#E8590C", greedy: "#94A3B8", fastest: "#3B82F6", quantum: "#6D28D9" };
const NAMES = { minnal: "Minnal-Q (quantum)", greedy: "Nearest-first (today)", fastest: "Fastest, ignores severity" };

const state = {
  meta: null, slot: "Morning peak (9 AM)", hospital: "Lakeshore Hospital", patients: [],
  lam: 2, reps: 2, objective: "cvar", result: null, dirty: true,
};
const $ = (id) => document.getElementById(id);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "style") e.style.cssText = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const kid of kids) e.append(kid instanceof Node ? kid : document.createTextNode(kid));
  return e;
};
const fmt = (x, d = 1) => Number(x).toFixed(d);
const toast = (msg) => {
  const t = $("toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), 2600);
};
const nodeByName = (n) => state.meta.nodes.find((x) => x.name === n);

/* ---------------- map ---------------- */
const map = L.map("map", { zoomControl: true, preferCanvas: false }).setView([10.0, 76.31], 12);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, className: "tiles",
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);
const layers = { nodes: L.layerGroup().addTo(map), routes: L.layerGroup().addTo(map), pins: L.layerGroup().addTo(map) };
let ambMarker = null, anim = null;

function pinIcon(text, color, size, pulse = false) {
  return L.divIcon({
    className: "", iconSize: [size, size], iconAnchor: [size / 2, size / 2],
    html: `<div class="pin${pulse ? " pulse" : ""}" style="width:${size}px;height:${size}px;background:${color};font-size:${Math.round(size / 2.4)}px">${text}</div>`,
  });
}

function drawNodes() {
  layers.nodes.clearLayers();
  for (const n of state.meta.nodes) {
    if (n.kind !== "junction") continue;
    const m = L.circleMarker([n.lat, n.lon], { radius: 6, color: "#64748B", weight: 2, fillColor: "#fff", fillOpacity: 1 })
      .bindTooltip(n.name, { direction: "top", offset: [0, -6] });
    m.on("click", () => openAddPopup(n));
    layers.nodes.addLayer(m);
  }
}

function openAddPopup(n) {
  const used = state.patients.findIndex((p) => p.location === n.name);
  const box = el("div", {}, el("b", {}, n.name));
  if (used >= 0) {
    box.append(el("div", { style: "margin-top:6px;color:#64748B" }, `Patient P${used + 1} is here.`));
  } else if (state.patients.length >= 4) {
    box.append(el("div", { style: "margin-top:6px;color:#64748B" }, "Maximum 4 patients (16 qubits)."));
  } else {
    box.append(el("div", { style: "margin-top:6px;color:#64748B;font-size:12px" }, "Add a patient here:"));
    const row = el("div", { class: "popsev" });
    for (const s of [1, 2, 3, 4]) {
      row.append(el("button", { style: `background:${SEV[s].color}`, onclick: () => {
        state.patients.push({ location: n.name, severity: s }); map.closePopup(); changed(); renderPatients(); drawPins();
      } }, SEV[s].label));
    }
    box.append(row);
  }
  L.popup({ offset: [0, -4] }).setLatLng([n.lat, n.lon]).setContent(box).openOn(map);
}

function drawPins() {
  layers.pins.clearLayers();
  const base = nodeByName(state.meta.base), hosp = nodeByName(state.hospital);
  layers.pins.addLayer(L.marker([base.lat, base.lon], { icon: pinIcon("🚑", "#0B1D3A", 34), zIndexOffset: 500 })
    .bindTooltip(state.meta.base, { direction: "top", offset: [0, -16] }));
  layers.pins.addLayer(L.marker([hosp.lat, hosp.lon], { icon: pinIcon("🏥", "#15803D", 34), zIndexOffset: 500 })
    .bindTooltip(state.hospital, { direction: "top", offset: [0, -16] }));
  state.patients.forEach((p, i) => {
    const n = nodeByName(p.location), size = 24 + p.severity * 4;
    layers.pins.addLayer(L.marker([n.lat, n.lon], { icon: pinIcon(`P${i + 1}`, SEV[p.severity].color, size, p.severity === 4), zIndexOffset: 800 })
      .bindTooltip(`P${i + 1} · ${p.location} · ${SEV[p.severity].label}`, { direction: "top", offset: [0, -size / 2] }));
  });
}

function drawRoutes() {
  layers.routes.clearLayers();
  stopAnim();
  const r = state.result;
  if (!r) return;
  const order = [["greedy", 4, 0.75, "8 8"], ["fastest", 4, 0.75, "2 8"], ["minnal", 7, 0.95, null]];
  const bounds = [];
  for (const [key, w, op, dash] of order) {
    const route = r.routes[key];
    if (!route) continue;
    const ll = route.path.map((p) => [p[0], p[1]]);
    bounds.push(...ll);
    if (key === "minnal") layers.routes.addLayer(L.polyline(ll, { color: "#fff", weight: w + 5, opacity: 0.9 }));
    layers.routes.addLayer(L.polyline(ll, { color: COL[key], weight: w, opacity: op, dashArray: dash, lineCap: "round" })
      .bindTooltip(NAMES[key], { sticky: true }));
  }
  if (bounds.length) map.flyToBounds(bounds, { padding: [40, 40], duration: 0.8 });
  $("play").disabled = !r.routes.minnal;
}

/* ---------------- ambulance animation ---------------- */
function stopAnim() {
  if (anim) cancelAnimationFrame(anim.raf);
  anim = null;
  if (ambMarker) { map.removeLayer(ambMarker); ambMarker = null; }
  $("play").textContent = "▶ Play ambulance";
  $("clock").textContent = "⏱ 0.0 min";
}

function play() {
  const route = state.result && state.result.routes.minnal;
  if (!route) return;
  if (anim) { stopAnim(); return; }
  const pts = route.path, total = pts[pts.length - 1][2], DURATION = 9000;
  ambMarker = L.marker([pts[0][0], pts[0][1]], {
    icon: L.divIcon({ className: "", html: '<div class="amb">🚑</div>', iconSize: [28, 28], iconAnchor: [14, 14] }),
    zIndexOffset: 1000,
  }).addTo(map);
  $("play").textContent = "■ Stop";
  const start = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - start) / DURATION) * total;
    let i = 1;
    while (i < pts.length - 1 && pts[i][2] < t) i++;
    const a = pts[i - 1], b = pts[i];
    const f = b[2] > a[2] ? (t - a[2]) / (b[2] - a[2]) : 1;
    ambMarker.setLatLng([a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])]);
    $("clock").textContent = `⏱ ${fmt(t)} min`;
    if (t < total) anim.raf = requestAnimationFrame(step);
    else { $("play").textContent = "↺ Replay"; anim = null; }
  };
  anim = { raf: requestAnimationFrame(step) };
}
$("play").addEventListener("click", play);

/* ---------------- controls ---------------- */
function seg(container, options, current, onPick, label = (x) => x) {
  const c = $(container); c.innerHTML = "";
  for (const o of options) {
    c.append(el("button", { class: o === current ? "on" : "", onclick: () => { onPick(o); seg(container, options, o, onPick, label); } }, label(o)));
  }
}

function renderPatients() {
  const box = $("patients"); box.innerHTML = "";
  const junctions = state.meta.nodes.filter((n) => n.kind === "junction").map((n) => n.name);
  state.patients.forEach((p, i) => {
    const sel = el("select", { "aria-label": `Patient ${i + 1} location`, onchange: (e) => {
      if (state.patients.some((q, j) => j !== i && q.location === e.target.value)) { toast("Another patient is already there."); e.target.value = p.location; return; }
      p.location = e.target.value; changed(); drawPins();
    } });
    for (const j of junctions) sel.append(el("option", j === p.location ? { selected: "" } : {}, j));
    const sev = el("div", { class: "sev" });
    for (const s of [1, 2, 3, 4]) {
      sev.append(el("button", {
        class: s === p.severity ? "on" : "", style: s === p.severity ? `background:${SEV[s].color}` : "",
        title: SEV[s].label, onclick: () => { p.severity = s; changed(); renderPatients(); drawPins(); },
      }, SEV[s].label));
    }
    box.append(el("div", { class: "patient" },
      el("div", { class: "num", style: `background:${SEV[p.severity].color}` }, `P${i + 1}`),
      sel,
      el("button", { class: "x", title: "Remove", onclick: () => {
        if (state.patients.length <= 2) { toast("Keep at least 2 patients."); return; }
        state.patients.splice(i, 1); changed(); renderPatients(); drawPins();
      } }, "×"),
      sev));
  });
  const n = state.patients.length;
  $("qubitHint").textContent = `· ${n * n} qubits`;
  $("chipQubits").textContent = `QAOA · ${n * n} qubits · p = ${state.reps}`;
  $("addPatient").disabled = n >= 4;
}

$("addPatient").addEventListener("click", () => {
  const free = state.meta.nodes.filter((x) => x.kind === "junction" && !state.patients.some((p) => p.location === x.name));
  if (state.patients.length >= 4 || !free.length) return;
  state.patients.push({ location: free[0].name, severity: 2 }); changed(); renderPatients(); drawPins();
});

function changed() {
  state.dirty = true;
  $("run").textContent = state.result ? "⚡ Re-optimize with QAOA" : "⚡ Optimize with QAOA";
}

function loadDemo() {
  state.slot = "Morning peak (9 AM)"; state.hospital = "Lakeshore Hospital"; state.lam = 2;
  state.patients = state.meta.demo["3"].map((p) => ({ ...p }));
  $("hospital").value = state.hospital; $("lam").value = 2; $("lamVal").textContent = "2.0";
  seg("slots", state.meta.slots, state.slot, (o) => { state.slot = o; changed(); });
  renderPatients(); drawPins(); changed();
}
$("demo").addEventListener("click", () => { loadDemo(); optimize(); });

$("lam").addEventListener("input", (e) => { state.lam = Number(e.target.value); $("lamVal").textContent = fmt(state.lam); changed(); });
$("hospital").addEventListener("change", (e) => { state.hospital = e.target.value; changed(); drawPins(); });
$("run").addEventListener("click", optimize);

/* ---------------- tabs ---------------- */
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
  document.querySelectorAll(".tabpane").forEach((p) => p.classList.toggle("active", p.id === t.dataset.tab));
}));

/* ---------------- API ---------------- */
async function optimize() {
  const n = state.patients.length;
  $("run").disabled = true;
  $("loadingText").textContent = `Training QAOA on ${n * n} qubits (AerSimulator)…`;
  $("loading").classList.remove("hidden");
  try {
    const res = await fetch("/api/optimize", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slot: state.slot, hospital: state.hospital, patients: state.patients,
                             lam: state.lam, reps: state.reps, objective: state.objective }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Request failed");
    state.result = data; state.dirty = false;
    drawRoutes(); renderResults(); renderQuantum(); renderRoutesTable(); renderEvidence();
    $("run").textContent = "⚡ Re-optimize with QAOA";
  } catch (e) {
    toast(`⚠️ ${e.message}`);
  } finally {
    $("run").disabled = false;
    $("loading").classList.add("hidden");
  }
}

/* ---------------- results ---------------- */
function stopsHtml(route) {
  const wrap = el("div", { class: "stops" }, el("span", { class: "stop" }, "🚑 Base"));
  for (const i of route.order) {
    const p = state.result.scenario.patients[i];
    wrap.append(el("span", { class: "arr" }, "→"),
      el("span", { class: "stop", style: `border-left:4px solid ${SEV[p.severity].color}` }, `P${i + 1} ${p.location}`));
  }
  wrap.append(el("span", { class: "arr" }, "→"), el("span", { class: "stop", style: "background:#ECFDF3" }, `🏥 ${state.result.scenario.hospital}`));
  return wrap;
}

function renderResults() {
  const r = state.result, g = r.routes.greedy, m = r.routes.minnal, q = r.quantum;
  $("emptyState").classList.add("hidden"); $("resultsBody").classList.remove("hidden");
  if (m) {
    const saved = g.critical - m.critical, extra = m.total - g.total;
    $("kCrit").textContent = `${fmt(m.critical)} min`;
    $("kCritS").textContent = `nearest-first: ${fmt(g.critical)} min`;
    $("kSaved").textContent = `${fmt(Math.max(saved, 0))} min`;
    $("kTotal").textContent = `${fmt(m.total)} min`;
    $("kTotalS").innerHTML = extra > 0.05 ? `<span class="bad">+${fmt(extra)} min</span> vs nearest-first`
      : `<span class="good">${fmt(extra)} min</span> vs nearest-first`;
    const b = $("banner");
    if (saved > 0.05) {
      b.innerHTML = `✅ <b>Minnal-Q reaches the critical patient ${fmt(saved)} minutes sooner</b> than nearest-first dispatch${extra > 0.05 ? `, for ${fmt(extra)} extra minutes of driving` : ", and drives less overall"}.`;
      b.classList.remove("hidden");
    } else {
      b.innerHTML = "ℹ️ Here the nearest-first route already reaches the critical patient first.";
      b.classList.remove("hidden");
    }
  }
  $("kAmp").textContent = `${Math.round(q.p_opt / q.random_p_opt)}×`;
  $("kAmpS").textContent = `P(optimal) ${(q.p_opt * 100).toFixed(2)}% · ${fmt(q.seconds)}s`;

  const cards = $("routeCards"); cards.innerHTML = "";
  for (const key of ["minnal", "greedy", "fastest"]) {
    const route = r.routes[key];
    if (!route) continue;
    cards.append(el("div", { class: "rcard", onclick: () => map.flyToBounds(route.path.map((p) => [p[0], p[1]]), { padding: [40, 40] }) },
      el("div", { class: "t", style: `color:${COL[key]}` }, el("i", { style: `background:${COL[key]}` }), NAMES[key]),
      stopsHtml(route),
      el("div", { class: "m" }, `Total ${fmt(route.total)} min · critical patient at ${fmt(route.critical)} min`)));
  }

  const tl = $("timeline"); tl.innerHTML = "";
  const maxT = Math.max(...["greedy", "fastest", "minnal"].filter((k) => r.routes[k]).map((k) => r.routes[k].total)) * 1.06;
  for (const key of ["minnal", "greedy", "fastest"]) {
    const route = r.routes[key];
    if (!route) continue;
    const track = el("div", { class: "tl-track" },
      el("div", { class: "tl-bar", style: `width:${(route.total / maxT) * 100}%;background:${COL[key]}` }));
    route.arrivals.forEach((t, i) => {
      const p = r.scenario.patients[i], s = 14 + p.severity * 3;
      track.append(el("div", { class: "tl-dot", title: `P${i + 1} ${p.label} @ ${p.location}: ${fmt(t)} min`,
        style: `left:${(t / maxT) * 100}%;width:${s}px;height:${s}px;background:${SEV[p.severity].color}` }, `${i + 1}`));
    });
    track.append(el("div", { class: "tl-end", style: `left:${(route.total / maxT) * 100}%`, title: `Hospital at ${fmt(route.total)} min` }, "🏥"));
    tl.append(el("div", { class: "tl-row" }, el("div", { class: "tl-name", style: `color:${COL[key]}` }, NAMES[key]), track));
  }
  tl.append(el("div", { class: "tl-axis" }, el("span", {}, "0 min"), el("span", {}, `${fmt(maxT / 2, 0)} min`), el("span", {}, `${fmt(maxT, 0)} min`)));
}

/* ---------------- charts ---------------- */
const charts = {};
Chart.defaults.font.family = "Inter, system-ui, sans-serif";
Chart.defaults.color = "#64748B";
function chart(id, cfg) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart($(id), cfg);
}

function renderQuantum() {
  const r = state.result, q = r.quantum, n = r.scenario.patients.length;
  $("qQubits").textContent = q.qubits;
  $("qPopt").textContent = `${(q.p_opt * 100).toFixed(2)}%`;
  $("qFeas").textContent = `${(q.feasible * 100).toFixed(1)}%`;
  $("qDepth").textContent = q.depth;

  const labels = ["Random guess", "QAOA p = 1"], vals = [q.random_p_opt, q.p_opt_p1], cols = ["#CBD5E1", "#A78BFA"];
  if (q.reps === 2) { labels.push("QAOA p = 2"); vals.push(q.p_opt); cols.push(COL.quantum); }
  chart("cProb", {
    type: "bar",
    data: { labels, datasets: [{ data: vals.map((v) => v * 100), backgroundColor: cols, borderRadius: 8 }] },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false },
      tooltip: { callbacks: { label: (c) => `${c.parsed.y.toFixed(3)}% chance of the optimal route` } } },
      scales: { y: { title: { display: true, text: "probability (%)" }, grid: { color: "#EEF2F7" } }, x: { grid: { display: false } } } },
  });

  const s = q.sampled.slice(0, 12);
  chart("cSampled", {
    type: "bar",
    data: { labels: s.map((d) => d.order.map((i) => `P${i + 1}`).join(" → ") + `  · ${fmt(d.cost, 0)}`),
            datasets: [{ data: s.map((d) => d.shots), backgroundColor: s.map((d) => (d.optimal ? COL.minnal : "#CBD5E1")), borderRadius: 6 }] },
    options: { indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false },
      tooltip: { callbacks: { label: (c) => `${c.parsed.x} shots${s[c.dataIndex].optimal ? " · optimal" : ""}` } } },
      scales: { x: { title: { display: true, text: "shots (of 4,096)" }, grid: { color: "#EEF2F7" } }, y: { grid: { display: false } } } },
  });

  chart("cTrain", {
    type: "line",
    data: { labels: q.history.map((_, i) => i + 1),
            datasets: [{ data: q.history, borderColor: COL.quantum, backgroundColor: "rgba(109,40,217,.08)", fill: true, pointRadius: 0, tension: 0.25, borderWidth: 2 }] },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false } },
      scales: { x: { title: { display: true, text: "optimizer step" }, ticks: { maxTicksLimit: 8 }, grid: { display: false } },
                y: { title: { display: true, text: `normalised ${q.objective}` }, grid: { color: "#EEF2F7" } } } },
  });

  const t = el("table", { class: "qgrid" });
  const head = el("tr", {}, el("th", {}, ""));
  for (let p = 0; p < n; p++) head.append(el("th", {}, `Stop ${p + 1}`));
  t.append(head);
  r.scenario.patients.forEach((pt, i) => {
    const tr = el("tr", {}, el("th", { style: "text-align:left" }, `P${i + 1} ${pt.label}`));
    for (let p = 0; p < n; p++) tr.append(el("td", { class: q.optimal_bits[i * n + p] ? "on" : "" }, `q${i * n + p}`));
    t.append(tr);
  });
  $("qgrid").replaceChildren(t);
  $("qMeta").textContent = `QAOA p = ${q.reps} · ${q.objective === "cvar" ? "CVaR (α = 0.2)" : "expectation"} · ${q.shots} shots · `
    + `${q.pauli_terms} Pauli terms · penalty A = ${q.penalty} · ${q.two_qubit_gates} two-qubit gates · ${fmt(q.seconds)}s`;
}

function renderRoutesTable() {
  const r = state.result, rows = r.all_routes, best = rows[0].cost;
  const tags = (o) => {
    const k = o.join(",");
    const out = [];
    if (Math.abs(rows.find((x) => x.order.join(",") === k).cost - best) < 1e-6) out.push(["🏆 optimum", "#FFF4EC", COL.minnal]);
    if (r.routes.minnal && r.routes.minnal.order.join(",") === k) out.push(["⚛️ QAOA", "#F5F0FF", COL.quantum]);
    if (r.routes.greedy.order.join(",") === k) out.push(["nearest-first", "#F1F5F9", "#475569"]);
    if (r.routes.fastest.order.join(",") === k) out.push(["fastest", "#EFF6FF", COL.fastest]);
    return out;
  };
  const t = $("routesTable"); t.innerHTML = "";
  t.append(el("tr", {}, el("th", {}, "Route"), el("th", {}, "Cost"), el("th", {}, "Total"), el("th", {}, "Critical")));
  for (const row of rows) {
    const tg = el("div", {});
    for (const [txt, bg, fg] of tags(row.order)) tg.append(el("span", { class: "badge", style: `background:${bg};color:${fg}` }, txt));
    t.append(el("tr", { class: Math.abs(row.cost - best) < 1e-6 ? "best" : "" },
      el("td", {}, row.order.map((i) => `P${i + 1}`).join(" → "), tg),
      el("td", {}, fmt(row.cost)), el("td", {}, `${fmt(row.total)}`), el("td", {}, `${fmt(row.critical)}`)));
  }
  $("routesHint").textContent = `All ${rows.length} possible visiting orders (n! = ${rows.length}), best first. `
    + "The exact optimum comes from brute force and is the answer key for QAOA. Times in minutes.";
}

function renderEvidence() {
  const box = $("checks"); box.innerHTML = "";
  for (const c of state.result.checks) box.append(el("div", { class: "check" }, `${c.ok ? "✅" : "❌"} ${c.name}`));
}

/* ---------------- boot ---------------- */
(async function boot() {
  try {
    state.meta = await (await fetch("/api/meta")).json();
  } catch (e) {
    toast("⚠️ Could not reach the Minnal-Q server."); return;
  }
  const hs = $("hospital");
  for (const n of state.meta.nodes.filter((x) => x.kind === "hospital")) hs.append(el("option", {}, n.name));
  seg("reps", [1, 2], state.reps, (o) => { state.reps = o; changed(); renderPatients(); }, (o) => `p = ${o}`);
  seg("objective", ["cvar", "expectation"], state.objective, (o) => { state.objective = o; changed(); },
      (o) => (o === "cvar" ? "CVaR α=0.2" : "Expectation"));
  drawNodes();
  loadDemo();
  optimize();
})();

/* ---------------- live SOS from phones (/sos) ---------------- */
const sosLayer = L.layerGroup().addTo(map);
let sosVersion = 0, sosBooted = false;

function renderSos(feed) {
  const box = $("sosFeed"), body = $("sosBody");
  const recs = (feed.records || []).slice().reverse();
  box.classList.toggle("hidden", recs.length === 0);
  body.innerHTML = "";
  sosLayer.clearLayers();
  for (const r of recs) {
    const sev = SEV[r.severity];
    body.append(el("div", { class: "sos-item" },
      el("div", {}, el("b", {}, `#${r.id} ${r.kind_label}`), ` · near ${r.junction}`),
      el("div", {}, el("span", { class: "eta" }, `${Math.round(r.eta)} min`), ` ETA · stop ${r.stop}/${r.stops} · `,
        el("b", { style: `color:${sev.color}` }, r.severity_label)),
      el("div", { class: "muted" }, `QAOA ${r.qubits} qubits · nearest-first ETA ${Math.round(r.eta_greedy)} min · GPS ${r.distance_km} km from junction`),
      el("ul", {}, ...r.log.slice(-3).map((l) => el("li", {}, l)))));
    L.marker([r.lat, r.lon], { icon: L.divIcon({ className: "", iconSize: [30, 30], iconAnchor: [15, 28], html: '<div class="phone-pin">📱</div>' }) })
      .bindTooltip(`SOS #${r.id}: ${r.kind_label} (phone GPS)`).addTo(sosLayer);
    const j = nodeByName(r.junction);
    if (j) L.polyline([[r.lat, r.lon], [j.lat, j.lon]], { color: "#D62828", dashArray: "4 6", weight: 2 }).addTo(sosLayer);
  }
}

async function pollSos() {
  if (!state.meta) { setTimeout(pollSos, 1000); return; }
  try {
    const res = await fetch(`/api/sos/feed?since=${sosVersion}`);
    const feed = await res.json();
    if (feed.changed) {
      const first = !sosBooted; sosVersion = feed.version; sosBooted = true;
      renderSos(feed);
      const a = feed.active;
      if (a && !first) {
        // show the dispatch board that QAOA solved for this SOS
        state.slot = a.result.scenario.slot; state.hospital = a.result.scenario.hospital;
        state.patients = a.patients.map((p) => ({ ...p }));
        $("hospital").value = state.hospital;
        seg("slots", state.meta.slots, state.slot, (o) => { state.slot = o; changed(); });
        state.result = a.result; state.dirty = false;
        renderPatients(); drawPins(); drawRoutes(); renderResults(); renderQuantum(); renderRoutesTable(); renderEvidence();
        $("run").textContent = "⚡ Re-optimize with QAOA";
        $("sosFeed").classList.remove("flash"); void $("sosFeed").offsetWidth; $("sosFeed").classList.add("flash");
        toast(`🆘 SOS #${a.id}: ${a.kind_label} near ${a.junction}. QAOA dispatch, ETA ${Math.round(a.eta)} min`);
      }
    }
  } catch (_) { /* server restarting; try again */ }
  setTimeout(pollSos, 2000);
}
$("sosReset").addEventListener("click", async () => { await fetch("/api/sos/reset", { method: "POST" }); });
setTimeout(pollSos, 1500);
