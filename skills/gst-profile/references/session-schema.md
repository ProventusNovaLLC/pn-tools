# gst-profile session JSON — `schema: gst-profile/1`

This is the file `gst-profile run|wrap|analyze` writes to disk (and what
`analyze --serve`/the live panel/`report` all read). Field names below are
copied from a real capture —
`gst-profile/tests/fixtures/orin-nx-jp6-zc-break.json` (a zero-copy-break
session) and `gst-profile/tests/fixtures/orin-nx-jp6-healthy.json` (the
clean twin, no diagnostic findings) — not written from memory. Both are
generic `videotestsrc`/hardware-element pipelines; neither contains a
client name.

Top level:

```
{
  "schema": "gst-profile/1",
  "session": { ... },
  "target": { ... },
  "graph": { ... },
  "series": { ... },
  "findings": [ ... ],
  "events": [ ... ],
  "threads": { ... }
}
```

`threads` (a bonus not called out in the brief but present in every
fixture) is `{"<tid>:<comm>": <cpu_pct>, ...}` — the latest per-OS-thread
CPU snapshot from `/proc`, keyed by `"pid:comm"` (comm truncated to 15
chars, the kernel limit), e.g. `"98356:V4L2_EncThread": 0.0`. Rules do not
read it; it's informational/panel-only.

## `session`

Run metadata:

```
"session": {
  "id": "20260819T165720",
  "started": "2026-08-19T16:57:20Z",
  "duration_s": 12.318,
  "mode": "run",
  "launch": "videotestsrc is-live=true ! ... ! fakesink sync=false",
  "command": null,
  "label": "",
  "parent_session": null,
  "parse": {"lines": 22305, "records": 22279, "caps_events": 0,
            "format_decls": 20, "unparsed": 0, "errors": 0},
  "notes": ["lines read 22305, dropped 0, dot files dropped 0"]
}
```

