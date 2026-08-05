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

## License

MIT — see [LICENSE](LICENSE).
