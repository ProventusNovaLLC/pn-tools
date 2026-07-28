#!/usr/bin/env bash
#
# bringup-doctor.sh — Jetson serial boot-log triage in 30 seconds.
#
# Feed it a boot log (file or stdin), it greps for known failure signatures
# and prints the likely root-cause category + where to look next, so you
# get a hardware-vs-bootloader-vs-kernel-vs-DTS verdict BEFORE anyone RMAs
# a board.
#
# Usage:
#   bringup-doctor.sh boot.log
#   picocom -b 115200 /dev/ttyUSB0 | tee boot.log | bringup-doctor.sh -
#
#   -           read the log from stdin
#   --genio     MediaTek Genio mode (v1: prints the Genio boot-stage map;
#               Jetson signatures only for now)
#   -q          quiet — verdict lines only, no banner
#   -h          help
#
# Exit codes:  0 = no failure signatures found
#              1 = one or more failure signatures matched
#              2 = empty input (no serial output — see printed checklist)
#              3 = usage error
#
# Offline by design: pure bash + grep/awk, no network calls, no telemetry.
# The signature table below IS the documentation — read it.
#
# (c) ProventusNova — MIT license. Part of the pn-tools collection:
#   https://github.com/ProventusNovaLLC/pn-tools

set -u

VERSION="0.1.0-draft"
BLOG="https://proventusnova.com/blog"

QUIET=0
GENIO=0
INPUT=""

usage() { sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; }
say()   { printf '%s\n' "$*"; }
log()   { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }
die()   { printf 'bringup-doctor: %s\n' "$*" >&2; exit 3; }

while [ $# -gt 0 ]; do
  case "$1" in
    --genio) GENIO=1 ;;
    -q) QUIET=1 ;;
    -h|--help) usage; exit 0 ;;
    -V|--version) say "bringup-doctor.sh $VERSION"; exit 0 ;;
    -) INPUT="-" ;;
    -*) die "unknown option $1 (try -h)" ;;
    *) INPUT="$1" ;;
  esac
  shift
done

[ -n "$INPUT" ] || die "no input — pass a log file or '-' for stdin (try -h)"

LOGBUF=$(mktemp "${TMPDIR:-/tmp}/bringup-doctor.XXXXXX") || die "mktemp failed"
trap 'rm -f "$LOGBUF"' EXIT
if [ "$INPUT" = "-" ]; then
  cat > "$LOGBUF"
else
  [ -r "$INPUT" ] || die "cannot read $INPUT"
  cat "$INPUT" > "$LOGBUF"
fi

# =========================================================================
# Boot stage markers — Jetson Orin boot chain, in order.
# If the UART goes silent at a specific stage, that stage is your suspect.
# Reference: $BLOG/jetson-uefi-boot-flow-mb1-mb2-tfa-kernel
# =========================================================================
STAGE_NAMES=( "MB1" "MB2" "TF-A" "UEFI" "kernel" "userspace" )
STAGE_MARKS=(
  '\[MB1\]|MB1 \('
  '\[MB2\]|MB2 \('
  'NOTICE:( +)BL31'
  'NVIDIA UEFI|Jetson UEFI|BdsDxe|UEFI firmware'
  'Booting Linux on physical CPU'
  'systemd\[1\]|Welcome to|[a-zA-Z0-9-]+ login:'
)

# =========================================================================
# SIGNATURE TABLE — Jetson. Parallel arrays, one row per signature:
#   S_ID     short id
#   S_STAGE  boot stage the failure belongs to
#   S_RE     case-insensitive ERE matched against the log
#   S_DIAG   one-line diagnosis (root-cause class)
#   S_NEXT   the next check to run
#   S_URL    where the full fix lives
# =========================================================================
S_ID=();S_STAGE=();S_RE=();S_DIAG=();S_NEXT=();S_URL=()
sig() { S_ID+=("$1");S_STAGE+=("$2");S_RE+=("$3");S_DIAG+=("$4");S_NEXT+=("$5");S_URL+=("$6"); }

sig "eeprom" "MB1/MB2" \
  'eeprom.*(read|crc).*(error|fail)|eeprom.*(invalid|blank|not (found|programmed))|cvb eeprom.*(error|fail)' \
  "carrier-board EEPROM not programmed / unreadable — module falls back to reference-board config; rail/GPIO mismatch halts boot" \
  "read the carrier EEPROM over I2C: blank (all 0xFF) or reference-board IDs confirm it" \
  "$BLOG/jetson-carrier-board-not-booting-root-causes"

sig "bct-odmdata" "MB1/MB2" \
  '(bct|odmdata).*(error|invalid|mismatch|fail)|brbct|mb2.*(error|fail(ed)?)' \
  "BCT / ODMDATA does not match the hardware (PCIe lanes, USB mode, storage select)" \
  "extract ODMDATA with tegraflash and compare against the carrier's actual peripheral config" \
  "$BLOG/jetson-carrier-board-not-booting-root-causes"