- `id` — session identifier, also the default filename stem.
- `mode` — `"run"` (gst-launch string), `"wrap"` (the user's own binary),
  or `"analyze"` (offline, from a pre-existing log/dot).
- `duration_s` — wall-clock capture length.
- `launch` — the gst-launch pipeline string, when `mode == "run"`; `null`
  otherwise.
- `command` — the wrapped argv, when `mode == "wrap"`; `null` for `run`.
- `parse` — tracer-log ingestion stats (lines/records seen, errors) —
  useful for "did this capture actually work" sanity checks.

## `target`

What the tool could measure on this machine — read this before trusting
any finding that depends on a specific source:

```
"target": {
  "gstreamer": "1.20.3",
  "platform": "jetson",
  "board": "NVIDIA Jetson Orin NX Engineering Reference Developer Kit",
  "l4t": "36.4.3",
  "python": "3.10.12",
  "sources_present": ["tracer-log", "dot", "procstat", "tegrastats"],
  "sources_missing": [],
  "capabilities": {
    "element_latency": true,
    "stats": true,
    "queue_levels": false,
    "tegrastats": true
  }
}
```

- `platform` — `"jetson"`, `"mediatek"`, or `"generic"`. Drives which rows
  of `HW_SWAP` the SW rule uses (see `references/rules.md`), and gates
  vendor coloring in the panel.
- `capabilities` — booleans keyed by capability name; a rule with a
  `needs` list (VIC, HW: `tegrastats`; QLEAK: `queue_levels`) only runs
  when every needed key here is truthy. `queue_levels` is `false` in every
  fixture shipped today — QLEAK is effectively always inapplicable (see
  `references/rules.md`).
- **"Not available on this board" reads as a missing signal inside a
  present capability, not a missing capability.** `tegrastats: true` here
  means the `tegrastats` *source* was captured — it does **not** mean
  every per-engine metric inside it has data. On this L4T R36.4.3 board,
  `series.system.vic_pct`, `nvenc_pct`, `nvdec_pct`, and `emc_pct` are
  `null` across every window of the run (see the `series.system` section
  below) even though `tegrastats` capability is `true` — that's the
  literal shape of "not available on this board." Check the actual
  `series.system.*` arrays, not just `capabilities.tegrastats`, before
  claiming a hardware-engine number is measured.
- `sources_missing` lists any source `check`/the capture couldn't get
  (empty here — a full capture).

## `graph`

Static pipeline topology — elements and the links between them.

### `graph.elements[]`

```
{
  "id": "videoconvert0",
  "factory": "videoconvert",
  "gtype": "GstVideoConvert",
  "vendor": "generic",
  "klass": "",
  "props": {"qos": "TRUE"},
  "bin": null,
  "is_bin": false,
  "pads": {"sink": "sink", "src": "src"}
}
```

- `id` — the gst-launch element name (`videoconvert0`, `nvvconv1`, ...);
  this is what `findings[].targets.elements` and `.evidence` reference.
- `factory` — the GStreamer factory name (`videoconvert`, `nvvidconv`,
  `nvv4l2h264enc`, `fakesink`, ...). SW/CAPS/QUEUE/ENC/HW all match rules
  against this field.
- `vendor` — `"generic"` or `"nvidia"` (or other platform vendor tag) —
  drives element coloring in the panel; not read by any rule directly.
- `klass` — GStreamer element klass string; empty in every fixture
  observed (`""`) — don't rely on it being populated.
- `props` — a dict of the element's **non-default** properties as
  serialized in the dot dump, string-valued (`"TRUE"`/`"FALSE"`, quoted
  strings kept as-is, e.g. `"device": "\"/dev/v4l2-nvenc\""`). This is the
  root of the SYNC blind spot: a dot dump only records a property when it
  differs from its GObject default, so a property left at its default
  value is simply **absent** from `props`, not present-with-default-value.
  SYNC and ENC both read `props`.
- `is_bin` — `true` for the pipeline element itself; rules iterate
  `real_elements()`, which is every element with `is_bin == false`.

### `graph.links[]`

```
{
  "id": "capsfilter3:src->nvvconv2:sink",
  "src": "capsfilter3:src",
  "sink": "nvvconv2:sink",
  "caps": "video/x-raw ... format: NV12 ...",
  "memory": "sysmem",
  "format": "NV12",
  "media": "video/x-raw"
}
```

- `id` — `"<src elem>:<src pad>-><sink elem>:<sink pad>"`; also the key
  used in `series.links` and in `findings[].targets.links` /
  `.evidence.sysmem_link`/`.link`.
- `src` / `sink` — `"element:pad"`; the element id is the part before the
  colon (rules take `l["src"].split(":")[0]` for `src_el`, same for
  `sink_el` — the parsed `Analysis.LinkStat` exposes these directly as
  `src_el`/`sink_el`).
- `memory` — **`"nvmm" | "dmabuf" | "sysmem" | "unknown"`** — the memory
  domain of the buffers crossing this link, parsed from the caps' GStreamer
  memory feature (`capsutil.py::memory_domain`): `memory:NVMM` → `"nvmm"`,
  `memory:dmabuf` → `"dmabuf"`, any other non-system memory feature (e.g.
  `memory:CUDAMemory`) → `"unknown"` (not classified in this version), no
  memory feature → `"sysmem"`. **This is the field the ZC rule keys off,
  and the field the panel's edge color encodes.**
- `format` — the negotiated pixel format (`"NV12"`, `"I420"`, ...) or
  `null` for a non-raw link (e.g. the h264 links in the fixture carry
  `"format": null`).
- `media` — the caps media type (`"video/x-raw"`, `"video/x-h264"`, ...).
  ZC only considers links where `media` is `""` or `"video/x-raw"` — an
  encoded-stream sysmem link between hardware codecs is normal and must
  not be flagged.

### The zero-copy signal, concretely

**A gray (`sysmem`) segment sitting inside an otherwise NVMM/dmabuf-colored
raw-frame path is the ZC signal** — buffers left device memory and came
back, a CPU↔GPU copy every frame. In the zc-break fixture this is visible
directly in `graph.links`: `capsfilter1:src->nvvconv1:sink` is `"memory":
"nvmm"`, immediately followed downstream by
`nvvconv1:src->capsfilter2:sink` at `"memory": "sysmem"` — the pipeline
dropped out of NVMM into system memory for the resize/convert step
(`nvvconv1 → capsfilter2 → videoconvert0 → capsfilter3 → nvvconv2`, all
`sysmem`) before returning to `"memory": "nvmm"` at
`nvvconv2:src->capsfilter4:sink`. The ZC rule reports this island bounded
by `capsfilter1` (upstream NVMM) and `capsfilter4` (downstream NVMM); see
`references/rules.md` for the exact evidence shape. An all-encoded-stream
sysmem run (`nvv4l2h264enc0 → h264parse0 → fakesink0`, `media:
"video/x-h264"`) is present in the same fixture and is correctly *not*
flagged — encoded bytes have no zero-copy expectation.

## `series` — windowed metrics

250 ms windows (`window_ms: 250`) aligned to `series.t` (an array of window
start times in seconds, `[0.0, 0.25, 0.5, ...]`). Every array under
`series.elements.*`, `series.links.*`, `series.pipeline.*`, and
`series.system.*` is the same length as `t` and index-aligned to it —
`series.elements.videoconvert0.cpu_pct[5]` is that element's CPU percent in
the window starting at `series.t[5]`.

### `series.elements.<element id>`

```
"videoconvert0": {
  "proc_ms_p50": [null, 2.826052, 2.924807, ...],
  "proc_ms_p95": [null, 3.952032, 3.787612, ...],
  "cpu_pct": [null, 79.6, 63.5, ...],
  "queue_level": [null, null, null, ...],
  "buffers": [0, 9, 9, 7, 8, ...]
}
```

- `proc_ms_p50` / `proc_ms_p95` — per-window p50/p95 buffer processing
  time in ms for that element (from the `latency` tracer). `Analysis`
  takes the **p95 of the p95 series** (`_p95()` over the whole run) as
  each element's `proc_ms_p95`, and the **mean of the p50 series** as
  `proc_ms_typ`. HOT ranks elements by this; SW carries it as context.
- `cpu_pct` — per-window CPU percent for that element's thread(s), from
  `/proc` sampling (`procstat`). `Analysis` takes the **max** across the
  run as each element's `cpu_pct`. SW, CPU, and ZC's `offender_cpu_pct`
  all read this (maxed).
- `queue_level` — reserved for a future capability; `null` throughout in
  every fixture today (see QLEAK in `references/rules.md` — the rule this
  field would feed is currently a no-op stub).
- `buffers` — buffer count seen in that window (not percent/ms) — a raw
  activity counter, mostly informational.

### `series.links.<link id>`

```
"capsfilter3:src->nvvconv2:sink": {
  "fps": [0.0, 36.0, 36.0, 28.0, 32.0, ...],
  "bytes_s": [0.0, 49766400.0, 49766400.0, ...],
  "stalled": [false, false, false, ...]
}
```

- `fps` — buffers/sec crossing this link in the window. `Analysis` takes
  the **max** across the run per link; the **fastest source link's** max
  fps derives `frame_period_ms` (`1000 / fps`) for the OK rule.
- `bytes_s` — bytes/sec crossing this link in the window; drives the
  panel's edge-width encoding. Not read by any rule directly.
- `stalled` — per-window boolean: this link carried zero buffers in that
  window while the pipeline was running. `Analysis.LinkStat` derives two
  things from this array: `ever_stalled` (any `true` at all) and
  `stall_interior` (**≥2 consecutive** `true` windows *before* the final 2
  windows of the run — i.e. excludes ordinary teardown). **STALL reads
  `stall_interior`, not `ever_stalled`** — a link that only goes quiet
  during shutdown is not a STALL finding.

### `series.pipeline`

```
"pipeline": {
  "latency_ms_p50": [...],
  "latency_ms_p95": [...],
  "reported_latency_ms": [...]
}
```

- `latency_ms_p95` — per-window pipeline-wide latency p95 (source-to-sink,
  from the `latency` tracer). `Analysis.latency_ms_p95` is the **p95 of
  this series across the whole run** — the number the verdict header
  quotes against `frame_period_ms`, and what OK's threshold check reads.
- `reported_latency_ms` — the pipeline's own self-reported latency (a
  GStreamer query), when available; `Analysis.reported_latency_ms` takes
  the **last** value. Contextual; not read by any rule's `evaluate()`.

