/* Right-side inspector for the selected element: identity, properties, per-metric
   sparklines with the value at the cursor, and the findings touching it. */
var GPInspector = (function () {
  var METRICS = [
    { key: "proc_ms_p95", label: "proc p95", unit: " ms" },
    { key: "proc_ms_p50", label: "proc p50", unit: " ms" },
    { key: "cpu_pct", label: "cpu", unit: "%" },
    { key: "queue_level", label: "queue level", unit: "" },
  ];

  function render(state) {
    var box = document.getElementById("inspector");
    var id = state.selected;
    if (!id || !state.session) { box.hidden = true; return; }
    var graphEl = (state.session.graph.elements || []).filter(function (e) { return e.id === id; })[0];
    if (!graphEl) { box.hidden = true; return; }
    box.hidden = false;
    box.replaceChildren();

    var close = mk("button", "close", "×");
    close.addEventListener("click", function () { GPStore.select(null); });
    box.appendChild(close);

    var h = document.createElement("h2");
    var fac = mk("span", "fac", graphEl.factory || graphEl.gtype || id);
    h.appendChild(fac);
    var vt = mk("span", "vtag v-" + (graphEl.vendor || "generic"), graphEl.vendor || "generic");
    h.appendChild(vt);
    box.appendChild(h);
    if ((graphEl.factory || "") !== id) box.appendChild(mk("div", "dim mono", id));
    if (graphEl.klass) box.appendChild(mk("div", "dim", graphEl.klass));
    if (graphEl.bin && graphEl.bin !== state.session.graph.pipeline) {
      box.appendChild(mk("div", "dim", "inside bin: " + graphEl.bin));
    }

    // sparklines
    var s = state.session.series.elements[id] || {};
    var i = GPStore.cursorIndex();
    var any = false;
    var sec = mk("div", "sec", "last " + state.session.series.t.length + " windows");
    box.appendChild(sec);
    METRICS.forEach(function (m) {
      var vals = s[m.key] || [];
      if (!GPStore.numeric(vals).length) return;
      any = true;
      box.appendChild(sparkRow(m.label, vals, i, m.unit));
    });
    linkRows(state, id, i).forEach(function (r) { any = true; box.appendChild(r); });
    if (!any) box.appendChild(mk("div", "dim", "no per-element series on this capture"));

    // properties
    var props = graphEl.props || {};
    var keys = Object.keys(props);
    if (keys.length) {
      box.appendChild(mk("div", "sec", "properties (non-default)"));
      var table = document.createElement("table");
      keys.sort().forEach(function (k) {
        var tr = document.createElement("tr");
        tr.appendChild(mkCell("td", "k mono", k));
        tr.appendChild(mkCell("td", "v mono", String(props[k])));
        table.appendChild(tr);
      });
      box.appendChild(table);
    }

    // findings touching this element
    var touching = ((state.verdict && state.verdict.findings) || []).filter(function (f) {
      return ((f.targets || {}).elements || []).indexOf(id) >= 0;
    });
    if (touching.length) {
      box.appendChild(mk("div", "sec", "findings"));
      touching.forEach(function (f) {
        var chip = mk("button", "fchip " + f.severity, f.rule + " · " + f.title);
        chip.addEventListener("click", function () {
          GPStore.focusFinding(f.id);
          GPApp.showTab("analysis");
        });
        box.appendChild(chip);
      });
    }
  }

  /* fps in/out at the cursor from the links touching the element. */
  function linkRows(state, id, i) {
    var out = [];
    (state.session.graph.links || []).forEach(function (l) {
      var isIn = String(l.sink).split(":")[0] === id, isOut = String(l.src).split(":")[0] === id;
      if (!isIn && !isOut) return;
      var s = state.session.series.links[l.id];
      if (!s || !GPStore.numeric(s.fps || []).length) return;
      out.push(sparkRow(isIn ? "fps in" : "fps out", s.fps, i, " fps"));
    });
    return out.slice(0, 4);
  }

  function sparkRow(label, vals, i, unit) {
    var row = mk("div", "spark", "");
    var c = document.createElement("canvas");
    c.width = 110; c.height = 24;
    c.style.width = "110px"; c.style.height = "24px";
    var ctx = c.getContext("2d");
    var max = GPDraw.finiteMax(vals, 1e-9) * 1.18;
    GPDraw.line(ctx, vals, 2, 2, 106, 20, max, GPDraw.css("--info"), true);
    GPDraw.cursor(ctx, i, vals.length, 2, 2, 106, 20, GPDraw.css("--ink3"));
    row.appendChild(c);
    row.appendChild(mk("span", "lab", label));
    row.appendChild(mk("span", "val mono", GPDraw.fmt(vals[i], unit)));
    return row;
  }

  function mk(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }
  function mkCell(tag, cls, text) { return mk(tag, cls, text); }

  return { render: render };
})();
if (typeof module !== "undefined") module.exports = GPInspector;
