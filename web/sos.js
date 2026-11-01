/* Minnal-Q SOS phone app (prototype): GPS -> /api/sos -> QAOA dispatch -> simulated automated call. */
const API_HEADERS = { "Content-Type": "application/json", "ngrok-skip-browser-warning": "1" };
const KINDS = [
  ["cardiac", "❤️", "Chest pain"], ["breathing", "🫁", "Breathing"], ["unconscious", "😵", "Unconscious"],
  ["accident", "🚗", "Accident"], ["injury", "🦴", "Fall / injury"], ["other", "➕", "Other"],
];
const DEMO_LOC = { lat: 9.9970, lon: 76.2990, accuracy: 0, demo: true }; // Kaloor, used only if GPS is unavailable

const $ = (id) => document.getElementById(id);

/* ---------------- vitals from JeevaFlow (/static/jeeva) ---------------- */
const SEV_NAME = { 1: "Minor", 2: "Moderate", 3: "Serious", 4: "Critical" };
const VITALS = (() => {
  try { const v = JSON.parse(localStorage.getItem("minnalVitals") || "null"); return v && Date.now() - v.at < 30 * 60e3 ? v : {}; }
  catch (_) { return {}; }
})();
function renderVitals() {
  if (!VITALS.summary) return;
  $("vitalsHead").textContent = VITALS.severity ? `Vitals: ${SEV_NAME[VITALS.severity]}` : "Vitals: no danger signs";
  $("vitalsTxt").textContent = VITALS.summary + (VITALS.severity ? " · sent with your SOS" : "");
  const e = $("vitalsSev"); e.textContent = VITALS.severity ? SEV_NAME[VITALS.severity] : "OK";
  $("vitals").classList.add("has", "s" + (VITALS.severity || 0));
}
const st = { kind: "cardiac", pos: null, rec: null, callStart: 0, timer: null, ring: null, ended: false, keyWaiter: null };

