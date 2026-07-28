#!/usr/bin/env bash
#
# run-tests.sh — offline test suite for pn-tools.
#
# Covers everything testable WITHOUT hardware: shellcheck lint, CLI/arg
# behavior, bringup-doctor verdicts against the synthetic fixtures, and
# gst-audit findings on known-good / known-bad pipelines.
#
# NOT covered here (needs a bench — see each tool's brief):
#   - gmsl2-probe.sh against a real MAX9296/MAX96712 rig
#   - bringup-doctor.sh against real (sanitized) customer boot logs
#   - gst-audit.sh element checks on a real Jetson/Genio element set

set -u
cd "$(dirname "$0")/.." || exit 1

PASS=0 FAIL=0
ok()   { PASS=$((PASS+1)); printf 'ok   - %s\n' "$1"; }
fail() { FAIL=$((FAIL+1)); printf 'FAIL - %s\n' "$1"; }

# assert CMD_EXIT_CODE EXPECTED_CODE GREP_PATTERN DESCRIPTION
check() {
  local desc=$1 expect_rc=$2 pattern=$3; shift 3
  local out rc
  out=$("$@" 2>&1); rc=$?
  if [ "$rc" -ne "$expect_rc" ]; then
    fail "$desc (exit $rc, wanted $expect_rc)"
    return
  fi
  if [ -n "$pattern" ] && ! printf '%s' "$out" | grep -qE "$pattern"; then
    fail "$desc (missing pattern: $pattern)"
    return
  fi
  ok "$desc"
}

# ------------------------------------------------------------- shellcheck
if command -v shellcheck >/dev/null 2>&1; then
  for s in gmsl2/gmsl2-probe.sh boot/bringup-doctor.sh gstreamer/gst-audit.sh; do
    if shellcheck -S warning "$s" >/dev/null 2>&1; then
      ok "shellcheck $s"
    else
      fail "shellcheck $s"
      shellcheck -S warning "$s" | head -40
    fi
  done
else
  printf 'skip - shellcheck not installed\n'
fi

# --------------------------------------------------------- gmsl2-probe.sh
P=gmsl2/gmsl2-probe.sh
check "probe: -h prints usage"            0 "Usage" bash $P -h
check "probe: -V prints version"          0 "gmsl2-probe" bash $P -V
check "probe: bad chip rejected"          3 "max9296 or max96712" bash $P -c foo
check "probe: bad pipe rejected"          3 "must be 0..3" bash $P -p 9

# ------------------------------------------------------ bringup-doctor.sh
D=boot/bringup-doctor.sh
F=boot/fixtures
check "doctor: no args is usage error"    3 "no input" bash $D
check "doctor: -h prints usage"           0 "Usage" bash $D -h
check "doctor: clean boot → exit 0"       0 "No known failure signatures" bash $D "$F/clean-boot.log"
check "doctor: clean boot shows progress" 0 "userspace" bash $D "$F/clean-boot.log"
check "doctor: empty log → exit 2"        2 "NO SERIAL OUTPUT" bash $D "$F/empty.log"
check "doctor: dwc3 -71 matched"          1 "dwc3-71" bash $D "$F/dwc3-error-71.log"
check "doctor: dwc3 -71 cites fix post"   1 "dwc3-error-71-jetson-clock-reference-fix" bash $D "$F/dwc3-error-71.log"
check "doctor: UEFI assert matched"       1 "uefi-assert" bash $D "$F/uefi-assert.log"
check "doctor: UEFI shell drop matched"   1 "uefi-bds" bash $D "$F/uefi-assert.log"
check "doctor: VFS panic matched"         1 "vfs-panic" bash $D "$F/vfs-panic.log"
check "doctor: EEPROM fail matched"       1 "eeprom" bash $D "$F/eeprom-fail.log"
check "doctor: GMSL no-lock matched"      1 "gmsl-lock" bash $D "$F/gmsl-no-lock.log"
check "doctor: JP6 silent USB noted"      0 "usb-silent" bash $D "$F/jp6-usb-silent.log"
check "doctor: usb note is heuristic"     0 "not a verdict" bash $D "$F/jp6-usb-silent.log"
check "doctor: stdin works"               1 "dwc3-71" bash -c "cat $F/dwc3-error-71.log | bash $D -"
check "doctor: --genio prints stage map"  0 "BROM" bash -c "bash $D --genio $F/clean-boot.log"

# ----------------------------------------------------------- gst-audit.sh
G=gstreamer/gst-audit.sh
GOOD_NVMM="nvarguscamerasrc ! video/x-raw(memory:NVMM),width=1920,height=1080,format=NV12 ! nvvidconv ! video/x-raw(memory:NVMM),format=I420 ! queue max-size-buffers=4 ! nvv4l2h264enc bitrate=4000000 ! h264parse ! matroskamux ! filesink location=out.mkv"
BAD_SW="v4l2src ! videoconvert ! x264enc ! matroskamux ! filesink location=a.mkv"
BAD_RT="nvarguscamerasrc ! video/x-raw(memory:NVMM),format=NV12 ! nvvidconv ! video/x-raw,format=BGRx ! videoconvert ! video/x-raw,format=BGR ! nvvidconv ! video/x-raw(memory:NVMM),format=I420 ! queue ! nvv4l2h264enc ! fakesink"

check "audit: no args is usage error"     3 "no pipeline" bash $G
check "audit: -h prints usage"            0 "Usage" bash $G -h
check "audit: sw elements flagged"        1 "sw-element" bash $G "$BAD_SW"
check "audit: videoconvert→nvvidconv"     1 "nvvidconv" bash $G "$BAD_SW"
check "audit: x264enc→nvv4l2h264enc"      1 "nvv4l2h264enc" bash $G "$BAD_SW"
check "audit: missing queue flagged"      1 "no-queue-before-encoder" bash $G "$BAD_SW"
check "audit: NVMM round trip flagged"    1 "nvmm-roundtrip" bash $G "$BAD_RT"
check "audit: VIC note on nvvidconv"      1 "vic-contention" bash $G "$BAD_RT"
check "audit: findings cite blog"         1 "proventusnova.com/blog" bash $G "$BAD_SW"
check "audit: clean NVMM pipeline passes" 0 "clean" bash $G -q "$GOOD_NVMM"
check "audit: stdin works"                1 "sw-element" bash -c "echo '$BAD_SW' | bash $G -"
check "audit: genio maps nv elements"     1 "jetson-only-element" bash $G --genio "$GOOD_NVMM"
check "audit: genio suggests v4l2convert" 1 "v4l2convert" bash $G --genio "nvarguscamerasrc ! nvvidconv ! fakesink"
check "audit: live sink sync warning"     1 "sink-sync" bash $G "v4l2src ! videoconvert ! autovideosink"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
