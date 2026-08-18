# gst-profile — where does the time go in your GStreamer pipeline?

**Status: in development (Plan 1 of 4 — headless data path). Not released.**

`gst-profile` wraps your pipeline (or your own GStreamer app) in GStreamer's
built-in tracers, aggregates what flows, and tells you where the time and the
CPU go — per element, per link, with the memory domain of every link
(NVMEM / dmabuf / sysmem) so zero-copy breaks are visible. Nothing to build,
nothing to install on the target: Python 3.8+ standard library only.

```
gst-profile check                                        # what can this machine measure?
gst-profile run "nvarguscamerasrc ! nvvidconv ! ..." --duration 30s --print
gst-profile wrap --duration 30s -- ./my-app --args      # your binary, your pipeline
gst-profile analyze trace.log.gz --dot pipeline.dot     # offline, from a GST_DEBUG log
```

Later plans add the rule engine + verdict, the live panel (SSE), the static
report, the Skill and the bench-verified rules. See the design doc in the
private production hub (`03-gstreamer-cookbook/2026-08-17-gst-profiler-design.md`).

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
stalled, pipeline latency, system), events, findings (empty until Plan 2).

MIT — part of [pn-tools](https://github.com/ProventusNovaLLC/pn-tools).
