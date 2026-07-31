# Jetson reference — per-node commands and interpretations

Hardware-verified entries are tagged [VERIFIED R36.4.3]. Substitute
`<bus>`, `<sensor>`, `<drv>`, `/dev/videoN`, `W/H/FMT` from the user's
setup. Never guess values not in this file.

## N1 — video device exists?

```
ls /dev/video*
v4l2-ctl --list-devices
```
- YES: a `/dev/videoN` under the platform node with the sensor's name.
  Healthy shape [VERIFIED R36.4.3]:
  `vi-output, imx462 60-001a (platform:tegra-capture-vi:0)` →
  `/dev/video0`
- NO: no nodes, or only unrelated devices (USB webcams enumerate here
  too — do not mistake them for the CSI sensor).
- Note: `v4l2-ctl` missing → `sudo apt install v4l-utils` (not
  preinstalled on JetPack).

## N2 — sensor on I2C?

```
i2cdetect -y -r <bus>        # bus: carrier schematic or DT
i2cdetect -l                 # hint: list candidate buses
```
- YES: address shown (e.g. `36`) — or `UU`, meaning a kernel driver
  owns the device (also healthy, further along).
- NO: `--` at the expected address.

## N3 — power/enable GPIO high?

```
sudo cat /sys/kernel/debug/gpio     # or: gpioinfo
```
- Find the cam pwdn/enable line by label. UP = `out hi`.
- ACTIVE LOW trap [VERIFIED R36.4.3]: debugfs shows LOGICAL state —
  `out hi ACTIVE LOW` means the physical pin is LOW. Read the logic.

## A1 — drive the GPIO high

```
gpioset --mode=wait <chip> <line>=1     # leave running; Ctrl-C releases
```
- [VERIFIED R36.4.3, libgpiod v1.6.3]: default `--mode=exit` sets and
  RELEASES the line — the level may not hold. `--mode=wait` holds it.
- Newer libgpiod v2 has a different CLI — check `gpioset --version`.
- JetPack 6 has NO `/sys/class/gpio` sysfs route [VERIFIED] — gpiod only.
- Then re-run N2.

## N4 — schematic + bench checklist

Check in order; any fix → re-run N2. All pass and still `--` → T1.
1. Wiring vs schematic: SDA/SCL on the right bus, address straps,
   I2C mux/switch in the path.
2. Power rails in spec UNDER LOAD (multimeter, not schematic faith).
3. Reset GPIO released — verify POLARITY (wrong polarity looks exactly
   like dead silicon).
