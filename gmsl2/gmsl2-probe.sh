#!/usr/bin/env bash
#
# gmsl2-probe.sh — read-only GMSL2 link diagnostic for MAX9296 / MAX96712
#                  class deserializers.
#
# Tells you WHERE your GMSL2 camera link is broken — serializer link, video
# pattern path, or live stream — by reading the deserializer's link and
# per-pipe video status registers over I2C. Companion to the ProventusNova
# 4-stage GMSL2 bisection flowchart.
#
#   Stage A  : GMSL2 link lock (coax / power / connector / wrong-link DT)
#   Stage B1 : video reaches the deserializer (serializer input / sensor init)
#   Stage B2 : video pipe routing / format (soft_dt, bpp, tunnel mode)
#   Stage B3 : camera MIPI front-end (only a suspect if A..B2 pass)
#
# Usage:
#   gmsl2-probe.sh [-b BUS] [-a ADDR] [-c CHIP] [-p PIPE] [-f] [-q]
#
#   -b BUS    I2C bus number                      (default: 2)
#   -a ADDR   deserializer 7-bit I2C address      (default: 0x48)
#   -c CHIP   max9296 | max96712                  (default: max9296)
#   -p PIPE   probe a single video pipe 0-3       (default: all)
#   -f        pass -f to i2ctransfer (force access to a kernel-owned
#             device; reads are safe but bypass the driver busy-check)
#   -q        quiet — verdict lines only
#   -h        help
#
# Exit codes:  0 = all pass    1 = link fail    2 = video fail
#              3 = usage / environment error
#
# READ-ONLY: this script never writes a register. Every I2C transaction is
# a register READ (i2ctransfer write-phase carries only the register
# address). It is safe to run against a kernel-owned deserializer.
#
# Requires: bash, i2ctransfer (package: i2c-tools). Runs on Jetson
# (JetPack 5 + 6) and any Linux with i2c-tools.
#
# ⚠ VERIFY-BEFORE-TRUST: the register map below is sourced from bench notes
#   against MAX9296A/MAX96712-class datasheets. Bit positions of the raw
#   link-lock register are silicon-rev dependent. The authoritative "link
#   is functionally up" signal is VID_LOCK + VID_PKT_DET on a pipe — video
#   packets actually flowing — not a PHY lock bit alone.
#
# ⚠ MAX96724: the 0x0108 + pipe*0x12 video-status decode does NOT apply to
#   MAX96724 (all four pipe registers read a constant 0x02 even while a
#   stream is verifiably flowing). This script detects that pattern and
#   warns rather than mis-diagnosing.
#
# More context:
#   https://proventusnova.com/blog/gmsl2-camera-not-working-jetson
#   https://proventusnova.com/blog/gmsl2-camera-bringup-jetson-orin-max9295-max9296
#
# (c) ProventusNova — MIT license. Part of the pn-tools collection:
#   https://github.com/ProventusNovaLLC/pn-tools

set -u

VERSION="0.1.0-draft"

# ---------------------------------------------------------------- defaults
BUS=2
ADDR=0x48
CHIP="max9296"
PIPE="all"
FORCE=""
QUIET=0

# ------------------------------------------------------------ register map
# Sourced from MAX9296A / MAX96712-class register maps (bench-verified on
# MAX96712; VERIFY against the datasheet for your exact part + silicon rev).
REG_DEV_ID=0x000D       # device identifier
REG_LINK_EN=0x0006      # LINK_EN_A..D (bits 0-3)
REG_LOCK=0x0013         # GMSL2 link lock, link A: bit 3 (rev-dependent!)
REG_LOCK_ALT=0x001A     # alternate CTRL/lock status (raw dump only)
VIDEO_RX8_BASE=0x0108   # per-pipe video status: 0x0108 + pipe*0x12
VIDEO_RX8_STRIDE=0x12
# VIDEO_RX8 bits:
BIT_VID_BLK_LEN_ERR=7   # line block-length mismatch (clear-on-read) want 0
BIT_VID_LOCK=6          # video pipeline locked                      want 1
BIT_VID_PKT_DET=5       # video packets detected                     want 1
BIT_VID_SEQ_ERR=4       # line/frame sequence error                  want 0
STATUS_REREADS=3        # error bits latch + clear-on-read: read 3x, OR them

usage() { sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; }

log()  { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }
say()  { printf '%s\n' "$*"; }
die()  { printf 'gmsl2-probe: %s\n' "$*" >&2; exit 3; }

