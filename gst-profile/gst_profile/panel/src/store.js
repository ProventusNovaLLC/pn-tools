/* Session store: one client-side copy of the gst-profile/1 session document, built
   from an embedded session (report), a fetched snapshot (live/replay) and SSE frames.
   Pure data: no DOM. Views subscribe and re-read on notify. */
var GPStore = (function () {
  var ELEMENT_COLS = ["proc_ms_p50", "proc_ms_p95", "cpu_pct", "queue_level", "buffers"];
  var LINK_COLS = ["fps", "bytes_s", "stalled"];
  var PIPELINE_COLS = ["latency_ms_p50", "latency_ms_p95", "reported_latency_ms"];
  var SYSTEM_COLS = ["cpu_pct_per_core", "cpu_pct", "gr3d_pct", "vic_pct", "nvenc_pct", "nvdec_pct", "emc_pct"];

  var state = {
    session: null,          // the session dict (schema gst-profile/1)
    verdict: null,          // latest findings frame (verdict.to_dict shape)
    status: { state: "connecting" },
    cursor: { index: -1, live: true },   // index into series.t; live pins to the newest window
    mode: "live",           // live | replay | report
    selected: null,         // selected element id (inspector)
    focusFinding: null      // finding id highlighted on the pipeline tab
  };
  var listeners = [];

  function emptySeries() {
    return { window_ms: 250, t: [], elements: {}, links: {},
             pipeline: { latency_ms_p50: [], latency_ms_p95: [], reported_latency_ms: [] },
             system: { cpu_pct_per_core: [], cpu_pct: [], gr3d_pct: [], vic_pct: [], nvenc_pct: [], nvdec_pct: [], emc_pct: [] } };
  }

  function normalize(session) {
    session = session || {};
    if (!session.series || !session.series.t) session.series = emptySeries();
    var s = session.series;
    s.elements = s.elements || {}; s.links = s.links || {};
    s.pipeline = s.pipeline || {}; s.system = s.system || {};
    PIPELINE_COLS.forEach(function (c) { s.pipeline[c] = s.pipeline[c] || []; });
    SYSTEM_COLS.forEach(function (c) { s.system[c] = s.system[c] || []; });
    if (!session.graph) session.graph = { pipeline: "", elements: [], links: [] };
    session.events = session.events || [];
    session.findings = session.findings || [];
    session.target = session.target || {};
    session.session = session.session || {};
    return session;
  }

  function rows() { return state.session ? state.session.series.t.length : 0; }

  function cursorIndex() {
    var n = rows();
    if (!n) return -1;
    if (state.cursor.live || state.cursor.index < 0) return n - 1;
    return Math.min(state.cursor.index, n - 1);
  }

  /* Backfill a per-key column set to `upto` values, so a key that appears
     mid-capture gets nulls for the windows before it existed. */
  function pad(colsObj, colNames, upto) {
    colNames.forEach(function (c) {
      colsObj[c] = colsObj[c] || [];
      while (colsObj[c].length < upto) colsObj[c].push(null);
    });
  }

  function initSession(sessionDict, mode) {
    state.session = normalize(sessionDict);
    if (mode) state.mode = mode;
    if (state.session.findings.length && !state.verdict) state.verdict = deriveVerdict(state.session);
    notify();
  }

  function applyGraph(graphDict) {
    if (!state.session) state.session = normalize({});
    state.session.graph = graphDict;
    notify();
  }

  /* tick = {t, rows, row:{elements:{}, links:{}, pipeline:{}, system:{}}}, append one window.
     Frames older than what we already hold (reconnect replays) are dropped. */
  function applyTick(tick) {
    if (!state.session) state.session = normalize({});
    var s = state.session.series, t = s.t;
    if (typeof tick.t !== "number" || !tick.row) return false;
    if (t.length && tick.t <= t[t.length - 1]) return false;
    var n = t.length;
    t.push(tick.t);
    var rowEls = tick.row.elements || {};
    Object.keys(rowEls).forEach(function (el) {
      s.elements[el] = s.elements[el] || {};
      pad(s.elements[el], ELEMENT_COLS, n);
    });
    Object.keys(s.elements).forEach(function (el) {
      var src = rowEls[el] || {};
      ELEMENT_COLS.forEach(function (c) { s.elements[el][c].push(src[c] !== undefined ? src[c] : null); });
    });
    var rowLinks = tick.row.links || {};
    Object.keys(rowLinks).forEach(function (l) {
      s.links[l] = s.links[l] || {};
      pad(s.links[l], LINK_COLS, n);
    });
    Object.keys(s.links).forEach(function (l) {
      var src = rowLinks[l] || {};
      LINK_COLS.forEach(function (c) { s.links[l][c].push(src[c] !== undefined ? src[c] : null); });
    });
    var rp = tick.row.pipeline || {};
    PIPELINE_COLS.forEach(function (c) { s.pipeline[c].push(rp[c] !== undefined ? rp[c] : null); });
    var rs = tick.row.system || {};
    SYSTEM_COLS.forEach(function (c) { s.system[c].push(rs[c] !== undefined ? rs[c] : null); });
    notify();
    return true;
  }

  function applyFindings(payload) { state.verdict = payload; notify(); }

  function applyEvent(ev) {
    if (!state.session) state.session = normalize({});
    state.session.events.push(ev);
    notify();
  }

  function applyStatus(st) { state.status = st || state.status; notify(); }

  /* Replace the whole session from a fresh /session.json (SSE reconnect). */
  function resync(sessionDict) {
    var live = state.cursor.live, idx = state.cursor.index;
    state.session = normalize(sessionDict);
    state.cursor = { index: Math.min(idx, rows() - 1), live: live };
    notify();
  }

  function setCursor(index, live) {
    state.cursor = { index: index, live: !!live };
    notify();
  }
  function select(elementId) { state.selected = elementId; notify(); }
  function focusFinding(id) { state.focusFinding = id; notify(); }

  /* A dropped session file has findings but no verdict frame: rebuild the header
     and hot list from the series (mirror of the Python verdict, good enough for replay). */
  function deriveVerdict(session) {
    var s = session.series, findings = session.findings || [];
    var p95 = numeric(s.pipeline.latency_ms_p95), lat = p95.length ? percentile(p95, 0.95) : null;
    var per = {}, total = 0;
    Object.keys(s.elements).forEach(function (el) {
      var v = numeric(s.elements[el].proc_ms_p95);
      if (!v.length) return;
      var m = v.reduce(function (a, b) { return a + b; }, 0) / v.length;
      per[el] = m; total += m;
    });
    var hot = Object.keys(per).map(function (el) {
      return { element: el, proc_ms_p95: per[el], share_pct: total ? 100 * per[el] / total : 0 };
    }).sort(function (a, b) { return b.share_pct - a.share_pct; }).slice(0, 8);
    var head = [];
    if (lat !== null) head.push("pipeline latency p95 " + lat.toFixed(1) + " ms");
    if (hot.length) head.push("where the time goes: " + hot.slice(0, 3).map(function (h) {
      return h.element + " " + h.share_pct.toFixed(0) + "%"; }).join(" · "));
    return { header: head.join("  ·  ") || "no per-element timing on this capture",
             latency_ms_p95: lat, frame_period_ms: null, hot: hot, findings: findings,
             has_high_or_medium: findings.some(function (f) { return f.severity === "high" || f.severity === "medium"; }) };
  }

  function numeric(arr) { return (arr || []).filter(function (v) { return typeof v === "number"; }); }
  function percentile(vals, p) {
    var v = vals.slice().sort(function (a, b) { return a - b; });
    return v[Math.max(0, Math.min(v.length - 1, Math.round(p * (v.length - 1))))];
  }

  function subscribe(fn) { listeners.push(fn); }
  var scheduled = false;
  function notify() {
    if (scheduled) return;
    scheduled = true;
    var flush = function () { scheduled = false; listeners.forEach(function (fn) { fn(state); }); };
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(flush); else flush();
  }

  return { state: state, initSession: initSession, applyGraph: applyGraph, applyTick: applyTick,
           applyFindings: applyFindings, applyEvent: applyEvent, applyStatus: applyStatus,
           resync: resync, setCursor: setCursor, cursorIndex: cursorIndex, select: select,
           focusFinding: focusFinding, deriveVerdict: deriveVerdict, rows: rows,
           numeric: numeric, percentile: percentile, subscribe: subscribe };
})();
if (typeof module !== "undefined") module.exports = GPStore;
