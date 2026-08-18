import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const GPStore = require("../../gst_profile/panel/src/store.js");

function tick(t, els, links, pipe, sys) {
  return { t, rows: 0, row: { elements: els || {}, links: links || {}, pipeline: pipe || {}, system: sys || {} } };
}

test("ticks append columns aligned with t", () => {
  GPStore.initSession({}, "live");
  assert.equal(GPStore.applyTick(tick(0.0, { a: { proc_ms_p95: 2.5, buffers: 8 } }, { l1: { fps: 30, bytes_s: 100, stalled: false } }, { latency_ms_p95: 5.0 })), true);
  assert.equal(GPStore.applyTick(tick(0.25, { a: { proc_ms_p95: 3.0, buffers: 7 } }, { l1: { fps: 29, bytes_s: 90, stalled: false } }, { latency_ms_p95: 6.0 })), true);
  const s = GPStore.state.session.series;
  assert.deepEqual(s.t, [0.0, 0.25]);
  assert.deepEqual(s.elements.a.proc_ms_p95, [2.5, 3.0]);
  assert.deepEqual(s.links.l1.fps, [30, 29]);
  assert.deepEqual(s.pipeline.latency_ms_p95, [5.0, 6.0]);
});

test("an element appearing mid-capture is backfilled with nulls", () => {
  GPStore.initSession({}, "live");
  GPStore.applyTick(tick(0.0, { a: { proc_ms_p95: 1 } }));
  GPStore.applyTick(tick(0.25, { a: { proc_ms_p95: 2 }, b: { proc_ms_p95: 9 } }));
  const s = GPStore.state.session.series;
  assert.deepEqual(s.elements.b.proc_ms_p95, [null, 9]);
  assert.deepEqual(s.elements.a.proc_ms_p95, [1, 2]);
});

test("an element missing from a later tick gets null, not a crash", () => {
  GPStore.initSession({}, "live");
  GPStore.applyTick(tick(0.0, { a: { cpu_pct: 10 } }));
  GPStore.applyTick(tick(0.25, {}));
  assert.deepEqual(GPStore.state.session.series.elements.a.cpu_pct, [10, null]);
});

test("replayed or stale ticks are dropped (reconnect dedup)", () => {
  GPStore.initSession({}, "live");
  GPStore.applyTick(tick(0.0, { a: { buffers: 1 } }));
  GPStore.applyTick(tick(0.25, { a: { buffers: 2 } }));
  assert.equal(GPStore.applyTick(tick(0.25, { a: { buffers: 99 } })), false);
  assert.equal(GPStore.applyTick(tick(0.0, { a: { buffers: 99 } })), false);
  assert.deepEqual(GPStore.state.session.series.elements.a.buffers, [1, 2]);
});

test("cursor: live pins to the newest window, frozen stays put", () => {
  GPStore.initSession({}, "live");
  GPStore.applyTick(tick(0.0, {}));
  GPStore.applyTick(tick(0.25, {}));
  assert.equal(GPStore.cursorIndex(), 1);
  GPStore.setCursor(0, false);
  GPStore.applyTick(tick(0.5, {}));
  assert.equal(GPStore.cursorIndex(), 0);
  GPStore.setCursor(-1, true);
  assert.equal(GPStore.cursorIndex(), 2);
});

test("initSession normalizes a bare-series session (columnar arrays exist)", () => {
  GPStore.initSession({ series: { t: [0], elements: {}, links: {} } }, "replay");
  const s = GPStore.state.session.series;
  assert.deepEqual(s.pipeline.latency_ms_p95, []);
  assert.deepEqual(s.system.gr3d_pct, []);
});

test("deriveVerdict builds header + hot from the series of a dropped file", () => {
  const session = {
    series: { t: [0, 0.25], elements: {
      hot0: { proc_ms_p95: [30, 30] }, cold0: { proc_ms_p95: [10, 10] } },
      links: {}, pipeline: { latency_ms_p95: [40, 44] }, system: {} },
    findings: [{ id: "F-1", rule: "ZC", severity: "info" }],
  };
  const v = GPStore.deriveVerdict(session);
  assert.match(v.header, /pipeline latency p95 44\.0 ms/);
  assert.equal(v.hot[0].element, "hot0");
  assert.equal(Math.round(v.hot[0].share_pct), 75);
  assert.equal(v.findings.length, 1);
  assert.equal(v.has_high_or_medium, false);
});