### `series.system`

Jetson-only (`tegrastats`-sourced); populated only when
`target.capabilities.tegrastats` is true. Note that a truthy capability
does not mean every key below has real data — see the "not available on
this board" note under `target` above.

```
"system": {
  "cpu_pct": [0.0, 21.1, 9.3, ...],
  "cpu_pct_per_core": [[], [...], ...],
  "gr3d_pct": [null, 0.0, 0.0, ...],
  "vic_pct": [null, null, null, ...],
  "nvenc_pct": [null, null, null, ...],
  "nvdec_pct": [null, null, null, ...],
  "emc_pct": [null, null, null, ...]
}
```

- `cpu_pct` / `cpu_pct_per_core` — system-wide and per-core CPU load.
- `gr3d_pct` — GPU load. **Has real data on R36** (confirmed in the
  zc-break fixture: real floats, not null).
- `vic_pct`, `nvenc_pct`, `nvdec_pct`, `emc_pct` — per-engine hardware
  block load. **`null` across every window in the R36 fixture** —
  `tegrastats` on L4T R36 does not print these tokens at all (see the
  README quote in `references/rules.md`). `Analysis.system_peak` (the
  per-key max, what VIC and HW read) is `None` for all four on this
  platform, which is why VIC can never fire and HW can only ever report
  on `gr3d_pct` there.

