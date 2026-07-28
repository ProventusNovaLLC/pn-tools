#!/usr/bin/env bash
#
# gst-audit.sh — static "why is my pipeline slow" analyzer for GStreamer
#                on NVIDIA Jetson (with a --genio mapping for MediaTek).
#
# Point it at a gst-launch-1.0 pipeline string and it reports, WITHOUT
# running anything: software elements where hardware exists, broken
# NVMM zero-copy paths, missing/untuned queues, VIC contention risk,
# and live-sink sync latency traps. Each finding prints WHY it hurts,
# the FIX, and where the full write-up lives.
#
# Usage:
#   gst-audit.sh "v4l2src ! videoconvert ! x264enc ! matroskamux ! filesink location=a.mkv"
#   gst-audit.sh --genio "nvarguscamerasrc ! nvvidconv ! ..."
#   echo "$PIPELINE" | gst-audit.sh -
#
#   --genio   also map Jetson-specific elements to their MediaTek Genio
#             equivalents (v4l2 codecs / v4l2convert instead of nv*)
#   -q        quiet — findings only, no banner
#   -h        help
#
# Exit codes:  0 = clean (or informational notes only)
#              1 = performance findings
#              3 = usage error
#
# READ-ONLY: never launches the pipeline. The only external tool used is
# gst-inspect-1.0 (optional — used to check element availability on the
# machine you run this on; without it the audit is fully static).
#
# Known v1 limits: tee branches are analyzed as one linear sequence, and
# caps are read as written (no negotiation simulation). Good enough to
# catch the four failure classes above; not a replacement for
# GST_DEBUG=GST_LATENCY:5 tracing.
#
# (c) ProventusNova — MIT license. Part of the pn-tools collection:
#   https://github.com/ProventusNovaLLC/pn-tools

set -u

VERSION="0.1.0-draft"
BLOG="https://proventusnova.com/blog"
URL_PERF="$BLOG/gstreamer-pipeline-performance-jetson"
URL_VIC="$BLOG/nvvidconv-performance-multiple-gstreamer-processes"
URL_LAT="$BLOG/reduce-gstreamer-pipeline-latency-jetson"

QUIET=0
GENIO=0
PIPELINE=""

usage() { sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; }
say()   { printf '%s\n' "$*"; }
log()   { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }
die()   { printf 'gst-audit: %s\n' "$*" >&2; exit 3; }

while [ $# -gt 0 ]; do
  case "$1" in
    --genio) GENIO=1 ;;
    -q) QUIET=1 ;;
    -h|--help) usage; exit 0 ;;
    -V|--version) say "gst-audit.sh $VERSION"; exit 0 ;;
    -) PIPELINE=$(cat) ;;
    *) PIPELINE="${PIPELINE:+$PIPELINE }$1" ;;
  esac
  shift
done