# ------------------------------------------------------------ arg parsing
while getopts ":b:a:c:p:fqhV" opt; do
  case "$opt" in
    b) BUS=$OPTARG ;;
    a) ADDR=$OPTARG ;;
    c) CHIP=$OPTARG ;;
    p) PIPE=$OPTARG ;;
    f) FORCE="-f" ;;
    q) QUIET=1 ;;
    h) usage; exit 0 ;;
    V) say "gmsl2-probe.sh $VERSION"; exit 0 ;;
    \?) die "unknown option -$OPTARG (try -h)" ;;
    :)  die "option -$OPTARG needs a value" ;;
  esac
done

case "$CHIP" in
  max9296|max96712) ;;
  *) die "-c must be max9296 or max96712 (got: $CHIP)" ;;
esac
case "$PIPE" in
  all|0|1|2|3) ;;
  *) die "-p must be 0..3 or all (got: $PIPE)" ;;
esac

command -v i2ctransfer >/dev/null 2>&1 \
  || die "i2ctransfer not found — install i2c-tools"

# --------------------------------------------------------------- i2c reads
# 16-bit register addresses REQUIRE i2ctransfer (write 2 addr bytes, read 1
# data byte). Plain 8-bit i2cget reads garbage on these parts.
# stderr of the last failed transfer lands in $ERRTMP so the caller can
# tell a NAK from EACCES/EBUSY (they need different advice).
ERRTMP=$(mktemp "${TMPDIR:-/tmp}/gmsl2-probe.XXXXXX") || die "mktemp failed"
trap 'rm -f "$ERRTMP"' EXIT

reg_rd16() { # reg_rd16 REG -> echoes decimal value, rc!=0 on failure
  local reg=$1 hi lo out
  hi=$(( (reg >> 8) & 0xFF ))
  lo=$(( reg & 0xFF ))
  out=$(i2ctransfer -y $FORCE "$BUS" \
        "w2@$ADDR" "$hi" "$lo" r1 2>"$ERRTMP") || return 1
  # i2ctransfer prints like: 0x94
  printf '%d' "$out" 2>/dev/null || return 1
}

bit() { echo $(( ($1 >> $2) & 1 )); }

# ------------------------------------------------------------------ header
log "gmsl2-probe $VERSION — bus $BUS, deserializer $(printf '0x%02x' "$ADDR") ($CHIP)"
log "read-only probe; no register is ever written"
log ""
# DRAFT banner: remove only after the register map passes its datasheet
# review AND a MAX9296 bench run (tracked in the boot-triage roadmap).
log "⚠ DRAFT build: the register map has not completed datasheet review."
log "  Treat verdicts as advisory — confirm with capture-and-measure:"
log "  v4l2-ctl -d /dev/videoN --stream-mmap --stream-count=30"
log ""

# ---------------------------------------------------------------- presence
if ! devid=$(reg_rd16 "$REG_DEV_ID"); then
  err=$(cat "$ERRTMP" 2>/dev/null)
  case "$err" in
    *"Permission denied"*)
      die "cannot open /dev/i2c-$BUS: permission denied — run as root, or add your user to the 'i2c' group (this is NOT a bus/device problem)" ;;
    *[Bb]usy*)
      say "FAIL  $(printf '0x%02x' "$ADDR") on bus $BUS is kernel-owned (EBUSY)."
      say "      The kernel driver has the device open. Retry with -f —"
      say "      this probe only READS, which is safe on a live device."
      exit 3 ;;
    *"No such file"*)
      die "/dev/i2c-$BUS does not exist — check the bus number (i2cdetect -l)" ;;
  esac
  say "FAIL  no ACK from $(printf '0x%02x' "$ADDR") on bus $BUS (DEV_ID read)"
  say ""
  say "  Next checks:"
  say "   - i2cdetect -l                      # right bus number?"
  say "   - i2cdetect -y -r $BUS              # device visible at another addr?"
  say "     (vendor BSPs remap serdes I2C addresses — discover, don't assume)"
  say "   - if the deserializer is kernel-owned, retry with -f (read-only)"
  say "   - no ACK at any addr → deserializer unpowered / I2C wiring / mux"
  exit 1
fi

devid_hex=$(printf '0x%02x' "$devid")
devname="unknown"
UNSUPPORTED=0
[ "$devid" -eq $((0x94)) ] && devname="MAX9296A-class"
# 0xa2 observed on a live MAX96724 rig (bench, 2026-07-28) — decode invalid
if [ "$devid" -eq $((0xa2)) ]; then
  devname="MAX96724 (register decode NOT supported)"
  UNSUPPORTED=1
