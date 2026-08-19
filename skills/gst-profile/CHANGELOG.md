# Changelog — gst-profile

## 0.1.0 — 2026-08-19

- Initial release: drives the `gst-profile` CLI to capture a live or
  recorded GStreamer pipeline and read its ranked verdict — per-element
  time/CPU share, zero-copy breaks, software-vs-hardware element swaps,
  missing queues, sync issues. Jetson-aware, generic-GStreamer-safe.
- Bench-verified rules: ZC — zero-copy break, NVMM → sysmem (high); SW —
  software element where a hardware equivalent exists (medium); QUEUE —
  no thread boundary before the encoder/sink (medium). All three verified
  on NVIDIA Jetson Orin NX, L4T R36.4.3 / JetPack 6, GStreamer 1.20.3.
- All other rules (SYNC, CAPS, STALL, VIC, ENC, CPU, HW, QLEAK) ship as
  `info`-severity and flagged heuristic — not yet bench-verified.
