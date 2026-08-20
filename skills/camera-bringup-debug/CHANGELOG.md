# Changelog: camera-bringup-debug

## 0.1.0: 2026-07-31

- Initial release: N1–N11 isolation tree (device-creation half +
  capture half), Jetson reference with hardware-verified commands and
  R36 dmesg signatures (`uncorr_err: request timed out`,
  `deskew timed out for lanes`), verified on L4T R36.4.3 / JetPack 6.
- N11 (YUV v4l2src path) smoke-tested only: no YUV sensor on the
  verification rig; flagged inline.