fi
log "DEV_ID       $devid_hex  ($devname)"
[ "$devname" = "unknown" ] && \
  log "             note: unrecognized DEV_ID — register decode below is" \
      "only valid for MAX9296/MAX96712-class parts"

link_en=$(reg_rd16 "$REG_LINK_EN") || link_en=-1
lock_raw=$(reg_rd16 "$REG_LOCK")   || lock_raw=-1
lock_alt=$(reg_rd16 "$REG_LOCK_ALT") || lock_alt=-1

if [ "$link_en" -ge 0 ]; then
  log "LINK_EN      $(printf '0x%02x' "$link_en")  (bit0=A bit1=B bit2=C bit3=D)"
fi
[ "$lock_alt" -ge 0 ] && log "CTRL/LOCK_A  $(printf '0x%02x' "$lock_alt")  (raw, alternate lock status)"

locked=0
if [ "$lock_raw" -ge 0 ]; then
  locked=$(bit "$lock_raw" 3)
fi

# ----------------------------------------------------------- per-pipe read
pipes="0 1 2 3"
[ "$PIPE" != "all" ] && pipes="$PIPE"

declare -A P_LOCK P_PKT P_SEQ P_BLK P_RAW
identical_all=1
first_val=""

for p in $pipes; do
  reg=$(( VIDEO_RX8_BASE + p * VIDEO_RX8_STRIDE ))
  seq_sticky=0 blk_sticky=0 val=-1
  for _ in $(seq 1 "$STATUS_REREADS"); do
    v=$(reg_rd16 "$reg") || { val=-1; break; }
    val=$v
    [ "$(bit "$v" $BIT_VID_SEQ_ERR)" -eq 1 ] && seq_sticky=1
    [ "$(bit "$v" $BIT_VID_BLK_LEN_ERR)" -eq 1 ] && blk_sticky=1
  done
  P_RAW[$p]=$val
  if [ "$val" -lt 0 ]; then
    P_LOCK[$p]=-1; P_PKT[$p]=-1; P_SEQ[$p]=-1; P_BLK[$p]=-1
    continue
  fi
  P_LOCK[$p]=$(bit "$val" $BIT_VID_LOCK)
  P_PKT[$p]=$(bit "$val" $BIT_VID_PKT_DET)
  P_SEQ[$p]=$seq_sticky
  P_BLK[$p]=$blk_sticky
  [ -z "$first_val" ] && first_val=$val
  [ "$val" -ne "$first_val" ] && identical_all=0
done

# MAX96724-style decode sanity check: all pipes reading one constant value
# (classically 0x02) is the signature of a part whose VIDEO_RX8 map does
# not match this decode.
if [ "$PIPE" = "all" ] && [ "$identical_all" -eq 1 ] && \
   [ -n "$first_val" ] && [ "$first_val" -eq $((0x02)) ]; then
  say ""
  say "WARN  all four pipe status registers read a constant 0x02."
  say "      This is the MAX96724 signature: the 0x0108+pipe*0x12 decode"
  say "      does NOT apply there (verified on live hardware: constant"
  say "      0x02 with cameras attached and the driver bound)."
  UNSUPPORTED=1
fi

# ---------------------------------------------------------------- verdicts
video_lock_any=0 pkt_any=0 blk_any=0 seq_any=0 clean_pipe=-1
for p in $pipes; do
  [ "${P_LOCK[$p]}" = "1" ] && video_lock_any=1
  [ "${P_PKT[$p]}"  = "1" ] && pkt_any=1
  [ "${P_BLK[$p]}"  = "1" ] && blk_any=1
  [ "${P_SEQ[$p]}"  = "1" ] && seq_any=1
  if [ "${P_LOCK[$p]}" = "1" ] && [ "${P_PKT[$p]}" = "1" ] && \
     [ "${P_SEQ[$p]}" = "0" ] && [ "${P_BLK[$p]}" = "0" ]; then
    clean_pipe=$p
  fi
done

# Link is functionally up if video packets flow, whatever the lock bit says.
link_up=$locked
[ "$video_lock_any" -eq 1 ] || [ "$pkt_any" -eq 1 ] && link_up=1

pf() { # pf VALUE WANT -> PASS/FAIL/----
  if [ "$1" = "-1" ]; then echo "----"
  elif [ "$1" = "$2" ]; then echo "PASS"
  else echo "FAIL"; fi
}

