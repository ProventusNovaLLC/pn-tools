/* Timeline tab: stacked lanes on the shared time axis — pipeline latency band first,
   then element proc-time lanes hottest-first (toggleable), then link fps lanes.
   Crosshair hover reads every lane at that instant; events are vertical markers. */
var GPTimeline = (function () {
  var LANE_H = 34, GUTTER = 170, PAD_T = 6, HEADROOM = 1.18;
  var hidden = {};                       // element/link id -> user toggled off
  var hover = null;                      // hovered series index

  function lanes(state) {
    var s = state.session.series, out = [];
    if (GPStore.numeric(s.pipeline.latency_ms_p95).length) {
      out.push({ kind: "band", label: "pipeline latency", lo: s.pipeline.latency_ms_p50,
                 hi: s.pipeline.latency_ms_p95, unit: " ms", color: "--info" });
    }
    var els = Object.keys(s.elements).map(function (id) {
      var v = GPStore.numeric(s.elements[id].proc_ms_p95 || []);
      return { id: id, mean: v.length ? v.reduce(function (a, b) { return a + b; }, 0) / v.length : -1 };
    }).filter(function (e) { return e.mean >= 0; }).sort(function (a, b) { return b.mean - a.mean; });
    els.forEach(function (e) {
      if (hidden[e.id]) return;
      out.push({ kind: "line", label: e.id, vals: state.session.series.elements[e.id].proc_ms_p95,
                 unit: " ms", color: "--medium", id: e.id });
    });
    Object.keys(s.links).sort().forEach(function (id) {
      if (hidden[id]) return;
      var v = s.links[id];
      if (!GPStore.numeric(v.fps || []).length) return;
      out.push({ kind: "line", label: shortLink(id), vals: v.fps, unit: " fps",
                 color: "--info", id: id, stalled: v.stalled });
    });
    return out;
  }

  function shortLink(id) {
    var m = id.split("->");
    return m.length === 2 ? m[0].split(":")[0] + " → " + m[1].split(":")[0] : id;
  }

  function chips(state) {
    var host = document.getElementById("tl-toggles");
    var s = state.session.series;
    var ids = Object.keys(s.elements).filter(function (id) {
      return GPStore.numeric(s.elements[id].proc_ms_p95 || []).length;
    });
    var key = ids.join("|");
    if (host.getAttribute("data-key") === key) {
      Array.prototype.forEach.call(host.children, function (b) {
        b.classList.toggle("on", !hidden[b.getAttribute("data-id")]);
      });
      return;
    }
    host.setAttribute("data-key", key);
    host.replaceChildren();
    ids.forEach(function (id) {
      var b = document.createElement("button");
      b.textContent = id; b.setAttribute("data-id", id);
      b.classList.toggle("on", !hidden[id]);
      b.addEventListener("click", function () { hidden[id] = !hidden[id]; GPTimeline.render(GPStore.state); });
      host.appendChild(b);
    });
  }

  function render(state) {
    var canvas = document.getElementById("tl");
    if (!state.session || !document.getElementById("view-timeline").classList.contains("active")) return;
    chips(state);
    var d = GPDraw.setup(canvas), ctx = d.ctx;
    ctx.clearRect(0, 0, d.w, d.h);
    var s = state.session.series, n = s.t.length;
    var ls = lanes(state);
    var plotW = d.w - GUTTER - 14;
    var ink2 = GPDraw.css("--ink2"), ink3 = GPDraw.css("--ink3"), border = GPDraw.css("--border");

    if (!n || !ls.length) {
      ctx.fillStyle = ink3; ctx.font = "13px system-ui";
      ctx.fillText("no series yet — waiting for the first window", 16, 26);
      return;
    }

    ls.forEach(function (lane, li) {
      var y = PAD_T + li * LANE_H;
      if (y + LANE_H > d.h) return;                      // clipped; lane count fits typical pipelines
      ctx.fillStyle = ink2; ctx.font = "11.5px ui-monospace, Menlo, monospace";
      ctx.fillText(clip(ctx, lane.label, GUTTER - 18), 10, y + 14);
      ctx.strokeStyle = border; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(GUTTER, y + LANE_H - 6.5); ctx.lineTo(GUTTER + plotW, y + LANE_H - 6.5); ctx.stroke();
      var color = GPDraw.css(lane.color);
      if (lane.kind === "band") {
        var max = GPDraw.finiteMax(lane.hi, 1e-9);
        GPDraw.band(ctx, lane.lo, lane.hi, GUTTER, y + 3, plotW, LANE_H - 10, max * HEADROOM, color);
        label(ctx, lane, max, GUTTER + plotW, y, ink3);
      } else {
        var mx = GPDraw.finiteMax(lane.vals, 1e-9);
        GPDraw.line(ctx, lane.vals, GUTTER, y + 3, plotW, LANE_H - 10, mx * HEADROOM, color, true);
        label(ctx, lane, mx, GUTTER + plotW, y, ink3);
        if (lane.stalled) markStalls(ctx, lane.stalled, GUTTER, y + 3, plotW, LANE_H - 10);
      }
    });

    var plotH = Math.min(d.h - PAD_T, ls.length * LANE_H);
    drawEvents(ctx, state, GUTTER, PAD_T, plotW, plotH, n);
    GPDraw.cursor(ctx, GPStore.cursorIndex(), n, GUTTER, PAD_T, plotW, plotH, ink2);
    if (hover !== null) {
      GPDraw.cursor(ctx, hover, n, GUTTER, PAD_T, plotW, plotH, GPDraw.css("--focus"));
      hoverTipContent(state, ls, hover);
    }
  }

  function label(ctx, lane, max, xRight, y, color) {
    ctx.fillStyle = color; ctx.font = "10.5px ui-monospace, Menlo, monospace"; ctx.textAlign = "right";
    ctx.fillText("≤" + GPDraw.fmt(max, lane.unit), GUTTER - 10, y + 24);   // scale max, in the gutter
    ctx.textAlign = "left";
  }

  function markStalls(ctx, stalled, x, y, w, h) {
    var n = stalled.length, dx = n > 1 ? w / (n - 1) : 0;
    ctx.save(); ctx.fillStyle = GPDraw.css("--high"); ctx.globalAlpha = 0.5;
    for (var i = 0; i < n; i++) if (stalled[i] === true) ctx.fillRect(x + i * dx - 1, y, 2, h);
    ctx.restore();
  }

  function drawEvents(ctx, state, x, y, w, h, n) {
    var t = state.session.series.t;
    if (!t.length) return;
    var t0 = t[0], t1 = t[t.length - 1] || 1;
    ctx.save(); ctx.strokeStyle = GPDraw.css("--ink3"); ctx.setLineDash([2, 3]);
    (state.session.events || []).forEach(function (ev) {
      if (typeof ev.t !== "number" || ev.t < t0 || ev.t > t1) return;
      var px = x + (t1 > t0 ? (ev.t - t0) / (t1 - t0) : 0) * w;
      ctx.beginPath(); ctx.moveTo(px, y); ctx.lineTo(px, y + h); ctx.stroke();
    });
    ctx.restore();
  }

  function hoverTipContent(state, ls, i) {
    var tooltip = document.getElementById("tooltip");
    var t = state.session.series.t[i];
    var lines = ["<b>t = " + GPDraw.fmt(t, " s") + "</b>"];
    ls.slice(0, 14).forEach(function (lane) {
      var v = lane.kind === "band" ? lane.hi[i] : lane.vals[i];
      lines.push(GPPipeline.esc(lane.label) + ": <b>" + GPDraw.fmt(v, lane.unit) + "</b>");
    });
    var evs = (state.session.events || []).filter(function (e) { return Math.abs(e.t - t) < 0.5; });
    evs.slice(0, 3).forEach(function (e) { lines.push("◆ " + GPPipeline.esc(e.kind + ": " + e.text)); });
    tooltip.innerHTML = lines.join("<br>");
    tooltip.hidden = false;
  }

  function clip(ctx, text, maxW) {
    if (ctx.measureText(text).width <= maxW) return text;
    while (text.length > 2 && ctx.measureText(text + "…").width > maxW) text = text.slice(0, -1);
    return text + "…";
  }

  function wire() {
    var canvas = document.getElementById("tl");
    canvas.addEventListener("mousemove", function (ev) {
      var st = GPStore.state;
      if (!st.session) return;
      var r = canvas.getBoundingClientRect();
      var n = st.session.series.t.length;
      var frac = (ev.clientX - r.left - GUTTER) / Math.max(1, r.width - GUTTER - 14);
      if (frac < 0 || frac > 1 || n < 1) { hover = null; document.getElementById("tooltip").hidden = true; }
      else hover = Math.round(frac * (n - 1));
      var tip = document.getElementById("tooltip");
      tip.style.left = Math.min(ev.clientX + 14, window.innerWidth - 300) + "px";
      tip.style.top = Math.max(8, ev.clientY - 30) + "px";
      render(st);
    });
    canvas.addEventListener("mouseleave", function () {
      hover = null; document.getElementById("tooltip").hidden = true; render(GPStore.state);
    });
    canvas.addEventListener("click", function () {
      if (hover !== null) GPStore.setCursor(hover, false);
    });
  }

  return { render: render, wire: wire };
})();
if (typeof module !== "undefined") module.exports = GPTimeline;
