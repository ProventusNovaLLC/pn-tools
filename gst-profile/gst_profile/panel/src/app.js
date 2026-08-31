/* App chrome: mode bootstrap (report / live / replay), SSE wiring with resync,
   status strip, tabs, controls, the shared scrubber, and drag-drop replay. */
var GPApp = (function () {
  var es = null, activeTab = "pipeline";
  var scrubDrag = false;

  // ---- boot ----------------------------------------------------------------
  function boot() {
    GPTimeline.wire();
    wireChrome();
    GPStore.subscribe(onState);
    var hash = parseHash();
    if (hash.tab) showTab(hash.tab);
    if (hash.select) GPStore.select(hash.select);
    if (window.__SESSION__) {
      GPStore.applyStatus({ state: "report" });
      if (window.__VERDICT__) GPStore.applyFindings(window.__VERDICT__);
      GPStore.initSession(window.__SESSION__, "report");
    } else {
      connect(true);
    }
  }

  function parseHash() {
    var out = {};
    String(location.hash || "").replace(/^#/, "").split("&").forEach(function (kv) {
      var p = kv.split("=");
      if (p.length === 2) out[p[0]] = decodeURIComponent(p[1]);
    });
    return out;
  }

  function connect(first) {
    fetch("session.json").then(function (r) {
      if (!r.ok) throw new Error("http " + r.status);
      return r.json();
    }).then(function (session) {
      if (first) GPStore.initSession(session, "live");
      else GPStore.resync(session);
      stream();
    }).catch(function () {
      GPStore.applyStatus({ state: "disconnected" });
      setTimeout(function () { connect(GPStore.state.session === null); }, 2000);
    });
  }

  function stream() {
    if (es) es.close();
    es = new EventSource("events");
    es.addEventListener("graph", function (e) { GPStore.applyGraph(JSON.parse(e.data)); });
    es.addEventListener("tick", function (e) { GPStore.applyTick(JSON.parse(e.data)); });
    es.addEventListener("findings", function (e) { GPStore.applyFindings(JSON.parse(e.data)); });
    es.addEventListener("event", function (e) { GPStore.applyEvent(JSON.parse(e.data)); });
    es.addEventListener("status", function (e) { GPStore.applyStatus(JSON.parse(e.data)); });
    es.onerror = function () {
      var done = GPStore.state.status.state === "done";
      if (done) { if (es) { es.close(); es = null; } return; }
      GPStore.applyStatus({ state: "disconnected" });
      es.close(); es = null;
      setTimeout(function () { connect(false); }, 2000);   // resync from the snapshot, then re-stream
    };
  }

  // ---- chrome --------------------------------------------------------------
  function wireChrome() {
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (b) {
      b.addEventListener("click", function () { showTab(b.getAttribute("data-tab")); });
    });
    document.getElementById("btn-stop").addEventListener("click", function () {
      control({ action: "stop" });
    });
    document.getElementById("btn-mark").addEventListener("click", function () {
      control({ action: "mark", text: "mark from panel" });
    });
    document.getElementById("btn-save").addEventListener("click", saveSession);
    document.getElementById("btn-live").addEventListener("click", function () {
      GPStore.setCursor(-1, true);
    });
    wireScrubber();
    wireDrop();
  }

  function showTab(name) {
    activeTab = name;
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (b) {
      b.classList.toggle("active", b.getAttribute("data-tab") === name);
    });
    Array.prototype.forEach.call(document.querySelectorAll(".view"), function (v) {
      v.classList.toggle("active", v.id === "view-" + name);
    });
    onState(GPStore.state);
  }

  function control(payload) {
    fetch("control", { method: "POST", headers: { "Content-Type": "application/json" },
                       body: JSON.stringify(payload) }).catch(function () {});
  }

  function saveSession() {
    var state = GPStore.state;
    if (state.mode === "report" && window.__SESSION__) {
      download(JSON.stringify(window.__SESSION__));
      return;
    }
    if (state.mode === "replay" && state.session) {
      download(JSON.stringify(state.session));       // the dropped file is the session being viewed
      return;
    }
    fetch("session.json?redact=1").then(function (r) { return r.text(); }).then(download)
      .catch(function () { if (state.session) download(JSON.stringify(state.session)); });
  }

  function download(text) {
    var id = (GPStore.state.session && GPStore.state.session.session.id) || "session";
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    a.download = "gst-profile-" + id + ".json";
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 5000);
  }

  // ---- scrubber ------------------------------------------------------------
  function wireScrubber() {
    var canvas = document.getElementById("scrubcanvas");
    function toIndex(ev) {
      var st = GPStore.state;
      if (!st.session) return null;
      var n = st.session.series.t.length;
      if (n < 1) return null;
      var r = canvas.getBoundingClientRect();
      var frac = Math.max(0, Math.min(1, (ev.clientX - r.left) / Math.max(1, r.width)));
      return Math.round(frac * (n - 1));
    }
    canvas.addEventListener("mousedown", function (ev) {
      scrubDrag = true;
      var i = toIndex(ev);
      if (i !== null) GPStore.setCursor(i, false);
    });
    window.addEventListener("mousemove", function (ev) {
      if (!scrubDrag) return;
      var i = toIndex(ev);
      if (i !== null) GPStore.setCursor(i, false);
    });
    window.addEventListener("mouseup", function () { scrubDrag = false; });
  }

  function renderScrubber(state) {
    var canvas = document.getElementById("scrubcanvas");
    var d = GPDraw.setup(canvas), ctx = d.ctx;
    ctx.clearRect(0, 0, d.w, d.h);
    if (!state.session) return;
    var s = state.session.series, n = s.t.length;
    var p95 = s.pipeline.latency_ms_p95;
    var max = GPDraw.finiteMax(p95, 1e-9) * 1.15;      // headroom so a flat series reads as a line
    ctx.fillStyle = GPDraw.css("--surface2");
    ctx.fillRect(0, 0, d.w, d.h);
    if (GPStore.numeric(p95).length) GPDraw.line(ctx, p95, 0, 3, d.w, d.h - 6, max, GPDraw.css("--info"), true);
    (state.session.events || []).forEach(function (ev) {
      if (typeof ev.t !== "number" || n < 2) return;
      var px = (ev.t - s.t[0]) / (s.t[n - 1] - s.t[0] || 1) * d.w;
      ctx.fillStyle = GPDraw.css("--ink3");
      ctx.fillRect(px - 0.5, 0, 1, d.h);
    });
    GPDraw.cursor(ctx, GPStore.cursorIndex(), n, 0, 0, d.w, d.h, GPDraw.css("--ink"));
  }

  // ---- drag-drop replay ----------------------------------------------------
  function wireDrop() {
    document.body.addEventListener("dragover", function (ev) { ev.preventDefault(); });
    document.body.addEventListener("drop", function (ev) {
      ev.preventDefault();
      var f = ev.dataTransfer.files && ev.dataTransfer.files[0];
      if (!f) return;
      f.text().then(function (text) {
        var session = JSON.parse(text);
        if (es) { es.close(); es = null; }
        GPStore.applyStatus({ state: "replay" });
        GPStore.applyFindings(null);
        GPStore.initSession(session, "replay");
        GPStore.applyFindings(GPStore.deriveVerdict(GPStore.state.session));
      }).catch(function () {
        GPStore.applyStatus({ state: "not a session file" });
      });
    });
  }

  // ---- render --------------------------------------------------------------
  function onState(state) {
    renderStrip(state);
    renderVerdictLine(state);
    renderScrubber(state);
    if (state.session) {
      if (activeTab === "pipeline") { GPPipeline.render(state); GPInspector.render(state); }
      else if (activeTab === "timeline") GPTimeline.render(state);
      else if (activeTab === "system") GPSystem.render(state);
      else GPAnalysis.render(state);
    }
    renderLegend(state);
  }

  function renderStrip(state) {
    var st = state.status.state || "…";
    var dot = document.getElementById("statusdot");
    dot.className = "dot " + (st === "capturing" ? "capturing" : st === "disconnected" ? "err" : "done");
    document.getElementById("statustext").textContent = st;
    var s = state.session;
    var n = s ? s.series.t.length : 0;
    var elapsed = s && n ? s.series.t[n - 1] + (s.series.window_ms || 250) / 1000
                : (s && s.session.duration_s) || 0;
    document.getElementById("elapsed").textContent = n || s ? GPDraw.fmtClock(elapsed) : "";
    var tgt = (s && s.target) || {};
    var bits = [];
    if (tgt.gstreamer) bits.push("GStreamer " + tgt.gstreamer);
    if (tgt.board) bits.push(tgt.board);
    else if (tgt.platform && tgt.platform !== "generic") bits.push(tgt.platform);
    document.getElementById("targetinfo").textContent = bits.join(" · ");
    var parse = (s && s.session.parse) || {};
    var bad = (parse.unparsed || 0) + (parse.errors || 0);
    document.getElementById("parseinfo").textContent = bad > 0 ? bad + " unparsed lines" : "";
    var liveCapture = st === "capturing";
    document.getElementById("btn-stop").hidden = !liveCapture;
    document.getElementById("btn-mark").hidden = !liveCapture;
    var liveBtn = document.getElementById("btn-live");
    liveBtn.classList.toggle("on", state.cursor.live);
    liveBtn.textContent = liveCapture ? "LIVE" : "END";
    var i = GPStore.cursorIndex();
    document.getElementById("scrubtime").textContent =
      s && i >= 0 ? "t = " + GPDraw.fmt(s.series.t[i], " s") : "";
  }

  function renderVerdictLine(state) {
    var el = document.getElementById("verdictline");
    var v = state.verdict;
    if (!v) { el.textContent = "waiting for the first verdict…"; return; }
    el.replaceChildren();
    var b = document.createElement("b");
    var top = (v.findings || []).filter(function (f) { return f.rule !== "HOT" && f.rule !== "OK"; })[0];
    b.textContent = top ? "top finding: " + top.rule + " · " + top.title : "";
    el.appendChild(document.createTextNode(v.header + (top ? "   ·   " : "")));
    el.appendChild(b);
    var badge = document.querySelector('[data-tab="analysis"] .badge');
    var nf = (v.findings || []).filter(function (f) { return f.rule !== "HOT" && f.rule !== "OK"; }).length;
    var tab = document.querySelector('[data-tab="analysis"]');
    tab.replaceChildren(document.createTextNode("Analysis" + (nf ? " " : "")));
    if (nf) { var sp = document.createElement("span"); sp.className = "badge"; sp.textContent = String(nf); tab.appendChild(sp); }
  }

  function renderLegend(state) {
    var el = document.getElementById("legend");
    if (activeTab !== "pipeline") { el.textContent = ""; return; }
    el.replaceChildren();
    [["--nvmm", "NVMM (hardware memory)"], ["--dmabuf", "dmabuf"], ["--sysmem", "system memory"],
     ["--unknown", "unknown (dashed)"]].forEach(function (pair) {
      var sw = document.createElement("span");
      sw.className = "sw"; sw.style.background = GPDraw.css(pair[0]);
      el.appendChild(sw);
      el.appendChild(document.createTextNode(pair[1]));
    });
    el.appendChild(document.createTextNode("  ·  a gray gap in a green path is a copy; edge width = bytes/s, dash speed = fps"));
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  return { showTab: showTab };
})();
