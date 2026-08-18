import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const GPLayout = require("../../gst_profile/panel/src/layout.js");

const el = (id, extra) => Object.assign({ id, factory: id.replace(/\d+$/, ""), is_bin: false }, extra);
const link = (src, sink) => ({ id: src + "->" + sink, src, sink });

test("a chain lays out left to right, one node per layer", () => {
  const g = {
    elements: [el("src0"), el("conv0"), el("sink0")],
    links: [link("src0:src", "conv0:sink"), link("conv0:src", "sink0:sink")],
  };
  const L = GPLayout.layout(g);
  const by = L.byId;
  assert.equal(by.src0.layer, 0);
  assert.equal(by.conv0.layer, 1);
  assert.equal(by.sink0.layer, 2);
  assert.ok(by.src0.x < by.conv0.x && by.conv0.x < by.sink0.x);
  assert.equal(L.edges.length, 2);
});

test("a tee branch shares a layer and both edges resolve", () => {
  const g = {
    elements: [el("src0"), el("tee0"), el("enc0"), el("disp0"), el("sink0")],
    links: [link("src0:src", "tee0:sink"), link("tee0:src_0", "enc0:sink"),
            link("tee0:src_1", "disp0:sink"), link("enc0:src", "sink0:sink")],
  };
  const L = GPLayout.layout(g);
  assert.equal(L.byId.enc0.layer, L.byId.disp0.layer);
  assert.equal(L.byId.sink0.layer, 3);
  const fromTee = L.edges.filter((e) => e.src === "tee0");
  assert.equal(fromTee.length, 2);
  assert.notEqual(fromTee[0].y0, fromTee[1].y0);   // distributed on the node side
});

test("bins are dropped; links touching unknown elements are ignored", () => {
  const g = {
    elements: [el("pipeline0", { is_bin: true }), el("a0"), el("b0")],
    links: [link("a0:src", "b0:sink"), link("ghost0:src", "a0:sink")],
  };
  const L = GPLayout.layout(g);
  assert.equal(L.nodes.length, 2);
  assert.equal(L.edges.length, 1);
});

test("a cycle terminates and still assigns every layer", () => {
  const g = {
    elements: [el("a0"), el("b0"), el("c0")],
    links: [link("a0:src", "b0:sink"), link("b0:src", "c0:sink"), link("c0:src", "a0:sink")],
  };
  const L = GPLayout.layout(g);
  assert.equal(L.nodes.length, 3);
  assert.ok(L.nodes.every((n) => n.layer >= 0));
});

test("layout is deterministic for the same graph", () => {
  const g = {
    elements: [el("src0"), el("tee0"), el("q0"), el("q1"), el("sink0"), el("sink1")],
    links: [link("src0:src", "tee0:sink"), link("tee0:src_0", "q0:sink"), link("tee0:src_1", "q1:sink"),
            link("q0:src", "sink0:sink"), link("q1:src", "sink1:sink")],
  };
  assert.deepEqual(GPLayout.layout(g), GPLayout.layout(g));
});

test("node width tracks the longer of factory and instance name, clamped", () => {
  assert.equal(GPLayout.nodeWidth({ id: "a", factory: "b" }), 120);
  assert.ok(GPLayout.nodeWidth({ id: "averyveryverylongelementname0", factory: "x" }) > 120);
  assert.equal(GPLayout.nodeWidth({ id: "x".repeat(80), factory: "" }), 250);
});
