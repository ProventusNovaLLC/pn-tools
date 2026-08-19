# bench — golden-pipeline verification

The honesty gate (design decision D10): a diagnostic rule may only emit
`high`/`medium` after it is **bench-verified** on named hardware. Until then its
findings ship as `info` + "heuristic". This directory holds the golden pipeline
pairs that earn that promotion.

## The method

Each rule has a **pair** in `pairs/<rule>.sh` — two `gst-launch` strings:

- `BAD` — a pipeline that *should* trigger the rule's finding.
- `GOOD` — its twin without the anti-pattern, which *should* come back clean.

A rule graduates only when, on the bench board:

1. the **BAD** capture's verdict contains the rule's finding, and
2. the **GOOD** capture's verdict does **not**.

That is the whole criterion. It is judged by the operator reading the two
verdicts — the runner script does not decide it.

Pipelines are **`videotestsrc`-based on purpose**: no camera, so they are
reproducible on any Jetson and they sidestep a rig's "Argus poisons the
raw-V4L2 path" hazard (no sensors are touched). They carry no client content, so
the sanitized captures become public demo fixtures.

## Running a pair

```sh
# deploy the tool to the board first (from repo root):
git archive --format=tar --prefix=gst-profile/ HEAD:gst-profile | gzip > /tmp/gp.tgz
scp -q /tmp/gp.tgz jetson:/tmp/ && ssh jetson 'cd /tmp && rm -rf gst-profile && tar xzf gp.tgz && rm gp.tgz'

# then run each pair (SSH_AUTH_SOCK must reach the board):
bench/run-bench.sh zc
bench/run-bench.sh sw
bench/run-bench.sh queue
bench/run-bench.sh sync
```

Each run prints the bad and good verdicts and saves the two session JSONs to
`results/` (gitignored). A capture that passes the criterion is sanitized
(reviewed for any hostname/serial/client string — `videotestsrc` carries none,
but the review is mandatory per CAUTION.md) and copied into
`../tests/fixtures/orin-nx-jp6-<rule>.json`; the shared clean twin becomes
`orin-nx-jp6-healthy.json`. The verified rule id + config then go into
`gst_profile/rules.py:VERIFIED_RULES`.

## Named config

The bench board is an **NVIDIA Jetson Orin NX, L4T R36.4.3 (JetPack 6)**,
GStreamer 1.20.3 — recorded in `verified_on` as **`orin-nx-jp6-r36.4`**.

Run with the board's other camera/encode workloads quiesced, so their CPU load
does not pollute the per-element proc-time and CPU-share measurements.

## What this board can and cannot verify

Bench-verifiable here (CPU / memory-domain / static evidence):

| Rule | Finding | Target severity |
|---|---|---|
| ZC | zero-copy break (NVMM→sysmem→NVMM) | high |
| SW | software element where a HW one exists | medium |
| QUEUE | no thread boundary before the encoder/sink | medium |
| SYNC | live sink with `sync=true` | medium |
| STALL (stretch) | a link's fps → 0 while upstream flows | high |

**Not** verifiable on this platform — stays honest heuristic:

- **VIC**, **HW**, and the encoder-engine input of **ENC** need hardware-engine
  *utilization %*. On L4T R36, tegrastats emits CPU + GR3D + thermals + power
  only; the video engines (NVENC/NVDEC/VIC) expose no `load` counter anywhere in
  sysfs — only power-domain on/off and clock rate. That utilization number is
  genuinely unavailable on this platform (confirmed by sysfs probing), so faking
  it would violate the honesty gate. The System tab shows "not available on this
  board" for those lanes. Recovering true engine load is a future improvement on
  a platform that exposes it.