function show(id) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.toggle("active", s.id === id));
}
function toast(msg, ms = 3000) {
  const t = $("toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}
const APP = window.MinnalApp || null;  // present inside the Android app: native ringtone, voice, vibration
const buzz = (p) => {
  if (APP) { try { APP.vibrateMs(Array.isArray(p) ? p[0] : p); } catch (_) {} return; }
  try { navigator.vibrate && navigator.vibrate(p); } catch (_) {}
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ---------------- emergency type ---------------- */
function renderKinds() {
  const box = $("kinds"); box.innerHTML = "";
  for (const [k, e, label] of KINDS) {
    const b = document.createElement("button");
    b.className = "kind" + (k === st.kind ? " on" : "");
    b.innerHTML = `<span class="e">${e}</span>${label}`;
    b.onclick = () => { st.kind = k; renderKinds(); };
    box.append(b);
  }
}

/* ---------------- GPS ---------------- */
function setGps(text, cls) { const g = $("gps"); g.textContent = text; g.className = "gps " + cls; }
// The Android app (android/) reads GPS natively and calls this, so GPS works even over plain http.
window.minnalNativeLocation = (lat, lon, acc) => {
  st.pos = { lat, lon, accuracy: Math.round(acc) };
  setGps(`📍 GPS ±${st.pos.accuracy} m (app)`, "ok");
};
function startGps() {
  if (window.MinnalApp) { setGps("📍 Finding GPS (app)…", ""); return; }
  if (!window.isSecureContext) { gpsFallback("Needs HTTPS link for GPS"); return; }
  if (!navigator.geolocation) { gpsFallback("GPS not supported"); return; }
  navigator.geolocation.watchPosition(
    (p) => {
      st.pos = { lat: p.coords.latitude, lon: p.coords.longitude, accuracy: Math.round(p.coords.accuracy) };
      setGps(`📍 GPS ±${st.pos.accuracy} m`, "ok");
    },
    (e) => gpsFallback(e.code === 1 ? "Location permission denied" : "GPS unavailable"),
    { enableHighAccuracy: true, maximumAge: 10000, timeout: 20000 },
  );
}
function gpsFallback(why) {
  if (st.pos && !st.pos.demo) return;
  st.pos = { ...DEMO_LOC };
  setGps(`⚠️ ${why}: demo location (Kaloor)`, "bad");
}

/* ---------------- audio: ringtone + speech ---------------- */
let actx = null;
function unlockAudio() {
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    actx.resume();
  } catch (_) {}
  if ("speechSynthesis" in window) {  // iOS: speech must first be triggered inside a tap
    const u = new SpeechSynthesisUtterance(" "); u.volume = 0; speechSynthesis.speak(u);
  }
}
function startRing() {
  stopRing();
  if (APP) { APP.ring(true); st.ring = -1; return; }
  const beep = () => {
    if (!actx) return;
    const t = actx.currentTime;
    for (const [f, off] of [[440, 0], [480, 0]]) {
      const o = actx.createOscillator(), g = actx.createGain();
      o.frequency.value = f; o.connect(g); g.connect(actx.destination);
      g.gain.setValueAtTime(0.0001, t + off); g.gain.exponentialRampToValueAtTime(0.15, t + 0.05);
      g.gain.setValueAtTime(0.15, t + 1.6); g.gain.exponentialRampToValueAtTime(0.0001, t + 1.8);
      o.start(t + off); o.stop(t + 1.85);
    }
    buzz([800, 400, 800]);
  };
  beep(); st.ring = setInterval(beep, 3000);
}
function stopRing() { if (APP) APP.ring(false); clearInterval(st.ring); st.ring = null; buzz(0); }
const speechWaiters = {};
window.minnalSpeechDone = (id) => { const f = speechWaiters[id]; if (f) { delete speechWaiters[id]; f(); } };

function pickVoice() {
  const vs = ("speechSynthesis" in window) ? speechSynthesis.getVoices() : [];
  return vs.find((v) => v.lang === "en-IN") || vs.find((v) => v.lang.startsWith("en-GB")) || vs.find((v) => v.lang.startsWith("en"));
}
function say(html) {
  $("caption").innerHTML = html;
  const text = html.replace(/<[^>]+>/g, "");
  if (st.ended) return Promise.resolve();
  if (APP) {
    return new Promise((resolve) => {
      const id = "u" + Date.now() + Math.random().toString(36).slice(2, 6);
      let done = false; const fin = () => { if (!done) { done = true; delete speechWaiters[id]; resolve(); } };
      speechWaiters[id] = fin;
      setTimeout(fin, 2500 + text.length * 90); // safety net
      if (!APP.speak(id, text)) setTimeout(fin, 1200 + text.length * 45);
    });
  }
  if (!("speechSynthesis" in window)) return sleep(1200 + text.length * 45);
  return new Promise((resolve) => {
    const u = new SpeechSynthesisUtterance(text);
    const v = pickVoice(); if (v) u.voice = v;
    u.rate = 0.98;
    let done = false; const fin = () => { if (!done) { done = true; resolve(); } };
    u.onend = fin; u.onerror = fin;
    setTimeout(fin, 2500 + text.length * 90); // safety net if onend never fires
    speechSynthesis.speak(u);
  });
}
function waitKey(allowed) {
  $("keypad").classList.remove("wait");
  return new Promise((resolve) => { st.keyWaiter = { allowed, resolve }; });
}
document.querySelectorAll("#keypad button").forEach((b) => b.addEventListener("click", () => {
  buzz(30);
  const k = b.dataset.k;
  if (st.keyWaiter && st.keyWaiter.allowed.includes(k)) {
    const w = st.keyWaiter; st.keyWaiter = null; $("keypad").classList.add("wait"); w.resolve(k);
  }
}));

/* ---------------- SOS hold button ---------------- */
(function holdButton() {
  const btn = $("sosBtn"); let t = null;
  const cancel = () => { clearTimeout(t); t = null; btn.classList.remove("holding"); };
  btn.addEventListener("pointerdown", (e) => {
    e.preventDefault(); unlockAudio(); buzz(40);
    btn.classList.add("holding");
    t = setTimeout(() => { cancel(); sendSOS(); }, 1500);
  });
  ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => btn.addEventListener(ev, () => { if (t) { cancel(); toast("Hold for 1.5 seconds to send SOS"); } }));
  btn.addEventListener("contextmenu", (e) => e.preventDefault());
})();

function step(k, cls) { const li = document.querySelector(`#steps li[data-k="${k}"]`); if (li) li.className = cls; }

async function sendSOS() {
  buzz([100, 60, 100]);
  if (!st.pos) gpsFallback("GPS not ready");
  document.querySelectorAll("#steps li").forEach((li) => (li.className = ""));
  show("busy"); step("loc", "run");
  try {
    const req = fetch("/api/sos", {
      method: "POST", headers: API_HEADERS,
      body: JSON.stringify({ lat: st.pos.lat, lon: st.pos.lon, accuracy: st.pos.accuracy, kind: st.kind,
                             severity: VITALS.severity || null,
                             note: [st.pos.demo ? "demo location (GPS unavailable)" : "", VITALS.summary ? `vitals: ${VITALS.summary}` : ""].filter(Boolean).join("; ").slice(0, 200) }),
    });
    await sleep(500); step("loc", "done"); step("snap", "run");
    await sleep(500); step("snap", "done"); step("qaoa", "run");
    const res = await req; const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "SOS failed");
    st.rec = data;
    step("qaoa", "done"); step("call", "run");
    await sleep(700);
    st.ended = false; show("incoming"); startRing();
  } catch (e) {
    show("home"); toast("⚠️ " + e.message + ". Check the server link.", 5000);
  }
}

