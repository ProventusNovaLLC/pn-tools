/* Pipeline tab: the living graph. Node fill = vendor, heat bar = share of pipeline
   latency at the cursor window; edge color = memory domain, width = bytes/s, dashes
   animate in flow direction at a speed proportional to fps; a stalled link stops and
   pulses red. Findings outline their targets. All text lands via textContent. */
var GPPipeline = (function () {
  var NS = "http://www.w3.org/2000/svg";
  var svg, tooltip, layoutCache = { key: "", layout: null };
  var edgeEls = {}, nodeEls = {}, heatEls = {}, procEls = {};
  var dashOffsets = {}, lastFrame = 0, animating = false, showIdle = false;
  var DASH_PERIOD = 12;                    // px per dash cycle ("7 5")
  var SPEED = 0.55;                        // px/s of drift per fps: 30 fps ≈ 16.5 px/s

  function el(tag, cls) {
    var e = document.createElementNS(NS, tag);
    if (cls) e.setAttribute("class", cls);
    return e;
  }

  function graphKey(graph) {
    return (graph.elements || []).map(function (e) { return e.id; }).join("|") + "//" +
           (graph.links || []).map(function (l) { return l.id; }).join("|");
  }

  function ensureLayout(graph) {
    var key = graphKey(graph);
    if (layoutCache.key !== key) layoutCache = { key: key, layout: GPLayout.layout(graph) };
    return layoutCache.layout;
  }

  function render(state) {
    svg = svg || document.getElementById("graph");
    tooltip = tooltip || document.getElementById("tooltip");
    var session = state.session;
    var graph = session && session.graph;
    var empty = document.getElementById("graphempty");
    var hasNodes = graph && (graph.elements || []).some(function (e) { return !e.is_bin; });
    empty.hidden = !!hasNodes;
    if (!hasNodes) { svg.replaceChildren(); layoutCache = { key: "", layout: null }; renderIdleToggle(0); return; }

    // Idle stages (dormant whole capture, see idleElements) are hidden by default so
    // the graph shows only pipelines that carried data. The toggle reveals them (dimmed).
    var active = idleElements(state);
    var idleIds = (graph.elements || []).filter(function (e) { return !e.is_bin && !active[e.id]; }).map(function (e) { return e.id; });
    var activeCount = (graph.elements || []).filter(function (e) { return !e.is_bin; }).length - idleIds.length;
    var useGraph = (showIdle || !idleIds.length || activeCount === 0) ? graph : withoutElements(graph, idleIds);

    var L = ensureLayout(useGraph);
    if (svg.getAttribute("data-key") !== layoutCache.key) rebuild(state, L, useGraph);
    update(state, L, active);
    renderIdleToggle(idleIds.length);
  }

  /* A shallow graph copy with the given elements (and any link touching them) removed. */
  function withoutElements(graph, hideIds) {
    var hidden = {};
    hideIds.forEach(function (id) { hidden[id] = 1; });
    return {
      pipeline: graph.pipeline,
      elements: (graph.elements || []).filter(function (e) { return !hidden[e.id]; }),
      links: (graph.links || []).filter(function (l) {
        return !hidden[String(l.src).split(":")[0]] && !hidden[String(l.sink).split(":")[0]];
      }),
    };
  }

  function renderIdleToggle(count) {
    var host = document.getElementById("idletoggle");
    if (!host) return;
    if (!count) { host.hidden = true; return; }
    host.hidden = false;
    host.replaceChildren();
    var lab = document.createElement("span");
    lab.textContent = count + " idle stage" + (count > 1 ? "s" : "") + (showIdle ? " shown" : " hidden");
    var btn = document.createElement("button");
    btn.textContent = showIdle ? "hide" : "show";
    btn.addEventListener("click", function () { showIdle = !showIdle; render(GPStore.state); });
    host.appendChild(lab); host.appendChild(btn);
  }

  function rebuild(state, L, graph) {
    svg.setAttribute("data-key", layoutCache.key);
    svg.setAttribute("viewBox", "0 0 " + L.width + " " + L.height);
    svg.setAttribute("width", L.width); svg.setAttribute("height", L.height);
    svg.replaceChildren();
    edgeEls = {}; nodeEls = {}; heatEls = {}; procEls = {};
    var gEdges = el("g"), gNodes = el("g");
    svg.appendChild(gEdges); svg.appendChild(gNodes);

    L.edges.forEach(function (e) {
      var p = el("path", "edge m-" + (e.link.memory || "unknown"));
      p.setAttribute("d", e.path);
      if ((e.link.memory || "unknown") === "unknown") p.setAttribute("stroke-dasharray", "3 5");
      else p.setAttribute("stroke-dasharray", "7 5");
      var hit = el("path", "edgehit");
      hit.setAttribute("d", e.path);
      hit.addEventListener("mousemove", function (ev) { edgeTip(ev, e); });
      hit.addEventListener("mouseleave", hideTip);
      gEdges.appendChild(p); gEdges.appendChild(hit);
      edgeEls[e.link.id] = p;
      dashOffsets[e.link.id] = dashOffsets[e.link.id] || 0;
    });

    L.nodes.forEach(function (n) {
      var g = el("g", "node v-" + (n.el.vendor || "generic"));
      g.setAttribute("transform", "translate(" + n.x + "," + n.y + ")");
      var outline = el("rect", "outline");
      outline.setAttribute("x", -3); outline.setAttribute("y", -3);
      outline.setAttribute("width", n.w + 6); outline.setAttribute("height", n.h + 6);
      var body = el("rect", "body");
      body.setAttribute("width", n.w); body.setAttribute("height", n.h);
      var fac = el("text");
      fac.setAttribute("x", 9); fac.setAttribute("y", 19);
      fac.textContent = n.el.factory || n.el.gtype || n.id;
      var iname = el("text", "iname");
      iname.setAttribute("x", 9); iname.setAttribute("y", 33);
      if ((n.el.factory || "") !== n.id) iname.textContent = n.id;
      var heat = el("rect", "heat");
      heat.setAttribute("x", 8); heat.setAttribute("y", n.h - 8);
      heat.setAttribute("height", 4); heat.setAttribute("width", 0);
      var proc = el("text", "proctime");
      proc.setAttribute("x", n.w - 9); proc.setAttribute("y", 19);
      var idle = el("text", "idle-tag");
      idle.setAttribute("x", n.w - 9); idle.setAttribute("y", 19);
      idle.textContent = "idle";
      g.appendChild(outline); g.appendChild(body); g.appendChild(fac); g.appendChild(iname); g.appendChild(heat); g.appendChild(proc); g.appendChild(idle);
      g.addEventListener("click", function (ev) { ev.stopPropagation(); GPStore.select(n.id); });
      g.addEventListener("mousemove", function (ev) { nodeTip(ev, n); });
      g.addEventListener("mouseleave", hideTip);
      gNodes.appendChild(g);
      nodeEls[n.id] = g; heatEls[n.id] = heat; procEls[n.id] = proc;
    });

    svg.addEventListener("click", function () { GPStore.select(null); });
  }

  /* Continuous cold→amber→red scale. t in 0..1; the hottest element in the window is 1 (red). */
  function heatAt(t) {
    t = Math.max(0, Math.min(1, t));
    var c0 = GPDraw.css("--heat0"), c1 = GPDraw.css("--heat1"), c2 = GPDraw.css("--heat2");
    return t < 0.5 ? lerpHex(c0, c1, t * 2) : lerpHex(c1, c2, (t - 0.5) * 2);
  }
  function lerpHex(a, b, t) {
    var pa = hex(a), pb = hex(b);
    var m = function (k) { return Math.round(pa[k] + (pb[k] - pa[k]) * t); };
    return "rgb(" + m(0) + "," + m(1) + "," + m(2) + ")";
  }
  function hex(c) {
    c = String(c).replace("#", "");
    if (c.length === 3) c = c[0] + c[0] + c[1] + c[1] + c[2] + c[2];
    return [parseInt(c.slice(0, 2), 16), parseInt(c.slice(2, 4), 16), parseInt(c.slice(4, 6), 16)];
  }
  function fmtMs(v) { return (v >= 100 ? v.toFixed(0) : v.toFixed(1)) + " ms"; }

  /* An element is idle when no link touching it ever carried a buffer in this session
     (isolated nodes, or a pipeline dormant the whole capture, e.g. a recorder waiting
     for its trigger). Dimmed + tagged so it reads as "waiting", not "broken". */
  function idleElements(state) {
    var links = state.session.series.links, active = {};
    (state.session.graph.links || []).forEach(function (l) {
      var fps = links[l.id] && links[l.id].fps;
      var flows = fps && fps.some(function (v) { return typeof v === "number" && v > 0; });
      if (flows) { active[String(l.src).split(":")[0]] = 1; active[String(l.sink).split(":")[0]] = 1; }
    });
    return active;                                   // any node NOT in here is idle
  }

  function update(state, L, active) {
    var i = GPStore.cursorIndex();
    var caps = (state.session.target && state.session.target.capabilities) || {};
    var hasProc = caps.element_latency !== false;
    active = active || idleElements(state);

    // proc time (absolute, ms) + share (fraction of pipeline proc); heat is share
    // normalized to the hottest element, so the biggest time sink is red and the rest ramp down.
    var els = state.session.series.elements, procs = {}, total = 0;
    if (hasProc) L.nodes.forEach(function (n) {
      var arr = els[n.id] && els[n.id].proc_ms_p95, v = arr && arr[i];
      if (typeof v === "number") { procs[n.id] = v; total += v; }
    });
    var maxShare = 0;
    if (total > 0) Object.keys(procs).forEach(function (id) { maxShare = Math.max(maxShare, procs[id] / total); });

    L.nodes.forEach(function (n) {
      var g = nodeEls[n.id], heat = heatEls[n.id], proc = procEls[n.id];
      var v = procs[n.id];
      if (typeof v === "number" && total > 0) {
        var share = v / total, col = heatAt(maxShare ? share / maxShare : 0);
        heat.setAttribute("width", Math.round(share * (n.w - 16)));
        heat.setAttribute("fill", col);
        proc.textContent = fmtMs(v);
        proc.setAttribute("fill", col);
      } else {
        heat.setAttribute("width", 0);
        proc.textContent = "";
      }
      g.classList.toggle("selected", state.selected === n.id);
      g.classList.toggle("idle", !active[n.id]);
    });

    // finding outlines: severity class per target; the focused (or top) finding is primary
    var findings = (state.verdict && state.verdict.findings) || [];
    var diagnostic = findings.filter(function (f) { return f.rule !== "HOT" && f.rule !== "OK"; });
    var primary = state.focusFinding ? findings.filter(function (f) { return f.id === state.focusFinding; })[0]
                                     : diagnostic[0];
    Object.keys(nodeEls).forEach(function (id) {
      nodeEls[id].classList.remove("f-high", "f-medium", "f-info", "f-primary");
    });
    Object.keys(edgeEls).forEach(function (id) {
      edgeEls[id].classList.remove("f-high", "f-medium", "f-info");
    });
    // high/medium always paint; info (heuristic) findings only when focused or top:
    // a healthy pipeline full of info findings must not read as a christmas tree
    findings.slice().reverse().forEach(function (f) {          // reversed: rank 1 paints last, wins
      if (f.severity === "info" && f !== primary) return;
      if (f.rule === "HOT" || f.rule === "OK") return;
      var t = f.targets || {};
      (t.elements || []).forEach(function (id) {
        if (nodeEls[id]) { nodeEls[id].classList.add("f-" + f.severity); }
      });
      (t.links || []).forEach(function (id) {
        if (edgeEls[id]) edgeEls[id].classList.add("f-" + f.severity);
      });
    });
    if (primary) (primary.targets && primary.targets.elements || []).forEach(function (id) {
      if (nodeEls[id]) nodeEls[id].classList.add("f-primary");
    });

    // edge width + stall state at the cursor window
    var links = state.session.series.links;
    L.edges.forEach(function (e) {
      var p = edgeEls[e.link.id], s = links[e.link.id];
      var bytes = s && s.bytes_s ? s.bytes_s[i] : null;
      var w = typeof bytes === "number" && bytes > 0 ? Math.min(8, 1.6 + Math.log10(1 + bytes) * 0.62) : 1.6;
      p.setAttribute("stroke-width", w.toFixed(1));
      var stalled = !!(s && s.stalled && s.stalled[i]);
      p.classList.toggle("stalled", stalled);
    });

    startAnim();
  }

  /* rAF loop: drift dash offsets by each link's fps at the cursor window. */
  function startAnim() {
    if (animating) return;
    animating = true; lastFrame = performance.now();
    requestAnimationFrame(frame);
  }
  function frame(now) {
    var visible = document.getElementById("view-pipeline").classList.contains("active");
    var state = GPStore.state;
    if (!visible || !state.session || !layoutCache.layout) { animating = false; return; }
    var dt = Math.min(0.1, (now - lastFrame) / 1000); lastFrame = now;
    var i = GPStore.cursorIndex();
    var links = state.session.series.links;
    var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    layoutCache.layout.edges.forEach(function (e) {
      var id = e.link.id, p = edgeEls[id], s = links[id];
      if (!p) return;
      var fps = s && s.fps ? s.fps[i] : null;
      var stalled = !!(s && s.stalled && s.stalled[i]);
      if (reduced || stalled || typeof fps !== "number" || fps <= 0) return;
      dashOffsets[id] = (dashOffsets[id] - fps * SPEED * dt) % DASH_PERIOD;
      p.setAttribute("stroke-dashoffset", dashOffsets[id].toFixed(2));
    });
    requestAnimationFrame(frame);
  }

  function edgeTip(ev, e) {
    var state = GPStore.state, i = GPStore.cursorIndex();
    var s = state.session.series.links[e.link.id] || {};
    var fps = s.fps ? s.fps[i] : null, bytes = s.bytes_s ? s.bytes_s[i] : null;
    var rows = [
      "<b>" + escTip(e.src) + " → " + escTip(e.dst) + "</b>",
      "memory: <b>" + escTip(e.link.memory || "unknown") + "</b>" + (e.link.format ? " · " + escTip(e.link.format) : ""),
      GPDraw.fmt(fps, " fps") + " · " + GPDraw.fmtBytes(bytes) + (s.stalled && s.stalled[i] ? " · <b>stalled</b>" : ""),
    ];
    if (e.link.caps) rows.push('<span class="mono">' + escTip(e.link.caps) + "</span>");
    showTip(ev, rows.join("<br>"));
  }

  function nodeTip(ev, n) {
    var state = GPStore.state, i = GPStore.cursorIndex();
    var s = state.session.series.elements[n.id] || {};
    var p95 = s.proc_ms_p95 ? s.proc_ms_p95[i] : null, cpu = s.cpu_pct ? s.cpu_pct[i] : null;
    showTip(ev, "<b>" + escTip(n.id) + "</b><br>proc p95 " + GPDraw.fmt(p95, " ms") +
                " · cpu " + GPDraw.fmt(cpu, "%") + "<br><span class='dim'>click for details</span>");
  }

  function showTip(ev, html) {
    tooltip.innerHTML = html;                       // built only from escTip'd strings
    tooltip.hidden = false;
    var x = Math.min(ev.clientX + 14, window.innerWidth - tooltip.offsetWidth - 8);
    var y = Math.min(ev.clientY + 14, window.innerHeight - tooltip.offsetHeight - 8);
    tooltip.style.left = x + "px"; tooltip.style.top = y + "px";
  }
  function hideTip() { tooltip.hidden = true; }

  function escTip(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  return { render: render, esc: escTip };
})();
if (typeof module !== "undefined") module.exports = GPPipeline;
