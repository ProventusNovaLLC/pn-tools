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

test("a linear chain is drawn straight; every node shares one y", () => {
  const g = {
    elements: [el("a0"), el("b0"), el("c0"), el("d0")],
    links: [link("a0:src", "b0:sink"), link("b0:src", "c0:sink"), link("c0:src", "d0:sink")],
  };
  const L = GPLayout.layout(g);
  const ys = ["a0", "b0", "c0", "d0"].map((id) => L.byId[id].y);
  ys.forEach((y) => assert.ok(Math.abs(y - ys[0]) < 0.5, "chain node off the line: " + y + " vs " + ys[0]));
});

test("a fan-in centers the mux between its inputs", () => {
  const g = {
    elements: [el("s0"), el("s1"), el("mux0"), el("sink0")],
    links: [link("s0:src", "mux0:sink_0"), link("s1:src", "mux0:sink_1"), link("mux0:src", "sink0:sink")],
  };
  const L = GPLayout.layout(g);
  const mid = (L.byId.s0.y + L.byId.s1.y) / 2;
  assert.ok(Math.abs(L.byId.mux0.y - mid) < 1, "mux not centered: " + L.byId.mux0.y + " vs " + mid);
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

test("disconnected pipelines stack vertically without overlapping", () => {
  const g = {
    elements: [el("srcA0"), el("sinkA0"), el("srcB0"), el("sinkB0")],
    links: [link("srcA0:src", "sinkA0:sink"), link("srcB0:src", "sinkB0:sink")],
  };
  const L = GPLayout.layout(g);
  const aTop = Math.min(L.byId.srcA0.y, L.byId.sinkA0.y);
  const aBot = Math.max(L.byId.srcA0.y, L.byId.sinkA0.y) + GPLayout.NODE_H;
  const bTop = Math.min(L.byId.srcB0.y, L.byId.sinkB0.y);
  const bBot = Math.max(L.byId.srcB0.y, L.byId.sinkB0.y) + GPLayout.NODE_H;
  const separated = aBot <= bTop || bBot <= aTop;      // one band entirely above the other
  assert.ok(separated, "component bands overlap vertically");
});

test("a source and its chain do not share a layer band with an unrelated pipeline", () => {
  // two independent chains; each source is layer 0 but they must not stack in one column blob
  const g = {
    elements: [el("camA0"), el("encA0"), el("camB0"), el("encB0")],
    links: [link("camA0:src", "encA0:sink"), link("camB0:src", "encB0:sink")],
  };
  const L = GPLayout.layout(g);
  // both chains are straight, and the two chains occupy different y bands
  assert.ok(Math.abs(L.byId.camA0.y - L.byId.encA0.y) < 0.5);
  assert.ok(Math.abs(L.byId.camB0.y - L.byId.encB0.y) < 0.5);
  assert.notEqual(L.byId.camA0.y, L.byId.camB0.y);
});

test("capture pipelines stack above the derived pipelines they feed", () => {
  // a camera chain (real source) and an encoder chain (fed by an interpipe bridge)
  const g = {
    elements: [el("nvarguscamerasrc0"), el("capsfilter0"), el("interpipesink0"),
               el("interpipesrc0"), el("nvv4l2h264enc0"), el("interpipesink3")],
    links: [link("nvarguscamerasrc0:src", "capsfilter0:sink"), link("capsfilter0:src", "interpipesink0:sink"),
            link("interpipesrc0:src", "nvv4l2h264enc0:sink"), link("nvv4l2h264enc0:src", "interpipesink3:sink")],
  };
  const L = GPLayout.layout(g);
  const cameraTop = L.byId.nvarguscamerasrc0.y;
  const encoderTop = L.byId.interpipesrc0.y;
  assert.ok(cameraTop < encoderTop, "camera pipeline should sit above the encoder it feeds");
});

test("isolated nodes each become their own stacked component", () => {
  const g = {
    elements: [el("chain0"), el("chain1"), el("lonely0"), el("lonely1")],
    links: [link("chain0:src", "chain1:sink")],
  };
  const L = GPLayout.layout(g);
  assert.equal(L.nodes.length, 4);
  // the two lonely nodes sit at distinct y (stacked), both below the 2-node chain
  const chainBot = Math.max(L.byId.chain0.y, L.byId.chain1.y);
  assert.ok(L.byId.lonely0.y > chainBot);
  assert.ok(L.byId.lonely1.y > chainBot);
  assert.notEqual(L.byId.lonely0.y, L.byId.lonely1.y);
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
  assert.equal(GPLayout.nodeWidth({ id: "a", factory: "b" }), 140);
  assert.ok(GPLayout.nodeWidth({ id: "averyveryverylongelementname0", factory: "x" }) > 140);
  assert.equal(GPLayout.nodeWidth({ id: "x".repeat(80), factory: "" }), 270);
});