/* ---------------- automated call ---------------- */
$("decline").onclick = () => { stopRing(); renderStatus(); show("status"); toast("Call declined. Your SOS is still active."); };
$("hangup").onclick = endCall;
$("accept").onclick = () => {
  stopRing(); show("incall");
  st.callStart = Date.now();
  st.timer = setInterval(() => {
    const s = Math.floor((Date.now() - st.callStart) / 1000);
    $("timer").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }, 500);
  $("keypad").classList.add("wait");
  runCall(true);
};

function endCall() {
  st.ended = true;
  if (APP) APP.stopSpeech();
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  clearInterval(st.timer); stopRing();
  if (st.keyWaiter) { st.keyWaiter.resolve(null); st.keyWaiter = null; }
  renderStatus(); show("status");
}

async function ask(question) {
  for (;;) {
    await say(question);
    if (st.ended) return null;
    const k = await waitKey(["1", "2", "9"]);
    if (k !== "9") return k;
  }
}

async function runCall(withTriage) {
  const r = st.rec;
  await say(`Hello. This is the <b>Minnal-Q</b> automated emergency dispatch. We received your SOS for
    <b>${r.kind_label}</b> near <b>${r.junction}</b>.`);
  if (r.outside_area) await say(`Your GPS is ${r.distance_km} kilometres from the Kochi demo map, so we mapped you to ${r.junction}.`);
  await say(`Our quantum engine ran QAOA on <b>${r.qubits} qubits</b>. An ambulance from Kalamassery is on the way.
    Estimated arrival: <b>${Math.round(r.eta)} minutes</b>. You are stop ${r.stop} of ${r.stops}.`);
  if (st.ended) return;
  if (withTriage) {
    const c = await ask("Is the patient <b>conscious</b>? Press <b>1</b> for yes, <b>2</b> for no. Press 9 to repeat.");
    if (c === null) return;
    const b = await ask("Is the patient <b>breathing normally</b>? Press <b>1</b> for yes, <b>2</b> for no.");
    if (b === null) return;
    await say("Thank you. Updating your priority…");
    try {
      const res = await fetch(`/api/sos/${r.id}/triage`, { method: "POST", headers: API_HEADERS,
        body: JSON.stringify({ conscious: c === "1", breathing: b === "1" }) });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || "triage failed");
      st.rec = d;
      if (d.severity_changed) {
        await say(`Severity changed to <b>${d.severity_label}</b>. Minnal-Q re-optimised the route with QAOA.
          New arrival time: <b>${Math.round(d.eta)} minutes</b>. You are now stop ${d.stop} of ${d.stops}.`);
      } else {
        await say(`Severity confirmed as <b>${d.severity_label}</b>. Arrival time stays at <b>${Math.round(d.eta)} minutes</b>.`);
      }
    } catch (e) {
      await say("Sorry, the priority update failed. Your ambulance is still on the way.");
    }
  }
  if (st.ended) return;
  await say("Stay with the patient and keep this phone nearby. If the condition gets worse, call 112. Goodbye.");
  endCall();
}

/* ---------------- status ---------------- */
function renderStatus() {
  const r = st.rec; if (!r) return;
  $("sid").textContent = `SOS #${r.id} · ${r.status}`;
  $("eta").textContent = Math.round(r.eta);
  $("etaSub").textContent = r.eta_greedy > r.eta
    ? `Nearest-first dispatch would take ${Math.round(r.eta_greedy)} min (${Math.round(r.eta_greedy - r.eta)} min slower)`
    : `Nearest-first dispatch: ${Math.round(r.eta_greedy)} min`;
  $("sLoc").textContent = r.junction + (r.outside_area ? " (mapped)" : "");
  $("sSev").textContent = r.severity_label;
  $("sStop").textContent = `${r.stop} of ${r.stops}`;
  $("sQ").textContent = `${r.qubits} qubits · ${r.optimal ? "optimal" : "near-opt"}`;
  $("sRoute").textContent = "Route: " + r.route;
  $("sLog").innerHTML = r.log.map((l) => `<li>${l}</li>`).join("");
}
$("replay").onclick = () => {
  unlockAudio(); st.ended = false; show("incall"); st.callStart = Date.now();
  clearInterval(st.timer);
  st.timer = setInterval(() => {
    const s = Math.floor((Date.now() - st.callStart) / 1000);
    $("timer").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }, 500);
  $("keypad").classList.add("wait");
  runCall(false);
};
$("again").onclick = () => show("home");

/* ---------------- boot ---------------- */
renderKinds();
startGps();
if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = () => pickVoice();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
renderVitals();
