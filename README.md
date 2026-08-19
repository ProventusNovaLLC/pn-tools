# pn-tools

Embedded camera / BSP debugging tools and methods from the
[ProventusNova](https://proventusnova.com) bench, for NVIDIA Jetson and
MediaTek Genio. MIT-licensed, offline, no telemetry.

## Skills

Bench debugging methods as [Agent Skills](skills/) — your AI assistant
runs the decision tree, you paste command output. Install as a Claude
Code plugin:

```
/plugin marketplace add ProventusNovaLLC/pn-tools
/plugin install pn-tools@pn-tools
```

| Skill | Debugs | Verified on |
|---|---|---|
| [`camera-bringup-debug`](skills/camera-bringup-debug/) | Jetson MIPI CSI camera: no `/dev/video0`, zero frames, Argus failures | L4T R36.4.3, 2026-07-31 |
| [`gst-profile`](skills/gst-profile/) | GStreamer pipeline on Jetson: slow, high-CPU, dropped frames, zero-copy breaks | Orin NX / L4T R36.4.3, 2026-08-19 |

## Tools

Standalone CLIs the skills above drive, usable on their own too.

**[`gst-profile`](gst-profile/)** profiles a GStreamer pipeline (live or
recorded) and shows where the time and CPU actually go, per element —
flagging zero-copy breaks (NVMM → sysmem), software elements where a
hardware one exists, and missing queues. Python 3.8+ standard library
only: nothing to build, nothing to install on the target. See its
[README](gst-profile/README.md) for the full reference.

```
gst-profile check                                     # what can this machine measure?
gst-profile run "<launch string>" --duration 30s      # profile a live pipeline
gst-profile wrap --duration 30s -- ./my-app --args    # profile your own binary
```

## License

MIT — see [LICENSE](LICENSE).
