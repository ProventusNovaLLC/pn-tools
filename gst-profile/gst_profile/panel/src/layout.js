/* Layered left-to-right graph layout for pipeline graphs (Sugiyama-lite):
   longest-path layering from sources, barycenter ordering, measured node sizes.
   Pure function of the graph dict — no DOM. */
var GPLayout = (function () {
  var NODE_H = 46, H_GAP = 64, V_GAP = 20, CHAR_W = 7.4;

  function nodeWidth(el) {
    var label = Math.max((el.factory || el.gtype || "").length, (el.id || "").length);
    return Math.max(120, Math.min(250, Math.round(label * CHAR_W) + 30));
  }

  /* graph: {elements:[{id, is_bin, ...}], links:[{id, src:"el:pad", sink:"el:pad"}]} */
  function layout(graph) {
    var els = (graph.elements || []).filter(function (e) { return !e.is_bin; });
    var byId = {};
    els.forEach(function (e) { byId[e.id] = e; });
    var links = (graph.links || []).filter(function (l) {
      return byId[srcEl(l)] && byId[sinkEl(l)];
    });

    // element-level adjacency
    var out = {}, inn = {};
    els.forEach(function (e) { out[e.id] = []; inn[e.id] = []; });
    links.forEach(function (l) {
      var a = srcEl(l), b = sinkEl(l);
      if (out[a].indexOf(b) < 0) out[a].push(b);
      if (inn[b].indexOf(a) < 0) inn[b].push(a);
    });

    // longest-path layering from sources; DFS with an on-stack guard breaks cycles
    var layer = {}, onStack = {};
    function rank(id) {
      if (layer[id] !== undefined) return layer[id];
      if (onStack[id]) return 0;                       // cycle: treat the back-edge as absent
      onStack[id] = true;
      var r = 0;
      inn[id].forEach(function (up) { r = Math.max(r, rank(up) + 1); });
      onStack[id] = false;
      layer[id] = r;
      return r;
    }
    els.forEach(function (e) { rank(e.id); });

    // group by layer, initial order = insertion order
    var layers = [];
    els.forEach(function (e) {
      var L = layer[e.id];
      (layers[L] = layers[L] || []).push(e.id);
    });
    for (var i = 0; i < layers.length; i++) layers[i] = layers[i] || [];

    // barycenter ordering sweeps (down then up, twice)
    var pos = {};
    function reindex() {
      layers.forEach(function (ids) { ids.forEach(function (id, k) { pos[id] = k; }); });
    }
    reindex();
    function sweep(neigh) {
      layers.forEach(function (ids) {
        var keyed = ids.map(function (id) {
          var ns = neigh[id].filter(function (n) { return pos[n] !== undefined; });
          var bary = ns.length ? ns.reduce(function (a, n) { return a + pos[n]; }, 0) / ns.length : pos[id];
          return { id: id, k: bary };
        });
        keyed.sort(function (a, b) { return a.k - b.k || pos[a.id] - pos[b.id]; });
        ids.length = 0;
        keyed.forEach(function (e) { ids.push(e.id); });
        reindex();
      });
    }
    sweep(inn); sweep(out); sweep(inn); sweep(out);

    // coordinates: per-layer x from cumulative max widths; y centered per layer
    var layerW = layers.map(function (ids) {
      return ids.reduce(function (m, id) { return Math.max(m, nodeWidth(byId[id])); }, 0);
    });
    var xs = [], x = 0;
    for (i = 0; i < layers.length; i++) { xs.push(x); x += layerW[i] + H_GAP; }
    var maxCount = layers.reduce(function (m, ids) { return Math.max(m, ids.length); }, 0);
    var totalH = maxCount * NODE_H + (maxCount - 1) * V_GAP;

    var nodes = {}, nodeList = [];
    layers.forEach(function (ids, L) {
      var colH = ids.length * NODE_H + (ids.length - 1) * V_GAP;
      var y0 = (totalH - colH) / 2;
      ids.forEach(function (id, k) {
        var w = nodeWidth(byId[id]);
        var n = { id: id, el: byId[id], x: xs[L] + (layerW[L] - w) / 2, y: y0 + k * (NODE_H + V_GAP), w: w, h: NODE_H, layer: L };
        nodes[id] = n; nodeList.push(n);
      });
    });

    // edge endpoints: distribute multiple links on a node side evenly
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

    return { nodes: nodeList, byId: nodes, edges: edges,
             width: x - H_GAP + 4, height: Math.max(totalH, NODE_H) + 4 };
  }

  function srcEl(l) { return String(l.src || "").split(":")[0]; }
  function sinkEl(l) { return String(l.sink || "").split(":")[0]; }

  return { layout: layout, nodeWidth: nodeWidth, NODE_H: NODE_H };
})();
if (typeof module !== "undefined") module.exports = GPLayout;
