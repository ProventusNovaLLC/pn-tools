# gst-profile rules: per-rule reference

Source of truth: `gst-profile/gst_profile/rules.py`. Thirteen rules, listed
below in `ALL_RULES` order (the same order `run_rules()` evaluates them in;
final output order is by severity then impact, not this order). Every field
name here (evidence keys, `fix_patch` kinds, evidence dict shapes) is
copied from `rules.py` and cross-checked against a real finding in
`gst-profile/tests/fixtures/orin-nx-jp6-zc-break.json`.

## Severity gating (read this first)

A rule's Python source hard-codes an intended severity (`high`/`medium`/
`info`), but `run_rules()` runs every finding through a gate
(`rules.py::_gate`) before it ships:

- **HOT and OK** are measurement, not diagnosis: they always ship at their
  coded `info` severity with `heuristic: false`.
- **Every other rule's `high`/`medium` severity only survives the gate if
  the rule's id is a key in `VERIFIED_RULES`**: a bench-verified allowlist
  populated by a golden bad/good pipeline pair on named hardware (see
  `bench/`). As of this write, `VERIFIED_RULES = {"ZC": [...], "SW": [...],
  "QUEUE": [...]}`, all `["orin-nx-jp6-r36.4"]`. A rule not in that dict has
  its finding downgraded to `severity: "info"`, `heuristic: true`,
  `verified_on: []`, regardless of what severity string is in the Python
  source.
- A few rules (**CAPS, CPU, HW**) are coded `severity="info"` directly in
  the source; they were never candidates for high/medium and the gate
  just marks them `heuristic: true`.
- `OK` is dropped from the finding list entirely if any other diagnostic
  rule fired (even an info-level heuristic): the verdict never says
  "you're fine" and "here's a problem" in the same breath.

**Do not report a severity the tool doesn't emit.** Only ZC, SW, and QUEUE
can carry `high`/`medium` in the shipped tool today; every other rule you
see in a session's `findings` array is `info` and `heuristic: true`.

`verified_on` names where the *rule* was bench-verified, not where *this
capture* ran: a bench-verified rule reports its real `high`/`medium`
severity wherever it fires, even on hardware other than the one it was
validated on, e.g. a QUEUE finding from a capture on a generic x86 box
still ships `severity: "medium"`, `heuristic: false`,
`verified_on: ["orin-nx-jp6-r36.4"]`, because the QUEUE rule's logic
(no thread boundary before the encoder/sink) doesn't depend on the
platform it happens to run against.

Two honest limits, verbatim from `gst-profile/README.md`:

> Two honest limits worth knowing: **SYNC** (`sync=true` on a live sink)
> can't yet be detected from a `run`-mode capture: `sync=true` is the
> `GstBaseSink` default, so a dot dump never records it as a set property;
> that needs a rule-logic revision, so SYNC stays heuristic. And on L4T
> R36, `tegrastats` reports no per-engine load for NVENC/NVDEC/VIC (only
> GPU, CPU, thermals, power). That utilization number isn't exposed
> anywhere on the platform, so the **VIC**/**HW** rules and the
> encoder-engine signal stay heuristic, and the System tab shows "not
> available on this board" for those lanes.

That second limit is directly visible in the fixtures: in
`orin-nx-jp6-zc-break.json`, `series.system.vic_pct`, `nvenc_pct`,
`nvdec_pct`, and `emc_pct` are `null` across every window of the run, while
`gr3d_pct` (GPU) and `cpu_pct` carry real numbers: that's the R36 signal
gap, in the data.

---

## HOT: where the time goes

**Symptom:** none by itself: HOT is the always-on "where the time goes"
ranking that heads every verdict, not a problem indicator.

**Evidence it reads:** `Analysis.hot_share()`, built from
`series.elements.<id>.proc_ms_p95` (p95'd per element across the run) for
every non-bin element (`graph.elements[].is_bin == false`). Ranks elements
by that p95 time and computes each one's percent share of the summed p95
times across all elements.

**Emits (`finding.evidence`):** `{"ranking": [[element_id, proc_ms_p95,
share_pct], ...]}`, top 6 elements, e.g. from the ZC-break fixture:
`["nvv4l2h264enc0", 9.427, 33.3]`.

**Why it matters:** names the element to start optimizing on.

**Fix:** `fix_text`: "Start optimisation here; the rows below rank the
rest." No `fix_patch` (nothing to apply; it's a pointer, not a change).

**Verified state:** always `severity: "info"`, `heuristic: false`,
`verified_on: []`. Not gated: HOT is exempted from the bench-verification
gate because it's measurement, not a claim.

---

## OK: pipeline is within frame budget

**Symptom:** the device-side pipeline keeps up with the source frame rate;
if the user's end-to-end latency still looks bad, the bottleneck is
downstream (network/SFU/remote decode), not this pipeline.

**Evidence it reads:** `Analysis.latency_ms_p95` (p95 of
`series.pipeline.latency_ms_p95`) compared against
`Analysis.frame_period_ms` (derived from the fastest source link's fps in
`series.links.*.fps`). Fires only when `latency_ms_p95 <= frame_period_ms`.

**Emits:** `{"latency_ms_p95": ..., "frame_period_ms": ...}`.

**Why it matters:** tells the user where NOT to keep looking.

**Fix:** `fix_text`: "Profile the network path (RTT to your server) and
remote decode; the capture/encode side is not the bottleneck." No
`fix_patch`.

**Verified state:** always `severity: "info"`, `heuristic: false`. Dropped
from the findings list entirely if any other rule (besides HOT) also
fired. See the gating note above.

---

## ZC: zero-copy break (bench-verified, high)

**Symptom:** buffers leave GPU/dmabuf memory and come back: a CPU↔GPU
copy on every frame, burning bandwidth and latency. In the live panel this
is a gray (sysmem) segment sitting inside an otherwise NVMM/dmabuf-colored
path.

**Evidence it reads:** walks `Analysis.links` for links where
`memory == "sysmem"` **and** the payload is a raw frame (`media in ("",
"video/x-raw")`): an encoded-stream sysmem link (h264/h265/jpeg) between
hardware codecs is normal and is explicitly excluded. For each raw sysmem
link it walks the link graph upstream and downstream (via
`Analysis.links`, following `src_el`/`sink_el`) looking for the nearest
element on each side that sits across an NVMM- or dmabuf-memory link
(`link.memory in ("nvmm", "dmabuf")`): those two elements bound the
"island." Also reads the sysmem link's own sink element's `cpu_pct` (or
its source's, as fallback) (`series.elements.<id>.cpu_pct`, max).

**Emits:** `{"sysmem_link": <link id>, "hw_upstream": <element id>,
"hw_downstream": <element id>, "offender_cpu_pct": <float|null>}`, from
the fixture: `{"sysmem_link": "capsfilter3:src->nvvconv2:sink",
"hw_upstream": "capsfilter1", "hw_downstream": "capsfilter4",
"offender_cpu_pct": 79.6}`.

**Why it matters:** "A CPU<->GPU copy on every frame costs bandwidth and
latency; NVMM/dmabuf should stay on the GPU end to end."

**Fix:** `fix_text`: "Keep the path in device memory across
`<src>-><sink>` (use nvvidconv, or negotiate NVMM caps so no element
copies to system memory)." `fix_patch`: `{"kind": "set-caps", "link":
<link id>, "to": "video/x-raw(memory:NVMM)"}`.

**Verified state:** coded `severity="high"`; ZC is in `VERIFIED_RULES`
(`["orin-nx-jp6-r36.4"]`), so it ships at full severity:
`severity: "high"`, `heuristic: false`, `verified_on:
["orin-nx-jp6-r36.4"]`, whenever it fires.

---

## SW: software element with a hardware equivalent (bench-verified, medium)

**Symptom:** an element runs in software (CPU) even though the platform
has a dedicated hardware block for the same job: burns CPU, adds latency.

**Evidence it reads:** every non-bin element's `factory`
(`graph.elements[].factory`) checked against a per-platform swap table
(`HW_SWAP[a.platform]`, `Analysis.platform` from `target.platform`):
- `jetson`: `videoconvert`→`nvvidconv`, `videoscale`→`nvvidconv`,
  `x264enc`→`nvv4l2h264enc`, `x265enc`→`nvv4l2h265enc`,
  `jpegdec`→`nvjpegdec`, `jpegenc`→`nvjpegenc`,
  `avdec_h264`/`avdec_h265`→`nvv4l2decoder`.
- `mediatek`: `x264enc`→`v4l2h264enc`, `x265enc`→`v4l2h265enc`,
  `videoconvert`→`v4l2convert`, `jpegdec`→`v4l2jpegdec`.

Also reads the element's `cpu_pct` and `proc_ms_p95`
(`series.elements.<id>.cpu_pct` / `.proc_ms_p95`) for evidence context.

**Emits:** `{"factory": ..., "hardware_equivalent": ..., "cpu_pct": ...,
"proc_ms_p95": ...}`, from the fixture: `{"factory": "videoconvert",
"hardware_equivalent": "nvvidconv", "cpu_pct": 79.6, "proc_ms_p95":
4.66981}`.

**Why it matters:** "A software element burns CPU and adds latency where
the SoC has a dedicated block."

**Fix:** `fix_text`: "Replace `<factory>` with `<hw factory>`."
`fix_patch`: `{"kind": "replace-element", "element": <id>, "with": <hw
factory>}`.

**Verified state:** coded `severity="medium"`; SW is in `VERIFIED_RULES` →
ships at `severity: "medium"`, `heuristic: false`, `verified_on:
["orin-nx-jp6-r36.4"]`.

---

## QUEUE: no thread boundary before encoder/sink (bench-verified, medium)

**Symptom:** no queue element anywhere upstream of the encoder/sink/pay/
mux: the whole pipeline runs on one streaming thread, so a stall anywhere
stalls everything.

**Evidence it reads:** scans every non-bin element's `factory`
(`graph.elements[].factory`) for one starting with `queue`
(`has_queue`), and separately for any element whose factory contains
`enc`, `sink`, `pay`, or `mux` (`heavy`, the target list `ENC_SINK`). Fires
on the first heavy element found only when `has_queue` is false.

**Emits:** `{"heavy_element": <id>, "queues_present": 0}`, from the
fixture: `{"heavy_element": "nvv4l2h264enc0", "queues_present": 0}`.

**Why it matters:** "Without a queue the source, conversion and encode
share a single streaming thread, so any stall in one stalls all."

**Fix:** `fix_text`: "Insert a queue upstream of `<heavy_element>` to give
it its own thread."
`fix_patch`: `{"kind": "insert-element", "before": <heavy_element>,
"element": "queue"}`.

**Verified state:** coded `severity="medium"`; QUEUE is in
`VERIFIED_RULES` → ships at `severity: "medium"`, `heuristic: false`,
`verified_on: ["orin-nx-jp6-r36.4"]`.

---

## SYNC: sync=true on a live sink (heuristic: known blind spot)

**Symptom (intended):** a live-path sink holding buffers to the clock
(`sync=true`) adds up to a frame of latency.

**Evidence it reads:** every non-bin element whose `factory` contains
`sink`, checking `props.get("sync")` (`graph.elements[].props`). It only
fires when the `sync` key is present and not `None`, and its (lowercased,
stringified) value is one of `"true"`, `"1"`, `""`; if the key is absent
(`None`) the rule explicitly skips it ("unknown; don't guess", see the
code comment).

**Emits:** `{"sync": <raw prop value>}`.

**Why it matters:** "Clock-synced rendering holds each buffer to its
timestamp, adding up to a frame of latency; live/teleop paths usually want
sync=false."

**Fix:** `fix_text`: "Set sync=false on `<id>` for a low-latency live
path." `fix_patch`: `{"kind": "set-property", "element": <id>, "property":
"sync", "value": "false"}`.

**Verified state:** coded `severity="medium"` but SYNC is **not** in
`VERIFIED_RULES` (rules.py names it explicitly as excluded, alongside
STALL) → gated down to `severity: "info"`, `heuristic: true`,
`verified_on: []`, always.

**The blind spot, concretely:** `GstBaseSink`'s `sync` property defaults
to `true`, and a run-mode dot dump only records properties whose value
differs from the GObject default. So the actual failure case, a sink left
at the (bad, for live) default `sync=true`, is invisible to this rule; the
only case it *can* see is a `sync` value explicitly present in the dump,
which in practice means someone already set it non-default. In the
zc-break fixture, `fakesink0` carries `"props": {"sync": "FALSE", ...}`
because the launch string set `sync=false` explicitly: the healthy case,
not a finding. This is the exact gap the README calls out; a rule-logic
fix (reading the live pipeline's actual property, not just what a dot dump
captured) is needed before SYNC can be bench-verified.

---

## CAPS: back-to-back format conversions (heuristic, always info)

**Symptom:** two conversion elements in a row, or a conversion whose input
and output pixel format differ needlessly.

**Evidence it reads:** non-bin elements whose `factory` is one of
`videoconvert`, `nvvidconv`, `v4l2convert`, `videoscale` (`CONV`). For each
one, looks up its downstream elements via `Analysis.downstream()` (walks
`graph.links[].src`/`sink` for links whose `src_el == this element`) and
checks whether any downstream element's `factory` is also in `CONV`.

**Emits:** `{"element": <id>, "downstream": [<downstream element ids>]}`.

**Why it matters:** "Two conversions in a row usually means one can be
dropped or folded into the other."

**Fix:** `fix_text`: "Collapse the two conversions into one, or fix the
caps so no conversion is needed." No `fix_patch`.

**Verified state:** coded `severity="info"` directly in the source (never
a high/medium candidate) → always `severity: "info"`, `heuristic: true`,
`verified_on: []`.

---

## STALL: link stopped carrying buffers mid-run (heuristic: didn't reproduce cleanly)

**Symptom:** a link that was flowing stops flowing while the pipeline is
still in the `playing` state: either the true source starved (sensor/CSI/
driver problem) or a downstream element stopped consuming/producing.

**Evidence it reads:** `Analysis.links[].stall_interior`, derived from
`series.links.<id>.stalled` (a per-window boolean): true only for a
*sustained interior* stall (≥2 consecutive stalled windows before the
final 2 windows of the run), which distinguishes a real mid-capture stall
from ordinary teardown. To classify source vs. downstream, it checks
`Analysis.upstream(l.src_el)` (graph topology, via `graph.links`): no
upstream elements means the link's source element is a true pipeline
source.

**Emits:** `{"link": <link id>}`.

**Why it matters:** "Data stopped flowing across this link mid-capture;
upstream is not delivering buffers."

**Fix:** two variants depending on `is_source`. Source case: "Check the
sensor/driver bring-up (see the camera-bringup-debug skill); the source
stopped delivering." Non-source case: "Investigate why `<src>` stopped
producing; a downstream block-and-wait or an internal error is typical."
No `fix_patch`.

**Verified state:** coded `severity="high"` but STALL is explicitly
excluded from `VERIFIED_RULES`: the rules.py comment says it "did not
reproduce cleanly from a drop-from-start pipeline" during the bench pass →
gated down to `severity: "info"`, `heuristic: true`, `verified_on: []`,
always.

---

## VIC: VIC engine contention (heuristic: no signal on R36)

**needs:** `tegrastats` (`target.capabilities.tegrastats` must be truthy).

**Symptom (intended):** several `nvvidconv` users contending for the
shared VIC hardware converter, collapsing throughput.

**Evidence it reads:** `Analysis.system_peak["vic_pct"]` (max of
`series.system.vic_pct` across the run) and a count of non-bin elements
with `factory == "nvvidconv"`. Fires when `vic_pct >= 80` and at least one
`nvvidconv` is present.

**Emits:** `{"vic_pct": <float>, "nvvidconv_count": <int>}`.

**Why it matters:** "Multiple pipelines sharing the VIC hardware converter
contend for it; throughput can collapse several-fold."

**Fix:** `fix_text`: "Consolidate conversions or move some to GPU
(nvvidconv compute-hw=GPU), and avoid running independent nvvidconv
pipelines in parallel." No `fix_patch`. Carries a non-default `ref`:
ProventusNova's `nvvidconv-performance-multiple-gstreamer-processes` blog
post, not the generic scope link.

**Verified state:** coded `severity="medium"`; VIC is not in
`VERIFIED_RULES` → gated to `severity: "info"`, `heuristic: true`,
`verified_on: []`, always.

**No data on L4T R36:** `tegrastats` on R36 never emits a `VIC`/`VIC_FREQ`
token, so `series.system.vic_pct` is `null` across every window of every
R36 capture (confirmed in the zc-break fixture): this rule can be
`applicable()` (the `tegrastats` source is present) but can never actually
fire on R36 hardware, because `system_peak["vic_pct"]` is always `None`
there. See the README quote at the top of this file.

---

## ENC: latency-hostile encoder settings (heuristic, medium-coded)

**Symptom:** an encoder configured in a way that's fine for
offline/quality encoding but bad for a live path: B-frames (reorder
latency) or SPS/PPS not inserted per IDR (breaks mid-stream join).

**Evidence it reads:** non-bin elements whose `factory` contains `enc`.
Reads `props` (`graph.elements[].props`, lowercased keys/values) for
`bframes` (flagged if present and not `"0"`/`""`) and `insert-sps-pps`
(flagged if `"false"`/`"0"`).

**Emits:** only the bad keys found, e.g. `{"bframes": "2"}` or
`{"insert-sps-pps": "false"}` or both.

**Why it matters:** "B-frames add reorder latency; missing SPS/PPS-per-IDR
breaks mid-stream join. Live/teleop wants a low-latency encoder config."

**Fix:** `fix_text`: "For live: bframes=0, insert-sps-pps=true, a
low-latency control-rate/preset." No `fix_patch`. Carries a non-default
`ref`: ProventusNova's `reduce-gstreamer-pipeline-latency-jetson` blog
post.

**Verified state:** coded `severity="medium"`; ENC is not in
`VERIFIED_RULES` → gated to `severity: "info"`, `heuristic: true`,
`verified_on: []`, always.

---

## CPU: single element saturating a core (heuristic, always info)

**Symptom:** one element pins roughly a full CPU core, capping throughput
and adding jitter on a live path.

**Evidence it reads:** non-bin elements' `cpu_pct`
(`series.elements.<id>.cpu_pct`, max across the run) `>= 90`.

**Emits:** `{"cpu_pct": <float>}`.

**Why it matters:** "This element saturates its thread; on a live path it
caps throughput and adds jitter."

**Fix:** `fix_text`: "Offload `<id>` to a hardware block if one exists, or
give it its own queue/thread." No `fix_patch`.

**Verified state:** coded `severity="info"` directly → always `severity:
"info"`, `heuristic: true`, `verified_on: []`.

**Shared-thread aliasing:** `cpu_pct` is sampled per OS thread (`/proc`),
not per element (`model.py::ingest_cpu`). GStreamer only spawns a new
streaming thread at a `queue` (or similar); absent one, `_segment()` walks
downstream from the thread-owning element and attributes that *one*
thread's `cpu_pct` to every element in the segment, so
`series.elements.*.cpu_pct` is identical across all of them by
construction. This isn't a sampling coincidence. If that shared value is
`>= 90`, CPU fires once per element in the segment, which reads like
several bottlenecks but is really one signal: that shared thread is
saturated. Treat a run of identical `cpu_pct` across adjacent, queue-less
elements as one finding, not N.

---

## HW: hardware unit saturated (heuristic: partial signal on R36)

**needs:** `tegrastats` (`target.capabilities.tegrastats` must be truthy).

**Symptom:** a fixed hardware block (NVENC encoder, GPU/GR3D, or memory/
EMC) pegged at or near 100%: it bounds pipeline throughput no matter how
much CPU headroom is left.

**Evidence it reads:** `Analysis.system_peak` for three keys:
`nvenc_pct` ("NVENC encoder"), `gr3d_pct` ("GPU (GR3D)"), `emc_pct`
("memory (EMC)"), each the max of the corresponding `series.system.*`
array. Fires (one finding per unit) when a value is present and `>= 95`.

**Emits:** one finding per saturated unit, e.g. `{"gr3d_pct": 97.2}`.

**Why it matters:** "The `<unit>` block is maxed out; it bounds pipeline
throughput regardless of CPU headroom."

**Fix:** `fix_text`: "Reduce resolution/framerate/bitrate feeding the
`<unit>`, or split the load." No `fix_patch`.

**Verified state:** coded `severity="info"` directly → always `severity:
"info"`, `heuristic: true`, `verified_on: []`.

**Partial signal on R36:** in the zc-break fixture (an R36 board), of the
three keys this rule reads, only `gr3d_pct` (GPU) carries real numbers:
`nvenc_pct` and `emc_pct` are `null` across every window. The encoder-
engine signal this rule needs is exactly the one the README calls out as
absent on L4T R36 (`tegrastats` prints no per-engine NVENC/NVDEC/VIC
load); in practice this rule can only ever report on GPU saturation on
that platform.

---

## QLEAK: queue backpressure (currently a no-op stub)

**needs:** `queue_levels` (`target.capabilities.queue_levels`).

**Symptom (intended, per the class docstring):** "A queue pinned near its
max upstream of a slow element = backpressure (run mode only)."

**Current state (read this before citing QLEAK to a user):** its
`evaluate()` body is a placeholder. It loops over non-bin elements whose
`factory` starts with `queue`, `cpu_pct is None`, and `buffers` is
truthy, and does nothing (`pass`): the loop body has a literal comment,
`"placeholder; queue_levels arrive via series in a later capability"`. The
function always returns `[]`. **QLEAK never emits a finding in the shipped
tool, regardless of the session content.**

Separately, `queue_levels` is `false` in both example fixtures
(`target.capabilities.queue_levels`): the capability this rule `needs` is
not currently produced by any capture path either, so `applicable()`
returns false in practice too. Do not describe QLEAK's evidence, fix, or
severity to a user as if it currently does something: it is reserved for
a future capability, not a working diagnostic.

---

## Quick-reference table

| id    | coded severity | in `VERIFIED_RULES`? | shipped severity today | `needs` |
|-------|-----------------|----------------------|--------------------------|---------|
| HOT   | info (fixed)    | n/a (exempt)          | info, `heuristic:false`  | -       |
| OK    | info (fixed)    | n/a (exempt)          | info, `heuristic:false`  | -       |
| ZC    | high            | yes                    | **high**, `heuristic:false` | -   |
| SW    | medium          | yes                    | **medium**, `heuristic:false` | - |
| QUEUE | medium          | yes                    | **medium**, `heuristic:false` | - |
| SYNC  | medium          | no                     | info, `heuristic:true`   | -       |
| CAPS  | info (fixed)    | n/a                    | info, `heuristic:true`   | -       |
| STALL | high            | no                     | info, `heuristic:true`   | -       |
| VIC   | medium          | no                     | info, `heuristic:true`   | tegrastats |
| ENC   | medium          | no                     | info, `heuristic:true`   | -       |
| CPU   | info (fixed)    | n/a                    | info, `heuristic:true`   | -       |
| HW    | info (fixed)    | n/a                    | info, `heuristic:true`   | tegrastats |
| QLEAK | (never emits)   | no                     | never emits              | queue_levels |
