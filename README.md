# pn-tools

Field diagnostics for embedded camera / BSP bring-up, from the
[ProventusNova](https://proventusnova.com) bench. Pure bash, offline, no
telemetry, MIT-licensed. Every rule cites the blog post that explains it.

| Tool | What it answers | Needs |
|---|---|---|
| [`gmsl2/gmsl2-probe.sh`](gmsl2/gmsl2-probe.sh) | *Where* is my GMSL2 link broken? | `i2c-tools` on the target |
| [`boot/bringup-doctor.sh`](boot/bringup-doctor.sh) | Why doesn't this board boot? | a serial boot log |
| [`gstreamer/gst-audit.sh`](gstreamer/gst-audit.sh) | Why is my pipeline slow? | the pipeline string |

## gmsl2-probe.sh

Read-only GMSL2 link diagnostic for MAX9296 / MAX96712-class
deserializers. Reads the link-lock and per-pipe video status registers
(`VID_LOCK`, `VID_PKT_DET`, `VID_SEQ_ERR`, `VID_BLK_LEN_ERR`) over I2C
and prints a PASS/FAIL verdict block plus a one-line diagnosis mapped to
the 4-stage bisection flowchart — e.g. `LINK OK, NO VIDEO LOCK → problem
is upstream of the deserializer (stage B1)`.

```bash
# defaults: bus 2, deserializer 0x48
./gmsl2-probe.sh
# explicit, kernel-owned device (read-only force), MAX96712
./gmsl2-probe.sh -b 7 -a 0x29 -c max96712 -f
```

Exit codes are CI-friendly: `0` all-pass, `1` link fail, `2` video fail.
It never writes a register. Catches the `VID_BLK_LEN_ERR`-with-lock
trap (format/line-length mismatch that masquerades as a clock problem)
and the MAX96724 constant-`0x02` decode trap.

**Status: draft** — register addresses sourced from bench notes against
MAX9296A/MAX96712-class datasheets; verify on your silicon rev before
trusting a verdict (bit positions of the raw lock register are
rev-dependent; `VID_LOCK`+`VID_PKT_DET` is the authoritative signal).

## bringup-doctor.sh

Feed it a Jetson serial boot log (file or stdin) and get a
hardware-vs-bootloader-vs-kernel-vs-DTS verdict in 30 seconds, before
anyone RMAs a board. Greps for known failure signatures (EEPROM/BCT,
UEFI assertions and shell drops, VFS panics, the JetPack 6 `dwc3 -71`
USB clock regression, silent JP6 USB enumeration, GMSL link-lock
failures, probe deferrals), attributes the failure to a boot stage
(MB1 → MB2 → TF-A → UEFI → kernel → userspace), and cites the write-up
with the full fix for each match.

```bash
./bringup-doctor.sh boot.log
picocom -b 115200 /dev/ttyUSB0 | tee boot.log | ./bringup-doctor.sh -
```

No matches → prints the manual triage tree. Empty input is itself a
verdict (`NO SERIAL OUTPUT` → power/strapping/UART checklist).
`--genio` prints the MediaTek Genio boot-stage map (BROM → BL2 → BL31 →
BL32 → BL33 → kernel); Genio signatures land in v2. Synthetic test logs
live in [`boot/fixtures/`](boot/fixtures/).

## gst-audit.sh

Static analyzer for GStreamer pipeline strings on Jetson. Reports —
without launching anything — software elements where hardware exists
(`videoconvert`→`nvvidconv`, `x264enc`→`nvv4l2h264enc`, …), broken NVMM
zero-copy paths (sysmem round trips), missing queues before encoders,
untuned queues and missing `sync=false` on live paths, and the
multi-process VIC contention trap (measured 5–10× throughput collapse).
Each finding prints WHY + FIX + the reference post.

```bash
./gst-audit.sh "v4l2src ! videoconvert ! x264enc ! matroskamux ! filesink location=a.mkv"
./gst-audit.sh --genio "nvarguscamerasrc ! nvvidconv ! ..."   # Jetson→Genio element mapping
```

Exit `0` clean / `1` findings — usable as a CI gate on pipeline configs.

## Tests

```bash
tests/run-tests.sh
```

Runs shellcheck (if installed), CLI behavior tests, fixture-based
verdict tests for `bringup-doctor.sh`, and known-good/known-bad pipeline
audits for `gst-audit.sh`. Hardware-dependent verification (real GMSL2
rig, real boot logs, on-device element sets) is tracked separately and
must pass before a tool loses its `draft` marker.

## License

MIT — see [LICENSE](LICENSE).