[ -n "${PIPELINE//[[:space:]]/}" ] || die "no pipeline given (try -h)"
# strip gst-launch-1.0 prefix and quoting artifacts
PIPELINE=${PIPELINE#gst-launch-1.0 }
PIPELINE=${PIPELINE//\"/}
PIPELINE=${PIPELINE//\'/}

HAVE_INSPECT=0
command -v gst-inspect-1.0 >/dev/null 2>&1 && HAVE_INSPECT=1

# ------------------------------------------------------- knowledge tables
# SW element -> HW replacement on Jetson, with the measured cost of staying
# in software (from $URL_PERF).
declare -A HW_MAP HW_WHY
HW_MAP[videoconvert]="nvvidconv"
HW_WHY[videoconvert]="videoconvert burns 25-35% CPU for color conversion that nvvidconv does on the VIC engine for <1%"
HW_MAP[videoscale]="nvvidconv"
HW_WHY[videoscale]="videoscale scales on the CPU; nvvidconv scales on the VIC engine for <1% CPU"
HW_MAP[x264enc]="nvv4l2h264enc"
HW_WHY[x264enc]="x264enc burns 50-70% CPU; nvv4l2h264enc uses the NVENC hardware engine for <2%"
HW_MAP[x265enc]="nvv4l2h265enc"
HW_WHY[x265enc]="software HEVC encode saturates the CPU; nvv4l2h265enc runs on NVENC for <2%"
HW_MAP[avdec_h264]="nvv4l2decoder"
HW_WHY[avdec_h264]="avdec_h264 uses 35-50% CPU (and drops frames at 4K30); nvv4l2decoder runs on NVDEC at 1-2% and adds 20-40ms LESS latency at 1080p30"
HW_MAP[avdec_h265]="nvv4l2decoder"
HW_WHY[avdec_h265]="software HEVC decode saturates the CPU; nvv4l2decoder runs on NVDEC at 1-2%"
HW_MAP[jpegdec]="nvjpegdec"
HW_WHY[jpegdec]="jpegdec decodes on the CPU; nvjpegdec uses the hardware JPEG engine"
HW_MAP[jpegenc]="nvjpegenc"
HW_WHY[jpegenc]="jpegenc encodes on the CPU; nvjpegenc uses the hardware JPEG engine"
HW_MAP[autovideosink]="nv3dsink (or nvdrmvideosink headless)"
HW_WHY[autovideosink]="autovideosink picks a CPU/X11 sink (5-15% CPU); the NV sinks render for <1%"
HW_MAP[ximagesink]="nv3dsink (or nvdrmvideosink headless)"
HW_WHY[ximagesink]="ximagesink renders via CPU/X11 (5-15% CPU); the NV sinks render for <1%"
HW_MAP[xvimagesink]="nv3dsink (or nvdrmvideosink headless)"
HW_WHY[xvimagesink]="xvimagesink renders via X11; the NV sinks render for <1% and accept NVMM"

# Jetson element -> Genio equivalent (used with --genio).
declare -A GENIO_MAP
GENIO_MAP[nvarguscamerasrc]="v4l2src device=/dev/videoN io-mode=mmap  (find N via media-ctl -p / v4l2-ctl --list-devices)"
GENIO_MAP[nvvidconv]="v4l2convert output-io-mode=dmabuf capture-io-mode=mmap  (MDP hardware path; userptr falls back to CPU)"
GENIO_MAP[nvvideoconvert]="v4l2convert output-io-mode=dmabuf capture-io-mode=mmap"
GENIO_MAP[nvv4l2h264enc]="v4l2h264enc"
GENIO_MAP[nvv4l2h265enc]="v4l2h265enc"
GENIO_MAP[nvv4l2decoder]="v4l2h264dec / v4l2h265dec"
GENIO_MAP[nvjpegenc]="jpegenc (CPU) — check the BSP for a V4L2 JPEG codec"
GENIO_MAP[nvjpegdec]="jpegdec (CPU) — check the BSP for a V4L2 JPEG codec"
GENIO_MAP[nv3dsink]="waylandsink / kmssink"
GENIO_MAP[nvoverlaysink]="waylandsink / kmssink"
GENIO_MAP[nvdrmvideosink]="kmssink"

ENCODERS="nvv4l2h264enc nvv4l2h265enc x264enc x265enc omxh264enc omxh265enc nvjpegenc jpegenc"
LIVE_SRC="v4l2src nvarguscamerasrc udpsrc rtspsrc tcpclientsrc"
DISPLAY_SINKS="nv3dsink nvdrmvideosink nvoverlaysink nveglglessink autovideosink ximagesink xvimagesink waylandsink kmssink glimagesink"

# ------------------------------------------------------------ tokenize
# Split on '!' into segments; classify each as element / caps / branch-ref.
IFS='!' read -ra RAW_SEGS <<< "$PIPELINE"
ELEMS=()        # element name per element-position
ELEM_SEG=()     # full segment text (element + properties)
CAPS_AFTER=()   # caps string that FOLLOWS element i ("" if none)
last_elem=-1
for seg in "${RAW_SEGS[@]}"; do
  seg=$(printf '%s' "$seg" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
  [ -n "$seg" ] || continue
  first=${seg%% *}
  if [[ "$first" == */* ]]; then                       # caps segment
    [ "$last_elem" -ge 0 ] && CAPS_AFTER[$last_elem]="$seg"
    continue
  fi
  if [[ "$first" == *. ]]; then                        # tee branch ref (t.)
    continue                                           # linearized in v1
  fi
  ELEMS+=("$first")
  ELEM_SEG+=("$seg")
  CAPS_AFTER+=("")
  last_elem=$(( ${#ELEMS[@]} - 1 ))
done

[ ${#ELEMS[@]} -gt 0 ] || die "could not parse any elements out of: $PIPELINE"

has_elem() { local e; for e in "${ELEMS[@]}"; do [ "$e" = "$1" ] && return 0; done; return 1; }
in_list()  { case " $2 " in *" $1 "*) return 0;; esac; return 1; }

FINDINGS=0
INFOS=0
finding() { # finding SEVERITY ID WHAT WHY FIX REF
  local sev=$1
  if [ "$sev" = "INFO" ]; then INFOS=$((INFOS+1)); else FINDINGS=$((FINDINGS+1)); fi
  say "── $sev [$2]"
  say "   what: $3"
  say "   why : $4"
  say "   fix : $5"
  say "   ref : $6"
  say ""
}

log "gst-audit $VERSION — static analysis (pipeline is never launched)"
if [ "$HAVE_INSPECT" -eq 0 ]; then
  log "note: gst-inspect-1.0 not found — element availability not checked"
fi
log "elements: ${ELEMS[*]}"
log ""

# ---------------------------------------------------- check 1: SW vs HW
for i in "${!ELEMS[@]}"; do
  e=${ELEMS[$i]}
  [ -n "${HW_MAP[$e]:-}" ] || continue
  hw=${HW_MAP[$e]%% *}
  avail=""
  if [ "$HAVE_INSPECT" -eq 1 ] && ! gst-inspect-1.0 "$hw" >/dev/null 2>&1; then
    avail=" (note: $hw not present on THIS machine — recommendation assumes a Jetson target)"
  fi
  finding PERF "sw-element" \
    "$e at position $((i+1)) — software element where Jetson hardware exists" \
    "${HW_WHY[$e]}. Rule of thumb: >5% total CPU at 1080p30 on Orin means a CPU element is in the path." \
    "replace with ${HW_MAP[$e]}$avail" \
    "$URL_PERF"
done

# ------------------------------------- check 2: NVMM zero-copy breaks
# Walk the caps sequence: NVMM -> sysmem -> NVMM is a round trip; each
# domain flip after the first NVMM copies every frame through the CPU.
domain="" flips=0 first_nvmm=0 roundtrip=0
for i in "${!ELEMS[@]}"; do
  caps=${CAPS_AFTER[$i]}
  [ -n "$caps" ] || continue
  if [[ "$caps" == *"memory:NVMM"* ]]; then
    [ "$domain" = "sys" ] && [ "$first_nvmm" -eq 1 ] && roundtrip=$((roundtrip+1))
    domain="nvmm"; first_nvmm=1
  elif [[ "$caps" == video/x-raw* ]]; then
    [ "$domain" = "nvmm" ] && flips=$((flips+1))
    domain="sys"
  fi
done
if [ "$roundtrip" -gt 0 ]; then
  finding PERF "nvmm-roundtrip" \
    "caps go NVMM → system memory → NVMM ($roundtrip round trip(s)) — zero-copy is broken" \
    "every NVMM→sysmem edge copies each frame through the CPU: ~5-15ms per frame at 1080p30, roughly 720MB/s of pointless memory bandwidth at 4K30 — then you pay it AGAIN going back" \
    "keep the whole path in video/x-raw(memory:NVMM) between NV elements; only drop to system memory once, at the very end, if a CPU consumer truly needs it" \
    "$URL_PERF"
elif [ "$flips" -gt 0 ] && has_elem videoconvert; then
  finding PERF "nvmm-exit-to-cpu" \
    "pipeline leaves NVMM into a CPU path (videoconvert downstream)" \
    "the NVMM→sysmem edge copies every frame through the CPU (~5-15ms/frame at 1080p30) and everything after it runs in software" \
    "move color/scale work before the NVMM exit (nvvidconv inside the NVMM domain), and exit NVMM as late as possible" \
    "$URL_PERF"
fi

# --------------------------------- check 3: queues around encoders
for i in "${!ELEMS[@]}"; do
  e=${ELEMS[$i]}
  in_list "$e" "$ENCODERS" || continue
  prev_has_queue=0
  for (( j=0; j<i; j++ )); do
    [ "${ELEMS[$j]}" = "queue" ] && prev_has_queue=1
  done
  if [ "$prev_has_queue" -eq 0 ]; then
    finding WARN "no-queue-before-encoder" \
      "$e at position $((i+1)) with no queue anywhere upstream" \
      "an encoder is a slow element; without a queue the upstream thread blocks on it and the whole pipeline stalls at the encoder's pace" \
      "add 'queue max-size-buffers=4' immediately before $e to decouple the threads (leaky=2 max-size-buffers=1 on live paths where dropping beats buffering)" \
      "$URL_LAT"
  fi
done

# --------------------------------- check 4: VIC contention warning
if has_elem nvvidconv || has_elem nvvideoconvert; then
  finding INFO "vic-contention" \
    "pipeline uses the VIC engine (nvvidconv/nvvideoconvert)" \
    "the VIC has only 2-4 concurrent contexts on Orin-class parts; when MULTIPLE PROCESSES each run VIC pipelines they serialize on it and throughput can collapse 5-10x (measured)" \
    "run multi-camera/multi-stream work as ONE GStreamer process with multiple pipelines, not N processes; confirm contention with tegrastats (high VIC% across processes)" \
    "$URL_VIC"
fi

# --------------------------------- check 5: live-sink sync latency
is_live=0
for s in $LIVE_SRC; do has_elem "$s" && is_live=1; done
if [ "$is_live" -eq 1 ]; then
  for i in "${!ELEMS[@]}"; do
    e=${ELEMS[$i]}
    in_list "$e" "$DISPLAY_SINKS" || continue
    if [[ "${ELEM_SEG[$i]}" != *"sync=false"* ]]; then
      finding WARN "sink-sync" \
        "live source with display sink $e lacking sync=false" \
        "the sink holds frames to match presentation timestamps — on a live camera this is the single biggest latency contributor (hundreds of ms vs single digits)" \
        "add sync=false to $e" \
        "$URL_LAT"
    fi
  done
  for i in "${!ELEMS[@]}"; do
    if [ "${ELEMS[$i]}" = "queue" ] && \
       [[ "${ELEM_SEG[$i]}" != *max-size-buffers* ]]; then
      finding INFO "untuned-queue" \
        "bare 'queue' at position $((i+1)) on a live pipeline" \
        "a default queue can hold ~200 frames — nearly 7 seconds of latency quietly accumulating at 30fps" \
        "use 'queue max-size-buffers=1 leaky=2' on live paths so stale frames are dropped, keeping end-to-end delay at one frame" \
        "$URL_LAT"
    fi
  done
fi

# --------------------------------- check 6: appsink hygiene
for i in "${!ELEMS[@]}"; do
  if [ "${ELEMS[$i]}" = "appsink" ]; then
    seg=${ELEM_SEG[$i]}
    if [[ "$seg" != *drop=* || "$seg" != *max-buffers=* ]]; then
      finding WARN "appsink-untuned" \
        "appsink without max-buffers=1 drop=true" \
        "a slow callback back-pressures the whole pipeline; appsink also pulls NVMM buffers into system memory (a per-frame copy)" \
        "set 'appsink max-buffers=1 drop=true' so a slow consumer drops frames instead of stalling capture" \
        "$URL_PERF"
    fi
  fi
done

# --------------------------------- check 7: --genio element mapping
if [ "$GENIO" -eq 1 ]; then
  mapped=0
  for i in "${!ELEMS[@]}"; do
    e=${ELEMS[$i]}
    [ -n "${GENIO_MAP[$e]:-}" ] || continue
    mapped=$((mapped+1))
    finding WARN "jetson-only-element" \
      "$e at position $((i+1)) does not exist on MediaTek Genio" \
      "nv* elements are NVIDIA L4T/JetPack builds; Genio uses standard V4L2 M2M codecs and v4l2convert (dmabuf) for its hardware paths" \
      "on Genio use: ${GENIO_MAP[$e]}" \
      "$URL_PERF"
  done
  if [ "$mapped" -gt 0 ] || [[ "$PIPELINE" == *"memory:NVMM"* ]]; then
    say "note: 'video/x-raw(memory:NVMM)' caps are Jetson-only. On Genio the"
    say "      zero-copy path is dmabuf, selected via v4l2convert io-modes"
    say "      (output-io-mode=dmabuf capture-io-mode=mmap), not a caps feature."
    say ""
  fi
fi

# ------------------------------------------------------------- summary
say "audit: $FINDINGS finding(s), $INFOS informational note(s)."
if [ "$FINDINGS" -gt 0 ]; then
  say "measure before/after: GST_DEBUG=GST_LATENCY:5 <your pipeline>  and tegrastats"
  exit 1
fi
say "clean — no performance findings."
exit 0
