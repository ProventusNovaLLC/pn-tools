# gst-profile

Pipeline profiling for GStreamer on NVIDIA Jetson. Gives your AI
assistant ProventusNova's bench method: drive the `gst-profile` CLI
(same repo, `gst-profile/`) against a live or recorded pipeline, then
read its ranked verdict — where the time and CPU actually go, per
element — and explain it honestly instead of guessing from the launch
string.

**For:** engineers whose Jetson/GStreamer pipeline is slow, high-CPU,
or dropping frames and want to know which element is the bottleneck.

**Install (Claude Code):**

```
/plugin marketplace add ProventusNovaLLC/pn-tools
/plugin install pn-tools@pn-tools
```

Then describe the symptom and let the skill drive:

> **You:** My Jetson H.264 encode pipeline is slow — I can't tell
> which element is eating the time.
>
> **Assistant:** Checking what this machine can measure first:
> `gst-profile check` — GStreamer 1.20.3, platform jetson, full
> tracer coverage. Capturing:
> `gst-profile run "nvarguscamerasrc ! video/x-raw(memory:NVMM),width=1920,height=1080,framerate=30/1 ! videoconvert ! video/x-raw,format=I420 ! nvv4l2h264enc ! h264parse ! mp4mux ! filesink location=/tmp/out.mp4" --duration 30s --no-ui`
>
> **Assistant:** Verdict: latency p95 34.1 ms already exceeds the
> 33.3 ms frame period, and `videoconvert0` alone is 61% of it. Two
> bench-verified findings, both pointing at the same fix: ZC
> (high) — `videoconvert0` breaks zero-copy, forcing NVMM → sysmem;
> SW (medium) — a software element where the hardware `nvvidconv`
> exists. Swap `videoconvert` → `nvvidconv` and re-run to confirm.

The CLI is stdlib Python 3.8+, nothing to build or install on the
target — the skill runs it directly from `gst-profile/bin/gst-profile`
in this repo. Its bench-verified rules are ZC (high), SW (medium), and
QUEUE (medium); every other finding is reported as `info` and flagged
heuristic — not yet bench-verified, and the skill says so every time
it surfaces one.

Bench-verified on NVIDIA Jetson Orin NX, L4T R36.4.3 / JetPack 6,
GStreamer 1.20.3 (2026-08-19).

**Scope:** GStreamer pipelines only — not FFmpeg-only pipelines or
vendor SDKs that bypass GStreamer. A source starving for frames (no
frames arriving at all) is a bring-up problem, not a pipeline-shape
one — that's the **`camera-bringup-debug`** skill's job.