sig "uefi-assert" "UEFI" \
  'ASSERT_EFI_ERROR|ASSERT [^ ]*\.c\([0-9]+\)' \
  "UEFI firmware assertion — QSPI bootloader corruption, missing DTB, or (worst case) partial secure-boot fuse burn" \
  "at the UEFI shell: fs0: then ls — no fs0: means boot partition/table corrupt; recover with flash.sh -r <board> internal (reflash QSPI too)" \
  "$BLOG/jetson-uefi-shell-assertion-boot-recovery"

sig "uefi-bds" "UEFI" \
  'BdsDxe: failed to load|UEFI Interactive Shell|^Shell> *$' \
  "UEFI dropped to shell — boot option failed to load; boot partition not accessible or extlinux/DTB reference broken" \
  "check extlinux.conf references a DTB that exists; try manual boot: fs0:\\EFI\\BOOT\\BOOTAA64.EFI" \
  "$BLOG/jetson-uefi-shell-assertion-boot-recovery"

sig "vfs-panic" "kernel" \
  'VFS: Unable to mount root|Kernel panic - not syncing' \
  "kernel panics before userspace — rootfs/flash class: wrong root= device, missing rootfs, or a partial/interrupted flash" \
  "compare bootloader and kernel versions (partial-flash mismatch); verify root= in extlinux.conf matches the flashed medium" \
  "$BLOG/jetson-carrier-board-not-booting-root-causes"

sig "init-missing" "kernel" \
  'No init found|attempted to kill init|run-init: .*(fail|No such)' \
  "rootfs mounts but init is missing/broken — incomplete rootfs image or interrupted flash" \
  "mount the rootfs offline and check /sbin/init; reflash rootfs if incomplete" \
  "$BLOG/jetson-carrier-board-not-booting-root-causes"

sig "dwc3-71" "kernel" \
  'dwc3 .*failed to get clk|probe of .*failed with error -71' \
  "the JetPack 6 / L4T R36 USB regression: the 'ref' clock became MANDATORY in the DT; R35-ported device trees fail dwc3 probe (USB fully dead)" \
  'add to the xhci node: clocks = <&bpmp TEGRA234_CLK_CLK_M>; clock-names = "ref"; — DT recompile only, no kernel rebuild' \
  "$BLOG/dwc3-error-71-jetson-clock-reference-fix"

sig "usb-desc" "kernel" \
  'device descriptor read.*error|device not accepting address|unable to enumerate USB device' \
  "USB device-level enumeration failure — VBUS sequencing / signal-integrity / PHY config class" \
  "check VBUS-enable GPIO timing and regulator nodes against the R36 conventions" \
  "$BLOG/jetpack-6-usb-enumeration-failure-fix"

sig "gmsl-lock" "userspace" \
  'Serial-link [0-9]+: Failed to lock|Failed to lock!' \
  "GMSL serializer link never locks — empty connector, unpowered serializer, dead coax, OR a DT overlay enabling the WRONG link@N (survives every module/cable swap)" \
  "verify each enabled link@N in the DT maps to a physically populated connector BEFORE swapping hardware; then run gmsl2-probe.sh" \
  "$BLOG/gmsl2-camera-not-working-jetson"

sig "probe-fail" "userspace" \
  'probe of .+ failed with error -[0-9]+|deferred probe timeout|probe with driver .+ failed' \
  "a device driver failed/deferred probe — driver/DTS class (missing CONFIG_, wrong compatible, missing clock/regulator, power sequencing)" \
  "dmesg | grep -iE 'probe|defer'; ls /sys/firmware/devicetree/base/<node>; for cameras: media-ctl -p and v4l2-ctl --list-devices" \
  "$BLOG/custom-carrier-board-not-booting-jetson-orin"

# =========================================================================
# Genio table — v1 stub, structure ready for BROM/BL2/LK signatures.
# Boot chain: BROM → BL2 (TF-A) → BL31 → BL32 (OP-TEE) → BL33 (U-Boot) → kernel
# BROM prints on UART0 @ 115200 8N1 regardless of boot mode.
# =========================================================================
# shellcheck disable=SC2034  # empty by design — v2 fills these in
{ G_ID=(); G_STAGE=(); G_RE=(); G_DIAG=(); G_NEXT=(); G_URL=(); }

# ------------------------------------------------------------------- run
log "bringup-doctor $VERSION"
log ""

if [ "$GENIO" -eq 1 ]; then
  say "Genio mode: v1 ships Jetson signatures only."
  say "Genio boot chain for manual staging (BROM prints on UART0 @115200 8N1):"
  say "  BROM → BL2 (TF-A: DDR/eMMC init) → BL31 (PSCI, resident) →"
  say "  BL32 (OP-TEE) → BL33 (U-Boot: loads fitImage) → Linux"
  say "  UART silent at BROM = strapping/power/boot-media; silent after BL2 ="
  say "  DDR calibration or fip.bin; U-Boot up but no kernel = fitImage/DTB."
  say ""
