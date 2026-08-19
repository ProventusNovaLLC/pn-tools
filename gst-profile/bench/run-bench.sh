#!/bin/sh
# Run one golden bad/good pair on the bench board and pull the session JSON back.
#
# Usage: bench/run-bench.sh <rule>          rule = zc | sw | queue | sync | stall
# Env:   SSH_AUTH_SOCK must reach the board (see the repo's board notes);
#        DUR overrides the capture duration (default 12s);
#        HOST overrides the ssh target (default: jetson).
#
# Prereq: the tool is deployed to /tmp/gst-profile on the board, e.g.
#   git archive --format=tar --prefix=gst-profile/ HEAD:gst-profile | gzip > /tmp/gp.tgz
#   scp -q /tmp/gp.tgz "$HOST":/tmp/ && ssh "$HOST" 'cd /tmp && rm -rf gst-profile && tar xzf gp.tgz && rm gp.tgz'
#
# The honesty criterion (judged by the operator, not this script): the BAD verdict
# must contain the rule's finding; the GOOD verdict must not.
set -eu

RULE="${1:?usage: run-bench.sh <zc|sw|queue|sync|stall>}"
HERE="$(dirname "$0")"
HOST="${HOST:-jetson}"
DUR="${DUR:-12s}"

if [ ! -f "$HERE/pairs/$RULE.sh" ]; then
  echo "no such pair: $RULE (expected $HERE/pairs/$RULE.sh)" >&2
  exit 2
fi
. "$HERE/pairs/$RULE.sh"
mkdir -p "$HERE/results"

for kind in bad good; do
  case "$kind" in bad) PIPE="$BAD" ;; good) PIPE="$GOOD" ;; esac
  out="/tmp/gp-bench-$RULE-$kind.json"
  echo "======== $RULE / $kind ========"
  # -q keeps gst-launch quiet; the sed/grep trims NVENC banner noise so the verdict reads clean.
  ssh "$HOST" "cd /tmp/gst-profile && ./bin/gst-profile run \"$PIPE\" --duration $DUR --no-ui --out $out 2>&1 | sed -n '/gst-profile verdict/,\$p' | grep -viE 'NvMM|NvVideo|BlockCreate|Profile =|NVMEDIA|BLOCKING'"
  scp -q "$HOST:$out" "$HERE/results/$RULE-$kind.json"
  echo "  -> saved $HERE/results/$RULE-$kind.json"
done
