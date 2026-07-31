#!/usr/bin/env bash
#
# run-tests.sh — offline test suite for pn-tools.
#
# Covers everything testable WITHOUT hardware. Not covered here:
# gst-audit.sh element checks against a real Jetson/Genio element set.

set -u
cd "$(dirname "$0")/.." || exit 1

PASS=0 FAIL=0
ok()   { PASS=$((PASS+1)); printf 'ok   - %s\n' "$1"; }
fail() { FAIL=$((FAIL+1)); printf 'FAIL - %s\n' "$1"; }

# check DESCRIPTION EXPECTED_EXIT GREP_PATTERN CMD...
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
  for s in gstreamer/gst-audit.sh tests/run-tests.sh; do
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

# ------------------------------------------------------ scaffold sanity
check "marketplace.json is valid JSON"    0 "" \
  python3 -c "import json;json.load(open('.claude-plugin/marketplace.json'))"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
