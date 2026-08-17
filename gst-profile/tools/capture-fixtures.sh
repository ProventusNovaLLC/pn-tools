#!/usr/bin/env bash
# Regenerate fixtures/local-videotestsrc/ from a local GStreamer (any 1.18+; software elements only).
# Produces: trace-run.log.gz (GST_TRACER + GST_EVENT lines, 2 s of a 30 fps videotestsrc pipeline)
#           pipeline.PAUSED_PLAYING.dot (gst-launch dot dump with negotiated caps)
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
out="$here/fixtures/local-videotestsrc"
tmp="$(mktemp -d)"
mkdir -p "$out" "$tmp/dot"
GST_DEBUG_NO_COLOR=1 \
GST_TRACERS="latency(flags=pipeline+element+reported);stats" \
GST_DEBUG=GST_TRACER:7,GST_EVENT:5 \
GST_DEBUG_FILE="$tmp/trace.log" \
GST_DEBUG_DUMP_DOT_DIR="$tmp/dot" \
gst-launch-1.0 -q videotestsrc num-buffers=60 is-live=true \
  ! video/x-raw,width=320,height=240,framerate=30/1 ! videoconvert ! queue ! fakesink sync=false
gzip -c "$tmp/trace.log" > "$out/trace-run.log.gz"
cp "$tmp"/dot/*PAUSED_PLAYING.dot "$out/pipeline.PAUSED_PLAYING.dot"
rm -rf "$tmp"
echo "fixtures written to $out:"; ls -la "$out"