fi

# ---- empty input = "no serial output at all" — its own failure class
if ! grep -q '[^[:space:]]' "$LOGBUF"; then
  say "VERDICT: NO SERIAL OUTPUT AT ALL — the failure is before any code"
  say "  prints, or the console is miswired. Checklist, in order:"
  say "   1. serial console itself: 115200 8N1, right UART port, TX/RX not"
  say "      swapped (rule this out first — it mimics a dead board)"
  say "   2. power sequencing: CARRIER_POWER_ON / VDD_IN timing vs the"
  say "      design guide (logic analyzer)"
  say "   3. carrier EEPROM not programmed (blank EEPROM can kill boot"
  say "      before the first character)"
  say "   4. FORCE_RECOVERY strapping asserted → module sits in recovery:"
  say "      on the host, lsusb | grep -i 'nvidia.*apx'"
  say "  Read next: $BLOG/jetson-carrier-board-not-booting-root-causes"
  exit 2
fi

# ---- boot-stage attribution: how far did it get?
furthest="(pre-MB1 / none seen)"
progress=""
for i in "${!STAGE_NAMES[@]}"; do
  if grep -qiE "${STAGE_MARKS[$i]}" "$LOGBUF"; then
    progress+="${STAGE_NAMES[$i]} ✓  "
    furthest="${STAGE_NAMES[$i]}"
  fi
done
say "Boot progress : ${progress:-"no stage markers found"}"
say "Furthest stage: $furthest"
say ""

# ---- signature scan
matches=0
for i in "${!S_ID[@]}"; do
  line=$(grep -inE "${S_RE[$i]}" "$LOGBUF" | head -1) || true
  [ -n "$line" ] || continue
  matches=$((matches + 1))
  lineno=${line%%:*}
  text=$(printf '%s' "${line#*:}" | cut -c1-110)
  say "── MATCH [${S_ID[$i]}]  stage: ${S_STAGE[$i]}"
  say "   log:${lineno}: ${text}"
  say "   diagnosis : ${S_DIAG[$i]}"
  say "   next check: ${S_NEXT[$i]}"
  say "   read next : ${S_URL[$i]}"
  say ""
done

# ---- heuristic note: JP6 silent USB — controller up, nothing enumerates,
#      NO error printed (that silence IS the signature). Heuristic only:
#      a board with genuinely nothing plugged in looks identical, so this
#      never affects the exit code. Enumeration evidence accepts both the
#      'New USB device found' line and the per-device 'new <speed> USB
#      device number N' form (journalctl -k logs often carry only the
#      latter — verified on a live Orin NX R36.4.3 journal).
if grep -qiE 'xhci|tegra-xusb' "$LOGBUF" && \
   grep -qiE 'Booting Linux on physical CPU' "$LOGBUF" && \
   ! grep -qiE 'New USB device found|new (high|full|low|super)-speed USB device' "$LOGBUF" && \
   ! grep -qiE 'probe of .*failed with error -71' "$LOGBUF"; then
  say "── NOTE [usb-silent]  stage: kernel  (heuristic — not a verdict)"
  say "   xHCI initialized but the log shows NO device enumeration and no"
  say "   error. IF this board should have USB devices (hub, storage,"
  say "   modem), that silent pattern on JetPack 6 is the R35→R36 DT"
  say "   porting class: deprecated PHY properties (silently ignored),"
  say "   stale PINMUX, VBUS sequencing, or old controller bindings."
  say "   If nothing is plugged into USB, ignore this note."
  say "   next check: regenerate PINMUX with the R36 tool; update PHY +"
  say "   VBUS regulator nodes to R36 bindings."
  say "   read next : $BLOG/jetpack-6-usb-enumeration-failure-fix"
  say ""
fi

if [ "$matches" -gt 0 ]; then
  say "$matches known failure signature(s) matched."
  exit 1
fi

# ---- nothing matched → manual triage tree
say "No known failure signatures detected."
say ""
say "Manual triage tree (symptom → first checks):"
say "  bootloader never starts:"
say "    - bootloader actually flashed? boot media (eMMC/SD/NVMe) correct?"
say "    - serial console baud right (115200)?"
say "  kernel panics at boot:"
say "    - DTB matches the board? MACHINE/board config correct?"
say "    - initramfs expected but missing?"
say "  boots to login but a device is missing:"
say "    - module in image?  find /lib/modules -name '*.ko' | grep <drv>"
say "    - manual load:      modprobe <drv> && dmesg | tail -30"
say "    - DT node present?  ls /sys/firmware/devicetree/base/<path>"
say "    - common causes: missing CONFIG_, wrong compatible string,"
say "      missing firmware file, power sequencing"
say ""
say "Boot-flow reference: $BLOG/jetson-uefi-boot-flow-mb1-mb2-tfa-kernel"
exit 0
