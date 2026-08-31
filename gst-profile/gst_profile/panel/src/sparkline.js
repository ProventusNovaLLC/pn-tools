/* Small canvas drawing helpers shared by the inspector sparklines, the timeline,
   the system lanes and the scrubber. All draw in CSS pixels; setup() handles DPR. */
var GPDraw = (function () {
  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
  }

  /* Size a canvas to its CSS box at device resolution; returns a ctx scaled to CSS px. */
  function setup(canvas) {
    var r = canvas.getBoundingClientRect();
    var dpr = window.devicePixelRatio || 1;
    var w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr; canvas.height = h * dpr;
    }
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx: ctx, w: w, h: h };
  }

  function finiteMax(vals, floor) {
    var m = floor || 0;
    for (var i = 0; i < vals.length; i++) if (typeof vals[i] === "number" && vals[i] > m) m = vals[i];
    return m;
  }

  /* Polyline of a numeric-or-null series inside (x,y,w,h); null gaps break the line. */
  function line(ctx, vals, x, y, w, h, max, color, fill) {
    if (!vals.length || max <= 0) return;
    var dx = vals.length > 1 ? w / (vals.length - 1) : 0;
    ctx.save();
    ctx.lineWidth = 1.6; ctx.strokeStyle = color; ctx.lineJoin = "round";
    var started = false;
    ctx.beginPath();
    for (var i = 0; i < vals.length; i++) {
      var v = vals[i];
      if (typeof v !== "number") { started = false; continue; }
      var px = x + i * dx, py = y + h - Math.min(1, v / max) * h;
      if (!started) { ctx.moveTo(px, py); started = true; } else ctx.lineTo(px, py);
    }
    ctx.stroke();
    if (fill) {
      ctx.globalAlpha = 0.13; ctx.fillStyle = color;
      ctx.lineTo(x + (vals.length - 1) * dx, y + h); ctx.lineTo(x, y + h);
      ctx.closePath(); ctx.fill();
    }
    ctx.restore();
  }

  /* p50–p95 band + p95 line. */
  function band(ctx, lo, hi, x, y, w, h, max, color) {
    if (!hi.length || max <= 0) return;
    var dx = hi.length > 1 ? w / (hi.length - 1) : 0;
    ctx.save();
    ctx.globalAlpha = 0.18; ctx.fillStyle = color;
    ctx.beginPath();
    var i, v, drew = false;
    for (i = 0; i < hi.length; i++) {
      v = typeof hi[i] === "number" ? hi[i] : 0;
      var py = y + h - Math.min(1, v / max) * h;
      if (!drew) { ctx.moveTo(x + i * dx, py); drew = true; } else ctx.lineTo(x + i * dx, py);
    }
    for (i = lo.length - 1; i >= 0; i--) {
      v = typeof lo[i] === "number" ? lo[i] : 0;
      ctx.lineTo(x + i * dx, y + h - Math.min(1, v / max) * h);
    }
    ctx.closePath(); ctx.fill();
    ctx.restore();
    line(ctx, hi, x, y, w, h, max, color, false);
  }

  /* Vertical marker at series index i. */
  function cursor(ctx, i, n, x, y, w, h, color) {
    if (n < 1 || i < 0) return;
    var px = x + (n > 1 ? (i / (n - 1)) * w : 0);
    ctx.save();
    ctx.strokeStyle = color; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(px, y); ctx.lineTo(px, y + h); ctx.stroke();
    ctx.restore();
  }

  function fmt(v, unit) {
    if (typeof v !== "number") return "–";
    var a = Math.abs(v);
    var s = a >= 100 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : v.toFixed(2);
    return s + (unit || "");
  }

  function fmtBytes(v) {
    if (typeof v !== "number") return "–";
    if (v >= 1e9) return (v / 1e9).toFixed(2) + " GB/s";
    if (v >= 1e6) return (v / 1e6).toFixed(1) + " MB/s";
    if (v >= 1e3) return (v / 1e3).toFixed(1) + " kB/s";
    return v.toFixed(0) + " B/s";
  }

  function fmtClock(secs) {
    if (typeof secs !== "number" || secs < 0) secs = 0;
    var m = Math.floor(secs / 60), s = Math.floor(secs % 60);
    return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
  }

  return { css: css, setup: setup, finiteMax: finiteMax, line: line, band: band,
           cursor: cursor, fmt: fmt, fmtBytes: fmtBytes, fmtClock: fmtClock };
})();
if (typeof module !== "undefined") module.exports = GPDraw;
