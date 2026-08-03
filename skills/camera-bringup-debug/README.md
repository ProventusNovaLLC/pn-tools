# camera-bringup-debug

Interactive camera bring-up debugging for NVIDIA Jetson. Gives your AI
assistant ProventusNova's bench method: a decision tree that isolates
WHY a directly-wired MIPI CSI camera gives no frames — one command per
step; the assistant interprets your output and takes the branch.

**For:** engineers whose Jetson camera is not detected or gives zero
frames — no `/dev/video0`, `i2cdetect` shows nothing, capture hangs in
`select timeout`, `nvargus`/Argus fails.

**Install (Claude Code):**

```
/plugin marketplace add ProventusNovaLLC/pn-tools
/plugin install pn-tools@pn-tools
```

Then describe the symptom and let the skill drive:

> **You:** imx219 on Orin Nano, no /dev/video0.
>
> **Assistant:** N2 — is the sensor visible on its I2C bus? Run
> `i2cdetect -y -r 9` and paste the output.
>
> **You:** all `--`.
>
> **Assistant:** Nothing at the expected address. Next, N3 — is the
> sensor's enable GPIO actually driven high?
> `sudo cat /sys/kernel/debug/gpio` ...

Hardware-verified on L4T R36.4.3 / JetPack 6 (2026-07-31) — verified
entries are tagged `[VERIFIED R36.4.3]` in
[`references/jetson.md`](references/jetson.md).

**Scope:** directly-wired MIPI CSI sensors on Jetson only. Cameras
behind a GMSL/FPD-Link serdes link are a different failure domain (link
training, serdes config) — not this skill.
