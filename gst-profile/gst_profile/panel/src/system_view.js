/* System tab: per-core CPU and hardware-unit lanes (GR3D / VIC / NVENC / NVDEC / EMC)
   on the shared axis, 0–100 % fixed scale. A unit whose series is all null renders as
   an explicit "not available on this board" lane instead of silent zeros. */
var GPSystem = (function () {
  var LANE_H = 34, GUTTER = 170, PAD_T = 6;
  var UNITS = [
    { key: "cpu_pct", label: "cpu total" },
    { key: "gr3d_pct", label: "GR3D (gpu)" },
    { key: "vic_pct", label: "VIC" },
    { key: "nvenc_pct", label: "NVENC" },
    { key: "nvdec_pct", label: "NVDEC" },
    { key: "emc_pct", label: "EMC (memory)" },
  ];

  function coreSeries(sys) {
    var per = sys.cpu_pct_per_core || [];
    var ncores = 0;
    per.forEach(function (row) { if (Array.isArray(row)) ncores = Math.max(ncores, row.length); });
    var out = [];
    for (var c = 0; c < ncores; c++) {
      out.push({ label: "cpu core " + c, vals: per.map(function (row) {
        return Array.isArray(row) && typeof row[c] === "number" ? row[c] : null; }) });
    }
    return out;
  }

  function render(state) {
    var canvas = document.getElementById("sys");
    if (!state.session || !document.getElementById("view-system").classList.contains("active")) return;
    var d = GPDraw.setup(canvas), ctx = d.ctx;
    ctx.clearRect(0, 0, d.w, d.h);
    var s = state.session.series, sys = s.system, n = s.t.length;
    var plotW = d.w - GUTTER - 14;
    var ink2 = GPDraw.css("--ink2"), ink3 = GPDraw.css("--ink3"), border = GPDraw.css("--border");
    var jetson = (state.session.target || {}).platform === "jetson";

    var lanes = coreSeries(sys).map(function (c) { return { label: c.label, vals: c.vals, avail: true }; });
    UNITS.forEach(function (u) {
      if (u.key !== "cpu_pct" && !jetson && !GPStore.numeric(sys[u.key] || []).length) return;   // tegra lanes only where expected
      var vals = sys[u.key] || [];
      lanes.push({ label: u.label, vals: vals, avail: !!GPStore.numeric(vals).length });
    });

    if (!n || !lanes.length) {
      ctx.fillStyle = ink3; ctx.font = "13px system-ui";
      ctx.fillText("no system series on this capture: see `gst-profile check`", 16, 26);
      return;
    }

    lanes.forEach(function (lane, li) {
      var y = PAD_T + li * LANE_H;
      if (y + LANE_H > d.h) return;
      ctx.fillStyle = ink2; ctx.font = "11.5px ui-monospace, Menlo, monospace";
      ctx.fillText(lane.label, 10, y + 14);
      ctx.strokeStyle = border; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(GUTTER, y + LANE_H - 6.5); ctx.lineTo(GUTTER + plotW, y + LANE_H - 6.5); ctx.stroke();
      if (!lane.avail) {
        ctx.fillStyle = ink3; ctx.font = "11px system-ui";
        ctx.fillText("not available on this board: see `gst-profile check`", GUTTER + 6, y + 14);
        return;
      }
      var i = GPStore.cursorIndex();
      var v = lane.vals[i];
      GPDraw.line(ctx, lane.vals, GUTTER, y + 3, plotW, LANE_H - 10, 100, GPDraw.css("--info"), true);
      ctx.fillStyle = ink3; ctx.font = "10.5px ui-monospace, Menlo, monospace";
      ctx.fillText(GPDraw.fmt(v, "%"), 10 + 92, y + 14);          // value at cursor, in the gutter
    });

    var plotH = Math.min(d.h - PAD_T, lanes.length * LANE_H);
    GPDraw.cursor(ctx, GPStore.cursorIndex(), n, GUTTER, PAD_T, plotW, plotH, ink2);
  }

  return { render: render };
})();
if (typeof module !== "undefined") module.exports = GPSystem;
