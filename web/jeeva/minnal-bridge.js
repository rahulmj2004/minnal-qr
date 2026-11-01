/* Minnal-Q bridge for JeevaFlow Pulse Check.
   JeevaFlow measures vitals on the phone; this turns its results into a Minnal-Q severity (1-4),
   saves them for the SOS screen (same origin, localStorage) and shows a "send to SOS" bar. */
(function () {
  const KEY = "minnalVitals";
  const SEV = { 1: "Minor", 2: "Moderate", 3: "Serious", 4: "Critical" };

  function load() {
    try { const v = JSON.parse(localStorage.getItem(KEY) || "null"); return v && Date.now() - v.at < 30 * 60e3 ? v : {}; }
    catch (_) { return {}; }
  }

  /** Severity rules (provisional, for triage hints only). */
  function grade(v) {
    const why = [];
    let sev = 0;
    if (v.strokeSigns > 0) { sev = 4; why.push(`stroke signs ${v.strokeSigns}/3`); }
    if (v.rhythm === "irregular") { sev = Math.max(sev, 3); why.push("irregular rhythm (possible AFib)"); }
    if (v.hr != null) {
      if (v.hr > 130 || v.hr < 40) { sev = Math.max(sev, 3); why.push(`heart rate ${v.hr} bpm`); }
      else if (v.hr > 110 || v.hr < 50) { sev = Math.max(sev, 2); why.push(`heart rate ${v.hr} bpm`); }
    }
    return { severity: sev || null, why };
  }

  function summary(v) {
    const parts = [];
    if (v.hr != null) parts.push(`❤ ${v.hr} bpm`);
    if (v.rhythm) parts.push(v.rhythm === "irregular" ? "Irregular rhythm" : v.rhythm === "regular" ? "Regular rhythm" : `Rhythm: ${v.rhythm}`);
    if (v.strokeSigns != null) parts.push(v.strokeSigns ? `Stroke signs ${v.strokeSigns}/3` : "No stroke signs");
    return parts.join(" · ");
  }

  window.minnalReport = function (patch) {
    const v = Object.assign(load(), patch, { at: Date.now() });
    const g = grade(v);
    v.severity = g.severity; v.why = g.why; v.summary = summary(v);
    try { localStorage.setItem(KEY, JSON.stringify(v)); } catch (_) {}
    render(v);
  };

  const css = `
  .mq-top{position:sticky;top:0;z-index:50;display:flex;align-items:center;justify-content:space-between;gap:10px;
    padding:10px 14px;background:linear-gradient(90deg,#0B0F1A,#1B1238);color:#fff;font:600 14px/1.2 -apple-system,Segoe UI,Roboto,sans-serif;
    box-shadow:0 6px 20px rgba(0,0,0,.25)}
  .mq-top a{color:#fff;text-decoration:none;padding:7px 12px;border-radius:999px;background:rgba(255,255,255,.12);font-size:13px;white-space:nowrap}
  .mq-top .mq-b{display:inline-grid;place-items:center;width:26px;height:26px;border-radius:8px;margin-right:6px;
    background:linear-gradient(135deg,#FFD166,#FB8500);color:#1a1000}
  .mq-top small{display:block;font-weight:500;opacity:.7;font-size:11px}
  .mq-bar{position:fixed;left:12px;right:12px;bottom:calc(12px + env(safe-area-inset-bottom));z-index:60;display:none;
    align-items:center;gap:12px;padding:12px 14px;border-radius:18px;color:#fff;
    background:rgba(11,15,26,.94);border:1px solid rgba(255,255,255,.12);box-shadow:0 14px 40px rgba(0,0,0,.45);
    font:500 13px/1.3 -apple-system,Segoe UI,Roboto,sans-serif;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
  .mq-bar.show{display:flex}
  .mq-bar .mq-s{font-weight:800;font-size:12px;padding:4px 9px;border-radius:8px;white-space:nowrap}
  .mq-bar .mq-txt{flex:1;min-width:0}
  .mq-bar a{color:#fff;text-decoration:none;font-weight:800;padding:10px 14px;border-radius:12px;white-space:nowrap;
    background:linear-gradient(135deg,#FF5468,#B0102A);box-shadow:0 6px 18px rgba(240,35,59,.45)}`;
  const COLORS = { 1: "#22C55E", 2: "#F59E0B", 3: "#F97316", 4: "#F0233B" };

  let bar;
  function render(v) {
    if (!bar || !v.summary) return;
    const s = v.severity;
    bar.innerHTML = "";
    const tag = document.createElement("span"); tag.className = "mq-s";
    tag.textContent = s ? SEV[s] : "Normal"; tag.style.background = s ? COLORS[s] : "#334155";
    const txt = document.createElement("div"); txt.className = "mq-txt";
    txt.textContent = v.summary + (s ? " → sets SOS severity" : "");
    const go = document.createElement("a"); go.href = "/sos"; go.textContent = "Use in SOS ⚡";
    bar.append(tag, txt, go); bar.classList.add("show");
  }

  document.addEventListener("DOMContentLoaded", () => {
    const st = document.createElement("style"); st.textContent = css; document.head.append(st);
    const top = document.createElement("div"); top.className = "mq-top";
    top.innerHTML = '<div><span class="mq-b">⚡</span>Minnal-Q · Check vitals<small>Powered by JeevaFlow Pulse Check · results set your SOS severity</small></div><a href="/sos">← SOS</a>';
    document.body.prepend(top);
    bar = document.createElement("div"); bar.className = "mq-bar"; document.body.append(bar);
    render(load());
  });
})();
