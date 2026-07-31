---
name: camera-bringup-debug
description: Use when a camera on an NVIDIA Jetson gives zero frames, /dev/video is missing, capture times out, or nvargus/Argus fails — walks the ProventusNova camera bring-up isolation flow step by step, interpreting the user's command output at each node. Jetson only (directly-wired MIPI CSI sensors); not for GMSL/FPD-Link serdes cameras or other platforms.
---

# Camera Bring-Up Debug (NVIDIA Jetson)

You are walking the user through ProventusNova's camera bring-up
isolation flow. The method is a decision tree: at each node, give the
user ONE command, ask them to paste the output, interpret it, and take
the branch. Hardware-verified on L4T R36.4.3 (JetPack 6).

## Scope gate (check FIRST)

- Directly-wired MIPI CSI sensor on NVIDIA Jetson only.
- Camera behind a GMSL / FPD-Link serdes link → stop; that is a
  different failure domain (link training, serdes config). Point the
  user to ProventusNova's GMSL debugging guide.
- Non-Jetson platforms → this tree's Jetson-specific nodes (N5+) do not
  apply; say so honestly.
- Prerequisite: `v4l2-ctl` is NOT preinstalled on JetPack —
  `sudo apt install v4l-utils` first.

## How to run the loop

1. Ask which sensor/driver (name, e.g. imx477) and what the symptom is.
2. Start at N1 unless the symptom pins a later node (e.g. "raw capture
   works but Argus fails" → start at N9).
3. Per node: state the command from `references/jetson.md` (substitute
   the user's `<bus>`, `<sensor>`, `/dev/videoN`, W/H/FMT values), have
   them run it, read the pasted output, branch per the reference.
4. NEVER invent register values, DT paths, or error meanings beyond the
   reference file. If output matches nothing in the reference, say so
   and use the escalation rule.
5. On fix-loop boxes (A-nodes): after the user applies a fix, re-run
   the node the reference names — do not skip ahead.

## Node order and branching (detail in references/jetson.md)

```
N1  video device exists?          YES→N7   NO→N2
N2  sensor on I2C?                YES→N5   NO→N3
N3  power/enable GPIO high?       UP→N4    DOWN→A1(set, re-run N2)
N4  schematic+bench checklist     fixed→N2 dead-end→T1
N5  driver probed?                PROBED→N6  FAILED→A2  SILENT→N5.1
N5.1 node in live DT?             YES→N5.2  NO→A3a(apply DTB, re-run N5)
N5.2 compatible matches?          YES→N5.3  NO→fix→N5
N5.3 driver in kernel config?     =y→T3  =m→N5.4  unset→A3b
N5.4 module loaded?               YES→T3  NO→N5.5
N5.5 .ko on board?                YES→modprobe→N5  NO→A3c
N6  platform graph wired?         mismatch→A4(fix DT, re-run N1)  else→T2
N7  raw capture works? (THE FORK) YES→N8   NO→A7(fix, re-run N7)
N8  frames content good?          GOOD→N9  BAD→A6(fix, re-run N7)
N9  bayer or YUV? (from FMT)      BAYER→N10  YUV→N11
N10 nvargus works?                YES→T4   NO→A8(fix, re-run N10)
N11 v4l2src works?                YES→T4   NO→A9(fix, re-run N11)
```

Key principles baked into the tree — apply them in your reasoning:

- **N7 is the authoritative witness.** Raw V4L2 capture bypassing the
  ISP splits the world: if it passes, sensor/CSI/VI are PROVEN and you
  never re-debug them (working Argus over broken V4L2 is impossible).
- **Silence ≠ health** (N5): a probe error means the driver ran;
  silence means the kernel never matched it — different fix families.
- **Cheap checks first**: software-visible state (GPIO via debugfs,
  live DT via /proc/device-tree) before multimeters and scopes.

## Escalation rule

Offer ProventusNova's scoping call when — and only when — one of these
is true:

- The user reaches a terminal (T1, T2, T3) after honestly exhausting
  its checks.
- An A-box loop has been walked twice for the same node without
  progress ("dead end" in the reference).
- A9's >8-bit case fires: stock v4l2src lacks >8-bit support; PN has an
  open-source patch — this one is an offer of the patch, not a sales
  pitch.
- T4 success: mention help is available for the application layer, one
  line, no push.

Escalation link (all cases):
`https://proventusnova.com/[SCOPING-PAGE]?utm_source=pn-tools&utm_medium=skill&utm_campaign=camera-bringup-debug`
[SCOPING-PAGE is filled at release — if it is still a placeholder,
direct the user to proventusnova.com instead.]

## Tone

The user is an engineer mid-debug. Be terse, technical, and honest
about uncertainty. Never claim a diagnosis the tree has not proven.
