# gst-profile — where does the time go in your GStreamer pipeline?

**Status: in development. Core rules bench-verified on NVIDIA Jetson (Orin NX / JetPack 6); the public Skill and release are still to come. Not yet released.**

`gst-profile` wraps your pipeline (or your own GStreamer app) in GStreamer's
built-in tracers, aggregates what flows, and tells you where the time and the
CPU go — per element, per link, with the memory domain of every link
(NVMM / dmabuf / sysmem) so zero-copy breaks are visible. Nothing to build,
nothing to install on the target: Python 3.8+ standard library only.

```
gst-profile check                                        # what can this machine measure?
gst-profile run "nvarguscamerasrc ! nvvidconv ! ..." --duration 30s          # verdict + live view
gst-profile wrap --duration 30s -- ./my-app --args      # your binary, your pipeline
gst-profile analyze trace.log.gz --dot pipeline.dot     # offline, from a GST_DEBUG log
```

## Analysis and Reporting

The tool produces a **ranked verdict**: a concise summary of where CPU and time go in the pipeline, with findings organized by severity and severity-matched fixes. `run` and `wrap` open a **live view** (a live panel at `http://<host>:8790`) that streams metrics as the capture runs; use `--no-ui` for headless operation or `--hold N` to keep the view running for N seconds after capture completes. For recorded sessions, `analyze --serve` opens the live view on a stored capture, and `report <session> -o out.html` renders a self-contained static report you can review offline or share. The live server binds all interfaces by default so you can view it from another machine on the LAN; pass `--host 127.0.0.1` to restrict it to localhost. (`/session.json` and the stop/mark control are exposed while serving.)

**Severity is earned by bench verification.** A diagnostic rule only reports `high`/`medium` (and trips exit code 1) once it has passed a golden bad/good pipeline pair on named hardware — the bad pipeline must produce exactly that finding and its clean twin must not (see `bench/`). As of the Orin NX / JetPack 6 (L4T R36.4.3) bench pass, **ZC** (zero-copy break), **SW** (software element where a hardware one exists) and **QUEUE** (no thread boundary before the encoder) are verified and report at full severity, tagged `verified_on: orin-nx-jp6-r36.4`. Every other diagnostic still reports `info` + *heuristic* until it earns its own bench pass.

Two honest limits worth knowing: **SYNC** (`sync=true` on a live sink) can't yet be detected from a `run`-mode capture — `sync=true` is the `GstBaseSink` default, so a dot dump never records it as a set property; that needs a rule-logic revision, so SYNC stays heuristic. And on L4T R36, `tegrastats` reports no per-engine load for NVENC/NVDEC/VIC (only GPU, CPU, thermals, power) — that utilization number isn't exposed anywhere on the platform — so the **VIC**/**HW** rules and the encoder-engine signal stay heuristic, and the System tab shows "not available on this board" for those lanes.

**Overhead:** on the Orin NX, a 1080p30 all-hardware path runs at ~96.9 fps bare vs ~92.0 fps under the profiler — about a 5% throughput cost for the full tracer set. `--lite` trims it for extreme pipelines.

### Live panel

The live view is a four-tab panel. **Pipeline** — a vendor-coloured element graph; edge color encodes memory domain, edge width encodes bytes/s, dash speed encodes fps, and a stalled link stops animating and pulses to flag it. **Timeline** — hottest-first lanes. **System** — per-core CPU plus Jetson hardware units, with an explicit "not available on this board" lane (see `gst-profile check`) wherever a metric can't be measured. **Analysis** — findings as evidence → why → fix, including a launch-string diff for the suggested fix when the session has one. A shared time scrubber runs along the bottom of every tab: drag it back to freeze the view on an earlier window, click **LIVE** to re-pin to the live edge.

**Save session** (in the panel) and `report` (on the CLI) are **redacted by default** — `location=` properties, URIs, and embedded credentials are stripped; pass `--no-redact` to `report` to keep endpoints. Review the exported file before sharing regardless — the raw on-disk session JSON written by `run`/`wrap`/`analyze` is never redacted. Each tab is a deep link — `#tab=pipeline`, `#tab=timeline`, `#tab=system`, `#tab=analysis` — for pointing someone at a specific view.

Panel source lives in `gst_profile/panel/src/`; `python3 tools/build_panel.py` inlines it into the single page the live server serves and `report` embeds (`gst_profile/panel/live.html`). A test asserts the committed page never drifts from a fresh build. Two optional test suites exercise the panel further on a dev machine — JS logic tests under node's test runner, and a headless-Chrome render smoke — both skip automatically wherever `node` or a `google-chrome`/`chromium` binary isn't installed; neither is ever required on a target board.

Later plans add bench-verified rules and the public Skill. See the design doc
in the private production hub.

`gst-profile` sets (and overrides) `GST_DEBUG`, `GST_DEBUG_FILE`, and
`GST_DEBUG_DUMP_DOT_DIR` in the profiled child's environment — anything your
own pipeline or shell already set for these is not preserved during capture.

## Layout

- `bin/gst-profile` — entry point (adds the package to `sys.path`; no install step)
- `gst_profile/` — the package: `tracerlog` (log lines → records), `capsutil`,
  `dotparse`, `graph`, `launchparse` (static graph from a launch string),
  `series` (250 ms windows), `procstat` (/proc CPU), `tegrastats`, `model`
  (session + JSON), `preflight` (`check`), `launcher` (FIFO + child), `cli`
- `tests/` — `python3 -m unittest discover -s tests`
- `fixtures/local-videotestsrc/` — a real 2 s capture (regenerate with `tools/capture-fixtures.sh`)

## Session JSON

`schema: gst-profile/1` — graph (elements, links with memory domain), series
(columnar, 250 ms windows: per-element proc p50/p95 + cpu, per-link fps/bytes/
stalled, pipeline latency, system), events, findings (the ranked verdict,
computed and written into the session at save time).

Session JSON and shareable reports may contain pipeline details from your own
pipeline — `location=` properties, URIs, credentials embedded in a pipeline
string or a launch/wrap command — verbatim. The raw on-disk session file is
never redacted; `report` and the live panel's Save session both redact by
default (see **Live panel** above) — review any file before sharing
regardless.

MIT — part of [pn-tools](https://github.com/ProventusNovaLLC/pn-tools).