4. MCLK present (some sensors won't ACK I2C without it).

## T1 — hardware dead end

Suspect dead sensor or wiring. Insist on SUBSTITUTION before concluding:
known-good module on this board, or this module on a known-good board —
never convict from one pairing. Then: camera/board manufacturer, or the
escalation link.

## N5 — driver probed?

```
dmesg | grep -iE "<drv>|<sensor>|probe"
```
- PROBED: a detection line (e.g. `detected imx477 sensor`) → N6.
- FAILED: `probe of ... failed with error -N` / chip-ID mismatch /
  NAKs → A2.
- SILENT: no line from the driver at all → N5.1. Silence means the
  kernel never matched driver to DT node — different family than FAILED.

## A2 — read the probe error

- `-EPROBE_DEFER` (-517): missing clock / regulator / supplier
  reference in the DT.
- Chip-ID mismatch: wrong driver variant — OR the sensor ACKs I2C but
  is not fully powered/reset, so registers read garbage.
- I2C NAKs mid-init: electrical margin / wrong address.
- Fix → re-run N5. Unplaceable error → escalation link.

## N5.1 — node in the live device tree?

```
find /proc/device-tree -name "*<sensor>*"
cat <node>/status        # must be "okay"
```
- NO → A3a: the DTB/overlay was never applied. Install it where the
  boot chain reads it (extlinux FDT/OVERLAYS line, jetson-io, or
  flash), reboot, re-run N5.

## N5.2 — compatible matches?

```
cat /proc/device-tree/<node>/compatible
modinfo <drv> | grep alias      # "of:...C<string>" must match EXACTLY
```
- NO → fix the DT (or use the right driver), re-run N5.

## N5.3 — driver in this kernel?

```
grep CONFIG_VIDEO_<SENSOR> /boot/config-$(uname -r)
```
- `=y` builtin → T3. `=m` module → N5.4. Not set → A3b: enable the
  config or build the OOT module, re-run N5.

## N5.4 / N5.5 — module loaded? on disk?

```
lsmod | grep <drv>
find /lib/modules -name "*<drv>*"
```
- Loaded + everything matching + still silent → T3.
- On disk but not loaded → `modprobe <drv>`, re-run N5 (a probe error
  now routes via A2).
- Not on disk → A3c: install/build it, cross-built against this EXACT
  kernel, re-run N5.

## T3 — silent despite everything matching

Unusual state. One concrete lead: is the PARENT I2C bus controller
itself up (sensor node under a dead/disabled bus produces exactly this
silence)? Then escalation link.

## N6 — platform graph wired?

```
media-ctl -p
dmesg | grep -iE "tegra-camera|vi-output|video device"
ls /sys/firmware/devicetree/base/tegra-camera-platform/modules/
```
- Check: sensor port/endpoint remote-endpoint chain reaches
  NVCSI → VI in BOTH directions; tegra-camera-platform modules entry
  (devname matches sensor, badge/position consistent, num_channels).
- Mismatch → A4: fix, then APPLY properly — recompile DTB, install
  where the boot chain reads it, reboot. Editing source alone changes
  nothing. Re-run N1.
- All right, still no node → T2: diff the DT against a known-working
  reference (devkit + reference sensor overlay); manufacturer or
  escalation link.

## N7 — THE FORK: raw capture

```
v4l2-ctl -d /dev/videoN \
  --set-fmt-video=width=W,height=H,pixelformat=FMT \
  --stream-mmap --stream-count=10 --stream-to=/tmp/frames.raw
```
- W/H/FMT verbatim from `v4l2-ctl -d /dev/videoN --list-formats-ext`.
- YES [VERIFIED R36.4.3]: one `<` tick per frame, file lands.
- NO: hangs then `select timeout` / DQBUF errors.
- YES → N8. NO → A7.

## N8 — frames content good?

- Inspect `/tmp/frames.raw`: vooya (set W/H/format), or:
  - size = W × H × bytes-per-pixel × 10. 10/12-bit bayer (RG10 etc.)
    = 2 bytes/px [VERIFIED: 1920×1080 RG10 ×10 = 41 472 000 bytes].
  - `hexdump -C /tmp/frames.raw | head` — varying values = real data;
    all zeros / constant = BAD.
- GOOD → N9. BAD → A6: DTB capture-mode config (mode@N: active_w/h,
  format, line_length) + sensor register table (mode settings); fix →
  re-run N7; dead end → escalation link.

## A7 — nothing reaches the VI

Check, fix, re-run N7; dead end → escalation link.
1. DTB: num_lanes / data-lanes vs physical lanes.
2. DTB: pix_clk_hz correct for the mode.
3. DTB: embedded_metadata_height matches the sensor.
4. DTB: nvcsi/csi port + endpoint chain.
5. Sensor register table: stream-on actually sent; lane config matches
   DTB.

Evidence:
```
dmesg | grep -iE "nvcsi|tegra-vi|vi-output|capture|uncorr"
```
- JetPack 6 / R36 [VERIFIED — extracted from tegra-camera.ko]:
  `uncorr_err: request timed out after N ms` = capture request got no
  data from CSI.
- JetPack 5 and earlier (legacy wording): `PXL_SOF syncpt timeout`.
- Also [VERIFIED]: `deskew timed out for lanes 0x…` (nvcsi) =
  high-speed lane deskew failing.

## N9 — bayer or YUV?

No command — read the pixelformat used in N7:
- `RG10/BG10/GRBG/RGGB…` = Bayer [VERIFIED: IMX462 = RG10] → N10.
- `YUYV/UYVY/YUY2` (e.g. external-ISP modules like AP1302) = YUV → N11.

## N10 — nvargus works? (bayer)

```
gst-launch-1.0 nvarguscamerasrc sensor-id=0 num-buffers=30 ! \
  'video/x-raw(memory:NVMM),format=NV12' ! fakesink -v
```
- YES [VERIFIED R36.4.3]: clean exit, `GST_ARGUS: Done Success` → T4.
- NO → A8. Raw is PROVEN (N7/N8) — do NOT re-debug the lower stack:
  1. tegra-camera-platform entry: devname / position / badge.
  2. Mode-table ISP metadata (pix_clk_hz, gain/exposure ranges).
  Evidence: `sudo systemctl restart nvargus-daemon;
  journalctl -u nvargus-daemon`. Fix → re-run N10; dead end →
  escalation link.

## N11 — v4l2src works? (YUV)

```
gst-launch-1.0 v4l2src device=/dev/videoN num-buffers=30 ! \
  video/x-raw,format=<YUY2|UYVY>,width=W,height=H ! fakesink -v
```
- [NOT yet hardware-verified — no YUV sensor on the verification rig.]
- YES → T4. NO → A9:
  1. Format name mapping (V4L2 `YUYV` = GStreamer `YUY2`; `UYVY` same).
  2. Caps must match a real mode (width/height/framerate).
  3. Pixel depth > 8-bit (10/12/16-bit mono, Y16…): stock v4l2src does
     not support it — a patch is needed; ProventusNova provides it,
     open source. This is the offer-the-patch escalation.
  Evidence: `GST_DEBUG=v4l2src:5`. Fix → re-run N11; dead end →
  escalation link.

## T4 — SUCCESS

The platform is proven end-to-end: sensor, CSI, VI, capture path all
work. Anything still failing is in the user's application (pipeline
caps, API usage, permissions). One-line offer of help, no push.