## `findings[]`

The full shape of one finding, copied from the fixture (`F-HOT`, always
present when there's per-element data):

```
{
  "id": "F-HOT",
  "rule": "HOT",
  "severity": "info",
  "title": "nvv4l2h264enc0 takes 33% of per-element processing time",
  "rank": 1,
  "targets": {"elements": ["nvv4l2h264enc0"], "links": []},
  "evidence": {"ranking": [["nvv4l2h264enc0", 9.427, 33.3], ...]},
  "why": "This element spends the most time producing each buffer.",
  "fix_text": "Start optimisation here; the rows below rank the rest.",
  "fix_patch": null,
  "ref": "https://proventusnova.com/blog/... (or the default lead-magnet scope link)",
  "heuristic": false,
  "verified_on": [],
  "share_of_latency_pct": 33.3
}
```

And a diagnostic one (`F-ZC-capsfilter3` — stored in this fixture at
`"severity": "info", "heuristic": true`; see the staleness note after this
example for why that doesn't match what the current `rules.py` would
compute for the same evidence):

```
{
  "id": "F-ZC-capsfilter3",
  "rule": "ZC",
  "severity": "info",
  "heuristic": true,
  "verified_on": [],
  "title": "Zero-copy broken between capsfilter1 and capsfilter4: buffers leave GPU memory and return",
  "targets": {"elements": ["capsfilter3", "nvvconv2"],
              "links": ["capsfilter3:src->nvvconv2:sink"]},
  "evidence": {"sysmem_link": "capsfilter3:src->nvvconv2:sink",
               "hw_upstream": "capsfilter1", "hw_downstream": "capsfilter4",
               "offender_cpu_pct": 79.6},
  "why": "A CPU<->GPU copy on every frame costs bandwidth and latency; NVMM/dmabuf should stay on the GPU end to end.",
  "fix_text": "Keep the path in device memory across capsfilter3->nvvconv2 (use nvvidconv, or negotiate NVMM caps so no element copies to system memory).",
  "fix_patch": {"kind": "set-caps", "link": "capsfilter3:src->nvvconv2:sink", "to": "video/x-raw(memory:NVMM)"}
}
```

Field-by-field:

- `id` — `"F-<RULE>"` or `"F-<RULE>-<element/link id>"` for rules that can
  fire more than once per session.
- `rule` — the rule id (`HOT`, `OK`, `ZC`, `SW`, `QUEUE`, `SYNC`, `CAPS`,
  `STALL`, `VIC`, `ENC`, `CPU`, `HW`, `QLEAK`) — see
  `references/rules.md` for what each one checks.
- `severity` — `"high"` | `"medium"` | `"info"`. **This is the post-gate,
  already-final value** — trust it as-is; do not re-derive a "real"
  severity from the rule id.
- `rank` — 1-based position in the sorted findings list (severity desc,
  then `share_of_latency_pct` desc); `OK` is removed from the list first
  if any other diagnostic rule fired.
- `targets` — `{"elements": [...], "links": [...]}`, the element/link ids
  this finding is about; the panel highlights these.
- `evidence` — rule-specific dict; shape documented per-rule in
  `references/rules.md`.
- `why` / `fix_text` — the human-facing explanation and suggested fix,
  verbatim strings from the rule.
- `fix_patch` — `null`, or `{"kind": ..., ...}` describing a mechanical
  launch-string edit (`set-caps`, `replace-element`, `insert-element`,
  `set-property` are the kinds seen in the shipped rules) — this is what
  the panel's Analysis tab renders as a launch-string diff.
- `ref` — a URL; defaults to the tool's own scope/contact link
  (`SCOPE` in `rules.py`) unless the rule overrides it with a specific
  blog post (VIC, ENC).
- `heuristic` — `true` unless the finding is HOT/OK (always `false`) or a
  bench-verified high/medium finding (ZC/SW/QUEUE when gated to their real
  severity). **State this plainly whenever you surface a finding** — see
  `references/rules.md`'s gating section and the SKILL's honesty rules.
- `verified_on` — `[]`, or a list of hardware tags (currently only ever
  `["orin-nx-jp6-r36.4"]`) naming the bench pass that earned this
  finding's severity.
- `share_of_latency_pct` — `float|null`; only HOT sets this (its ranking
  share); used as the tiebreaker in finding sort order.

**A saved session file's `findings` array can be stale relative to the
rules currently shipping — verify before trusting an old file's
severities.** `cli.py` computes `findings` fresh (`rules.run_rules()` over
the freshly-built `Analysis`) and writes it into the JSON right before
saving (`d["findings"] = verdict.to_dict(a, fs)["findings"]`), so a file
captured *by the current build* of the tool carries correctly gated
severities. But an older saved file predates whatever gate changes shipped
after it was captured — and that is demonstrably true of these very
fixtures: `orin-nx-jp6-zc-break.json`'s stored `F-ZC-capsfilter3` finding
shows `"severity": "info", "heuristic": true` even though the *current*
`rules.py` has `ZC` in `VERIFIED_RULES` and would compute
`"severity": "high", "heuristic": false` if re-run against this same
file's `graph`/`series` today. (This is exactly what
`tests/test_verified_rules.py` does — it deliberately ignores the fixture's
stored `findings` array and recomputes via
`rules.run_rules(analysis.build(d))` against the archived measurement data,
which is the only way to test a severity-gate change against hardware
evidence you can't always re-capture.) Practical rule: to state a
finding's *current, authoritative* severity, prefer the live CLI/panel
verdict from the currently installed tool, or cross-check the rule id
against `references/rules.md`'s gating table — don't assume an old JSON
file's stored `severity`/`heuristic` reflects what today's rules.py would
say.

## `events[]`

A flat list of pipeline lifecycle events in time order:

```
{"t": 0.106, "kind": "state-changed", "text": "GstMessageStateChanged, old-state=(GstState)paused, new-state=(GstState)playing, pending-state=(GstState)void-pending;"}
...
{"t": 12.0, "kind": "child-exit", "text": "exit code 0"}
```

- `t` — seconds since capture start.
- `kind` — `"state-changed"` (bus state-change messages), `"error"`,
  `"eos"` (from `model.py::_ingest_record`, which only records
  `error`/`eos`/`state-changed` bus messages as events), or
  `"child-exit"` (the wrapped/launched process exiting, with its exit
  code in `text`).
- `text` — the raw message text (state-changed events carry the full
  `GstMessageStateChanged` structure string; truncated to 200 chars for
  non-child-exit kinds).

No rule reads `events` — it's for the panel timeline and manual
inspection (e.g. confirming a clean `exit code 0` vs. a crash).
