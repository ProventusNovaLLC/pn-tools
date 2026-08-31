/* Layered left-to-right graph layout for pipeline graphs (Sugiyama-lite).
   The graph may hold several disconnected pipelines (e.g. an app that runs many
   gst_parse_launch pipelines bridged by interpipe/appsink, invisible to pad
   topology). Each weakly-connected component is laid out on its own: longest-path
   layering, barycenter ordering, then neighbour-barycenter vertical positioning so
   a node sits centered on the elements it actually connects to. Components are then
   stacked vertically, each below the previous one. Columns (x) are shared across all
   components so every source lines up on the left. Pure function of the graph: no DOM. */
var GPLayout = (function () {
  var NODE_H = 46, H_GAP = 64, V_GAP = 20, COMPONENT_GAP = 44, CHAR_W = 7.4;

  function nodeWidth(el) {
    var label = Math.max((el.factory || el.gtype || "").length, (el.id || "").length);
    // +46 reserves room for the right-aligned proc-time label on the title line.
    return Math.max(140, Math.min(270, Math.round(label * CHAR_W) + 30 + 46));
  }

  function srcEl(l) { return String(l.src || "").split(":")[0]; }
  function sinkEl(l) { return String(l.sink || "").split(":")[0]; }

  /* graph: {elements:[{id, is_bin, ...}], links:[{id, src:"el:pad", sink:"el:pad"}]} */
  function layout(graph) {
    var els = (graph.elements || []).filter(function (e) { return !e.is_bin; });
    var byId = {};
    els.forEach(function (e) { byId[e.id] = e; });
    var links = (graph.links || []).filter(function (l) {
      return byId[srcEl(l)] && byId[sinkEl(l)];
    });

    // directed adjacency (for layering); self-loops ignored
    var out = {}, inn = {};
    els.forEach(function (e) { out[e.id] = []; inn[e.id] = []; });
    links.forEach(function (l) {
      var a = srcEl(l), b = sinkEl(l);
      if (a === b) return;
      if (out[a].indexOf(b) < 0) out[a].push(b);
      if (inn[b].indexOf(a) < 0) inn[b].push(a);
    });

    // ---- weakly-connected components (union-find over undirected edges) ----
    var parent = {};
    els.forEach(function (e) { parent[e.id] = e.id; });
    function find(x) { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; }
    links.forEach(function (l) {
      var a = find(srcEl(l)), b = find(sinkEl(l));
      if (a !== b) parent[a] = b;
    });
    var byRoot = {};
    els.forEach(function (e) { var r = find(e.id); (byRoot[r] = byRoot[r] || []).push(e.id); });
    var components = Object.keys(byRoot).map(function (r) { return byRoot[r]; });

    // ---- longest-path layering from sources (cycle-guarded; components disjoint) ----
    var layer = {}, onStack = {};
    function rank(id) {
      if (layer[id] !== undefined) return layer[id];
      if (onStack[id]) return 0;
      onStack[id] = true;
      var r = 0;
      inn[id].forEach(function (up) { r = Math.max(r, rank(up) + 1); });
      onStack[id] = false;
      layer[id] = r;
      return r;
    }
    els.forEach(function (e) { rank(e.id); });

    // ---- shared global columns: x per layer index, widest node in that layer ----
    var maxLayer = 0;
    els.forEach(function (e) { maxLayer = Math.max(maxLayer, layer[e.id]); });
    var layerW = [];
    for (var i = 0; i <= maxLayer; i++) layerW[i] = 0;
    els.forEach(function (e) { layerW[layer[e.id]] = Math.max(layerW[layer[e.id]], nodeWidth(e)); });
    var layerX = [], xacc = 0;
    for (i = 0; i <= maxLayer; i++) { layerX[i] = xacc; xacc += layerW[i] + H_GAP; }
    var totalWidth = Math.max(NODE_H, xacc - H_GAP);

    // ---- lay out each component, stack vertically ----
    // Order top→bottom by role, so producers sit above the stages they feed:
    //   tier 0 = capture pipelines (contain a real hardware/live source),
    //   tier 1 = derived pipelines (fed only by an in-process bridge: interpipe/app/proxy),
    //   tier 2 = single-node / unlinked components (idle stages), sink to the bottom.
    // Within a tier, order by the smallest source id so per-camera order stays stable.
    function isBridgeSrc(f) { return /^(interpipesrc|appsrc|proxysrc)/.test(String(f || "").toLowerCase()); }
    function compKey(comp) {
      var sources = comp.filter(function (id) { return inn[id].length === 0; });
      var srcIds = (sources.length ? sources : comp).slice().sort();
      var tier = comp.length <= 1 ? 2
        : srcIds.some(function (id) { return !isBridgeSrc(byId[id].factory || byId[id].gtype); }) ? 0 : 1;
      return { tier: tier, src: srcIds[0] };
    }
    components = components.map(function (comp) { return { comp: comp, key: compKey(comp) }; })
      .sort(function (a, b) {
        if (a.key.tier !== b.key.tier) return a.key.tier - b.key.tier;
        return a.key.src < b.key.src ? -1 : a.key.src > b.key.src ? 1 : 0;
      })
      .map(function (k) { return k.comp; });

    var nodes = {}, nodeList = [];
    var yCursor = 0;

    components.forEach(function (comp) {
      var compLayers = [];
      comp.slice().sort().forEach(function (id) {          // stable seed order
        var L = layer[id];
        (compLayers[L] = compLayers[L] || []).push(id);
      });

      // barycenter ORDER sweeps within the component (reduce edge crossings)
      var pos = {};
      function reindex() { compLayers.forEach(function (ids) { if (ids) ids.forEach(function (id, k) { pos[id] = k; }); }); }
      reindex();
      function orderSweep(neigh) {
        compLayers.forEach(function (ids) {
          if (!ids) return;
          var keyed = ids.map(function (id) {
            var ns = neigh[id].filter(function (n) { return pos[n] !== undefined; });
            var bary = ns.length ? ns.reduce(function (s, n) { return s + pos[n]; }, 0) / ns.length : pos[id];
            return { id: id, k: bary };
          });
          keyed.sort(function (a, b) { return a.k - b.k || pos[a.id] - pos[b.id]; });
          ids.length = 0; keyed.forEach(function (e) { ids.push(e.id); });
          reindex();
        });
      }
      orderSweep(inn); orderSweep(out); orderSweep(inn); orderSweep(out);

      // seed y by slot within layer (local to this component)
      var y = {};
      compLayers.forEach(function (ids) {
        if (!ids) return;
        ids.forEach(function (id, k) { y[id] = k * (NODE_H + V_GAP); });
      });

      // POSITION passes: pull each node toward the mean y of its cross-layer neighbours,
      // then keep min spacing within the layer (preserving order) and recenter the block.
      function positionPass(neigh, forward) {
        var order = [];
        for (var L = 0; L < compLayers.length; L++) order.push(L);
        if (!forward) order.reverse();
        order.forEach(function (L) {
          var ids = compLayers[L];
          if (!ids || !ids.length) return;
          var desired = ids.map(function (id) {
            var ns = neigh[id].filter(function (n) { return y[n] !== undefined && layer[n] !== L; });
            return ns.length ? ns.reduce(function (s, n) { return s + y[n]; }, 0) / ns.length : y[id];
          });
          var placed = [];
          for (var k = 0; k < ids.length; k++) {
            var yk = desired[k];
            if (k > 0) yk = Math.max(yk, placed[k - 1] + NODE_H + V_GAP);
            placed.push(yk);
          }
          var meanD = desired.reduce(function (s, v) { return s + v; }, 0) / desired.length;
          var meanP = placed.reduce(function (s, v) { return s + v; }, 0) / placed.length;
          var shift = meanD - meanP;
          ids.forEach(function (id, k) { y[id] = placed[k] + shift; });
        });
      }
      for (var p = 0; p < 4; p++) { positionPass(inn, true); positionPass(out, false); }

      // normalize the component to start at yCursor, emit nodes
      var ys = comp.map(function (id) { return y[id]; });
      var minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);
      var offset = yCursor - minY;
      comp.forEach(function (id) {
        var w = nodeWidth(byId[id]);
        var n = { id: id, el: byId[id], x: layerX[layer[id]] + (layerW[layer[id]] - w) / 2,
                  y: y[id] + offset, w: w, h: NODE_H, layer: layer[id] };
        nodes[id] = n; nodeList.push(n);
      });
      yCursor += (maxY - minY) + NODE_H + COMPONENT_GAP;
    });

    var totalHeight = Math.max(NODE_H, yCursor - COMPONENT_GAP);

    // ---- edge endpoints: distribute multiple links on a node side evenly ----
    var outLinks = {}, inLinks = {};
    links.forEach(function (l) {
      (outLinks[srcEl(l)] = outLinks[srcEl(l)] || []).push(l);
      (inLinks[sinkEl(l)] = inLinks[sinkEl(l)] || []).push(l);
    });
    function side(list, l, node) {
      var k = list.indexOf(l), n = list.length;
      return node.y + node.h * (k + 1) / (n + 1);
    }
    var edges = links.map(function (l) {
      var a = nodes[srcEl(l)], b = nodes[sinkEl(l)];
      var x0 = a.x + a.w, y0 = side(outLinks[a.id], l, a);
      var x1 = b.x, y1 = side(inLinks[b.id], l, b);
      var dx = Math.max(28, (x1 - x0) / 2);
      return { link: l, src: a.id, dst: b.id, x0: x0, y0: y0, x1: x1, y1: y1,
               path: "M" + x0 + "," + y0 + " C" + (x0 + dx) + "," + y0 + " " + (x1 - dx) + "," + y1 + " " + x1 + "," + y1 };
    });

    return { nodes: nodeList, byId: nodes, edges: edges, width: totalWidth + 4, height: totalHeight + 4 };
  }

  return { layout: layout, nodeWidth: nodeWidth, NODE_H: NODE_H };
})();
if (typeof module !== "undefined") module.exports = GPLayout;