say ""
say "REGISTER               VALUE  WANT  RESULT"
say "-------------------------------------------"
lockstr="-"; [ "$lock_raw" -ge 0 ] && lockstr=$locked
say "$(printf '%-22s %5s  %4s  %s' "LOCKED (0x0013 b3)" "$lockstr" "1" "$(pf "$locked" 1)")"
for p in $pipes; do
  reg=$(( VIDEO_RX8_BASE + p * VIDEO_RX8_STRIDE ))
  regs=$(printf '0x%04X' "$reg")
  raws="--"
  [ "${P_RAW[$p]}" -ge 0 ] && raws=$(printf '0x%02x' "${P_RAW[$p]}")
  say "pipe$p VIDEO_RX8 $regs = $raws (last of $STATUS_REREADS reads)"
  say "$(printf '%-22s %5s  %4s  %s' "pipe$p VID_LOCK    ($regs b6)" "${P_LOCK[$p]}" "1" "$(pf "${P_LOCK[$p]}" 1)")"
  say "$(printf '%-22s %5s  %4s  %s' "pipe$p VID_PKT_DET ($regs b5)" "${P_PKT[$p]}" "1" "$(pf "${P_PKT[$p]}" 1)")"
  say "$(printf '%-22s %5s  %4s  %s' "pipe$p VID_SEQ_ERR ($regs b4)" "${P_SEQ[$p]}" "0" "$(pf "${P_SEQ[$p]}" 0)")"
  say "$(printf '%-22s %5s  %4s  %s' "pipe$p VID_BLK_LEN ($regs b7)" "${P_BLK[$p]}" "0" "$(pf "${P_BLK[$p]}" 0)")"
done
say ""

# Unsupported silicon: the raw dump above may still be useful, but a
# PASS/FAIL verdict from an invalid decode would send you down the wrong
# bisection branch — refuse to give one.
if [ "$UNSUPPORTED" -eq 1 ]; then
  say "VERDICT: NONE — this part's register map is not supported by this"
  say "  probe (values above are a raw dump, not a diagnosis). Use the"
  say "  driver's own lock reporting (dmesg) plus capture-and-measure:"
  say "  v4l2-ctl -d /dev/videoN --stream-mmap --stream-count=30"
  exit 3
fi

# One-line diagnosis, mapped to the bisection flowchart stage.
if [ "$link_up" -eq 0 ]; then
  say "VERDICT: NO LINK LOCK → GMSL2 link never trained (stage A)."
  say "  Check, in order:"
  say "   1. wrong-link DT: is the enabled link@N the connector the camera"
  say "      is physically on? (survives every module/cable swap — rule it"
  say "      out first, it costs one command)"
  say "   2. coax seated / continuity, serializer power-over-coax"
  say "   3. dmesg SILENCE for the serializer on this link means failure is"
  say "      below I2C, at link training (the ser tunnel bus only exists"
  say "      after lock) — empty connector, unpowered ser, dead PHY"
  exit 1
fi

if [ "$video_lock_any" -eq 0 ]; then
  say "VERDICT: LINK OK, NO VIDEO LOCK → problem is upstream of the"
  say "  deserializer: check serializer video input / sensor init"
  say "  (stage B1 in the flowchart). The sensor is likely not streaming,"
  say "  or the serializer video path is not enabled (VID_TX_EN)."
  exit 2
fi

if [ "$blk_any" -eq 1 ]; then
  say "VERDICT: VIDEO LOCKED but VID_BLK_LEN_ERR is latching →"
  say "  format / line-length mismatch (the RAW8-vs-RAW16 trap), NOT a"
  say "  clock problem (stage B2). Fix the deser soft_dt/soft_bpp override"
  say "  (and its override-ENABLE bit) — or enable GMSL2 tunnel mode"
  say "  end-to-end, which sidesteps block-length entirely."
  exit 2
fi

if [ "$seq_any" -eq 1 ]; then
  say "VERDICT: VIDEO LOCKED but VID_SEQ_ERR is latching → line/frame"
  say "  sequence errors: marginal link or pipe routing (stage B2)."
  say "  Check coax quality/length, ser lane count vs camera, VC routing."
  exit 2
fi

if [ "$pkt_any" -eq 0 ]; then
  say "VERDICT: VIDEO LOCK without packet detect — unusual. Re-run while"
  say "  the sensor is actually commanded to stream (stage B1/B3 boundary)."
  exit 2
fi

say "VERDICT: ALL PASS on pipe $clean_pipe — link locked, video packets"
say "  flowing, no sequence/length errors. If frames still don't reach"
say "  your app, the problem is DOWNSTREAM of the deserializer: Jetson"
say "  CSI/VI config, device tree, or capture stack (stage B3/host)."
say "  Confirm with: v4l2-ctl -d /dev/video0 --stream-mmap --stream-count=30"
exit 0
