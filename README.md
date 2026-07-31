# pn-tools

Embedded camera / BSP debugging tools and methods from the
[ProventusNova](https://proventusnova.com) bench, for NVIDIA Jetson and
MediaTek Genio. MIT-licensed, offline, no telemetry.

| What | Where | Status |
|---|---|---|
| `gst-audit.sh` — static GStreamer pipeline analyzer | [`gstreamer/`](gstreamer/) | available |
| Interactive debugging skills for AI assistants | [`skills/`](skills/) | in review, landing incrementally |
| Known-good boot logs (Jetson + Genio devkits) | [`boot-logs/`](boot-logs/) | capture in progress |

## gst-audit.sh

Points at a GStreamer pipeline string and reports — without launching
anything — why it will be slow on Jetson: software elements where
hardware exists (`videoconvert`→`nvvidconv`, `x264enc`→`nvv4l2h264enc`),
broken NVMM zero-copy paths, missing queues before encoders, untuned
queues and missing `sync=false` on live paths, and the multi-process VIC
contention trap (measured 5–10× throughput collapse). Each finding
prints WHY + FIX + the reference post.

```bash
./gstreamer/gst-audit.sh "v4l2src ! videoconvert ! x264enc ! matroskamux ! filesink location=a.mkv"
./gstreamer/gst-audit.sh --genio "nvarguscamerasrc ! nvvidconv ! ..."   # Jetson→Genio element mapping
```

Read-only (`gst-inspect-1.0` is the only external tool, and it's
optional). Exit `0` clean / `1` findings — usable as a CI gate on
pipeline configs.

## Tests

```bash
tests/run-tests.sh
```

## License

MIT — see [LICENSE](LICENSE).
