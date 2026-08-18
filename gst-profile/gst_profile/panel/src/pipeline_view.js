/* Pipeline tab: the living graph. Node fill = vendor, heat bar = share of pipeline
   latency at the cursor window; edge color = memory domain, width = bytes/s, dashes
   animate in flow direction at a speed proportional to fps; a stalled link stops and
   pulses red. Findings outline their targets. All text lands via textContent. */
var GPPipeline = (function () {
  var NS = "http://www.w3.org/2000/svg";
  var svg, tooltip, layoutCache = { key: "", layout: null };
  var edgeEls = {}, nodeEls = {}, heatEls = {};
  var dashOffsets = {}, lastFrame = 0, animating = false;
  var DASH_PERIOD = 12;                    // px per dash cycle ("7 5")
  var SPEED = 0.55;                        // px/s of drift per fps — 30 fps ≈ 16.5 px/s

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
    if (!hasNodes) { svg.replaceChildren(); layoutCache = { key: "", layout: null }; return; }

    var L = ensureLayout(graph);
    if (svg.getAttribute("data-key") !== layoutCache.key) rebuild(state, L, graph);
    update(state, L, graph);
  }

  function rebuild(state, L, graph) {
    svg.setAttribute("data-key", layoutCache.key);
    svg.setAttribute("viewBox", "0 0 " + L.width + " " + L.height);
    svg.setAttribute("width", L.width); svg.setAttribute("height", L.height);
    svg.replaceChildren();
    edgeEls = {}; nodeEls = {}; heatEls = {};
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
      heat.setAttribute("x", 8); heat.setAttribute("y", n.h - 7);
      heat.setAttribute("height", 3); heat.setAttribute("width", 0);
      g.appendChild(outline); g.appendChild(body); g.appendChild(fac); g.appendChild(iname); g.appendChild(heat);
      g.addEventListener("click", function (ev) { ev.stopPropagation(); GPStore.select(n.id); });
      g.addEventListener("mousemove", function (ev) { nodeTip(ev, n); });
      g.addEventListener("mouseleave", hideTip);
      gNodes.appendChild(g);
      nodeEls[n.id] = g; heatEls[n.id] = heat;
    });

    svg.addEventListener("click", function () { GPStore.select(null); });
  }

  function shareAt(state, i) {
    var els = state.session.series.elements, per = {}, total = 0;
    Object.keys(els).forEach(function (id) {
      var v = els[id].proc_ms_p95 && els[id].proc_ms_p95[i];
      if (typeof v === "number") { per[id] = v; total += v; }
    });
    Object.keys(per).forEach(function (id) { per[id] = per[id] / total; });
    return total > 0 ? per : {};
  }

  function heatColor(share) {
    return share > 0.5 ? GPDraw.css("--heat2") : share > 0.2 ? GPDraw.css("--heat1") : GPDraw.css("--heat0");
  }

  function update(state, L) {
    var i = GPStore.cursorIndex();
    var caps = (state.session.target && state.session.target.capabilities) || {};
    var share = caps.element_latency === false ? {} : shareAt(state, i);

    L.nodes.forEach(function (n) {
      var g = nodeEls[n.id], heat = heatEls[n.id];
      var s = share[n.id] || 0;
      heat.setAttribute("width", Math.round(s * (n.w - 16)));
      heat.setAttribute("fill", heatColor(s));
      g.classList.toggle("selected", state.selected === n.id);
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
    // high/medium always paint; info (heuristic) findings only when focused or top —
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
