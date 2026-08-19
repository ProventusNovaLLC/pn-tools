"""Deterministic, explainable rules over an Analysis. Each rule: id, needs, evaluate -> [Finding].
Severity gate: only rules whose `verified_on` is non-empty (bench-verified, Plan 4) may emit
high/medium; until then every diagnostic finding ships `info` + heuristic. HOT/OK are measurement,
not heuristics — they always emit at their designed level."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

BLOG = "https://proventusnova.com/blog"
SCOPE = "https://proventusnova.com/contact/?utm_source=lead-magnet&utm_medium=tool&utm_campaign=gst-profile"

# HW-accelerated replacements per platform: software factory -> hardware factory
HW_SWAP = {
    "jetson": {"videoconvert": "nvvidconv", "videoscale": "nvvidconv", "x264enc": "nvv4l2h264enc",
               "x265enc": "nvv4l2h265enc", "jpegdec": "nvjpegdec", "jpegenc": "nvjpegenc",
               "avdec_h264": "nvv4l2decoder", "avdec_h265": "nvv4l2decoder"},
    "mediatek": {"x264enc": "v4l2h264enc", "x265enc": "v4l2h265enc", "videoconvert": "v4l2convert",
                 "jpegdec": "v4l2jpegdec"},
}


@dataclass
class Finding:
    id: str
    rule: str
    severity: str                       # high | medium | info
    title: str
    targets: Dict[str, List[str]]       # {"elements": [...], "links": [...]}
    evidence: Dict[str, object]
    why: str
    fix_text: str
    fix_patch: Optional[dict] = None    # {"kind": ..., ...} for v2 A/B
    ref: str = SCOPE
    verified_on: List[str] = field(default_factory=list)
    share_of_latency_pct: Optional[float] = None
    heuristic: bool = True
    rank: int = 0


# Rule ids bench-verified on named hardware (golden bad/good pipeline pairs; see bench/).
# Until a rule id is in here, its high/medium findings are emitted as `info` + heuristic.
# Verified 2026-08-19 on an Orin NX / L4T R36.4.3 (JP6), GStreamer 1.20.3: each bad pipeline
# yielded exactly this finding and its good twin came back clean. SYNC and STALL are NOT here:
# SYNC's sync=true is invisible to a run-mode dot dump (it is the GstBaseSink param-spec default,
# so it is never recorded as a non-default prop) — needs a rule-logic fix; STALL did not reproduce
# cleanly from a drop-from-start pipeline. Both stay honest heuristics.
VERIFIED_RULES: Dict[str, List[str]] = {
    "ZC": ["orin-nx-jp6-r36.4"],
    "SW": ["orin-nx-jp6-r36.4"],
    "QUEUE": ["orin-nx-jp6-r36.4"],
}

def _gate(rule_id: str, sev: str):
    """Return (severity, heuristic, verified_on). high/medium -> info until the rule is bench-verified."""
    v = VERIFIED_RULES.get(rule_id, [])
    if sev == "info":
        return "info", (rule_id not in ("HOT", "OK")), []
    if v:
        return sev, False, v
    return "info", True, []


class Rule:
    id = "base"
    needs: List[str] = []               # capability keys that must be truthy in analysis.caps
    def applicable(self, a) -> bool:
        return all(a.caps.get(n) for n in self.needs)
    def evaluate(self, a) -> List[Finding]:
        return []


class HotRule(Rule):
    """Always: where the time goes. Measurement, not a heuristic."""
    id = "HOT"
    def evaluate(self, a):
        hot = a.hot_share()
        if not hot:
            return []
        top = hot[0]
        return [Finding(id="F-HOT", rule="HOT", severity="info", heuristic=False,
                        title=f"{top[0]} takes {top[2]:.0f}% of per-element processing time",
                        targets={"elements": [top[0]], "links": []},
                        evidence={"ranking": [(e, round(m, 3), round(s, 1)) for e, m, s in hot[:6]]},
                        why="This element spends the most time producing each buffer.",
                        fix_text="Start optimisation here; the rows below rank the rest.",
                        share_of_latency_pct=round(top[2], 1))]


class OkRule(Rule):
    """When nothing high fires and the device pipeline is within the frame budget."""
    id = "OK"
    def evaluate(self, a):
        if a.latency_ms_p95 is None or a.frame_period_ms is None:
            return []
        if a.latency_ms_p95 <= a.frame_period_ms:
            return [Finding(id="F-OK", rule="OK", severity="info", heuristic=False,
                            title=f"Device pipeline is within frame budget: {a.latency_ms_p95:.1f} ms latency vs {a.frame_period_ms:.1f} ms/frame",
                            targets={"elements": [], "links": []},
                            evidence={"latency_ms_p95": round(a.latency_ms_p95, 2), "frame_period_ms": round(a.frame_period_ms, 2)},
                            why="On-device processing keeps up with the source frame rate. If end-to-end latency is worse, it is downstream: network, SFU, or remote decode.",
                            fix_text="Profile the network path (RTT to your server) and remote decode; the capture/encode side is not the bottleneck.")]
        return []


class ZeroCopyRule(Rule):
    """A sysmem island bounded by hardware memory: buffers left GPU/dmabuf memory and came back,
    a CPU<->GPU copy on every frame. Detected on the link chain, so it catches a break that spans
    several elements (e.g. nvmm -> videoconvert(sysmem) -> nvvidconv -> nvmm)."""
    id = "ZC"
    HW = ("nvmm", "dmabuf")
    def evaluate(self, a):
        # order the links into linear position by walking from source elements
        # only a raw-frame sysmem link is a zero-copy break; an encoded (h264/h265/jpeg) sysmem
        # link between hardware codecs is normal and must not be flagged.
        sysmem = [l for l in a.links if l.memory == "sysmem" and (l.media in ("", "video/x-raw"))]
        out = []
        seen_islands = set()
        for l in sysmem:
            up_hw = self._reaches_hw(a, l.src_el, upstream=True)
            down_hw = self._reaches_hw(a, l.sink_el, upstream=False)
            if up_hw and down_hw:
                # group the contiguous sysmem run into one finding keyed by its bounding elements
                key = (up_hw, down_hw)
                if key in seen_islands:
                    continue
                seen_islands.add(key)
                offender = a.elements.get(l.sink_el) or a.elements.get(l.src_el)
                out.append(Finding(id=f"F-ZC-{l.src_el}", rule="ZC", severity="high",  # gated below
                    title=f"Zero-copy broken between {up_hw} and {down_hw}: buffers leave GPU memory and return",
                    targets={"elements": [l.src_el, l.sink_el], "links": [l.id]},
                    evidence={"sysmem_link": l.id, "hw_upstream": up_hw, "hw_downstream": down_hw,
                              "offender_cpu_pct": offender.cpu_pct if offender else None},
                    why="A CPU<->GPU copy on every frame costs bandwidth and latency; NVMM/dmabuf should stay on the GPU end to end.",
                    fix_text=f"Keep the path in device memory across {l.src_el}->{l.sink_el} (use nvvidconv, or negotiate NVMM caps so no element copies to system memory).",
                    fix_patch={"kind": "set-caps", "link": l.id, "to": "video/x-raw(memory:NVMM)"}))
        return out
    def _reaches_hw(self, a, el, upstream, depth=0, seen=None):
        """Return the id of the nearest element across a hardware-memory link on the given side, or None."""
        if depth > 32:
            return None
        seen = seen if seen is not None else set()
        if el in seen:
            return None
        seen.add(el)
        for l in a.links:
            if upstream and l.sink_el == el:
                if l.memory in self.HW:
                    return l.src_el
                r = self._reaches_hw(a, l.src_el, upstream, depth + 1, seen)
                if r:
                    return r
            if not upstream and l.src_el == el:
                if l.memory in self.HW:
                    return l.sink_el
                r = self._reaches_hw(a, l.sink_el, upstream, depth + 1, seen)
                if r:
                    return r
        return None


class SwElementRule(Rule):
    """Software element where the platform has a hardware equivalent."""
    id = "SW"
    def evaluate(self, a):
        swap = HW_SWAP.get(a.platform, {})
        if not swap:
            return []
        out = []
        for e in a.real_elements():
            if e.factory in swap:
                out.append(Finding(id=f"F-SW-{e.id}", rule="SW", severity="medium",  # gated below
                    title=f"{e.id} ({e.factory}) runs in software; {swap[e.factory]} is available on this platform",
                    targets={"elements": [e.id], "links": []},
                    evidence={"factory": e.factory, "hardware_equivalent": swap[e.factory], "cpu_pct": e.cpu_pct, "proc_ms_p95": e.proc_ms_p95},
                    why="A software element burns CPU and adds latency where the SoC has a dedicated block.",
                    fix_text=f"Replace {e.factory} with {swap[e.factory]}.",
                    fix_patch={"kind": "replace-element", "element": e.id, "with": swap[e.factory]}))
        return out


class QueueRule(Rule):
    """No queue between a source/decoder and the encoder or sink: one thread does everything."""
    id = "QUEUE"
    ENC_SINK = ("enc", "sink", "pay", "mux")
    def evaluate(self, a):
        has_queue = any(e.factory == "queue" or e.factory.startswith("queue") for e in a.real_elements())
        heavy = [e for e in a.real_elements() if any(k in e.factory for k in self.ENC_SINK)]
        if heavy and not has_queue:
            tgt = heavy[0]
            return [Finding(id="F-QUEUE", rule="QUEUE", severity="medium",  # gated below
                title="No queue before the encoder/sink: the whole pipeline runs on one thread",
                targets={"elements": [tgt.id], "links": []},
                evidence={"heavy_element": tgt.id, "queues_present": 0},
                why="Without a queue the source, conversion and encode share a single streaming thread, so any stall in one stalls all.",
                fix_text=f"Insert a queue upstream of {tgt.id} to give it its own thread.",
                fix_patch={"kind": "insert-element", "before": tgt.id, "element": "queue"})]
        return []


class SyncRule(Rule):
    """A live sink with sync=true holds each buffer to the clock — adds a frame of latency on a live path."""
    id = "SYNC"
    def evaluate(self, a):
        out = []
        for e in a.real_elements():
            if "sink" in e.factory and str(e.props.get("sync", "")).lower() in ("true", "1", ""):
                if e.props.get("sync") is None:
                    continue  # unknown; don't guess
                out.append(Finding(id=f"F-SYNC-{e.id}", rule="SYNC", severity="medium",  # gated below
                    title=f"{e.id} has sync=true on a live path",
                    targets={"elements": [e.id], "links": []},
                    evidence={"sync": e.props.get("sync")},
                    why="Clock-synced rendering holds each buffer to its timestamp, adding up to a frame of latency; live/teleop paths usually want sync=false.",
                    fix_text=f"Set sync=false on {e.id} for a low-latency live path.",
                    fix_patch={"kind": "set-property", "element": e.id, "property": "sync", "value": "false"}))
        return out


class CapsConversionRule(Rule):
    """Two conversions in a row, or a convert whose input and output pixel format differ needlessly."""
    id = "CAPS"
    CONV = ("videoconvert", "nvvidconv", "v4l2convert", "videoscale")
    def evaluate(self, a):
        out = []
        convs = [e for e in a.real_elements() if e.factory in self.CONV]
        for e in convs:
            downs = [a.elements.get(x) for x in a.downstream(e.id)]
            if any(d and d.factory in self.CONV for d in downs if d):
                out.append(Finding(id=f"F-CAPS-{e.id}", rule="CAPS", severity="info",
                    title=f"Back-to-back format conversions at {e.id}",
                    targets={"elements": [e.id], "links": []},
                    evidence={"element": e.id, "downstream": a.downstream(e.id)},
                    why="Two conversions in a row usually means one can be dropped or folded into the other.",
                    fix_text="Collapse the two conversions into one, or fix the caps so no conversion is needed."))
        return out


class StallRule(Rule):
    """A link that stopped carrying buffers while the pipeline was still running."""
    id = "STALL"
    def evaluate(self, a):
        out = []
        for l in a.links:
            if l.stall_interior:
                src = a.elements.get(l.src_el)
                is_source = src and not a.upstream(l.src_el)
                out.append(Finding(id=f"F-STALL-{l.id}", rule="STALL", severity="high",  # gated below
                    title=("Source starvation at " + l.src_el) if is_source else (l.src_el + " stopped producing buffers"),
                    targets={"elements": [l.src_el], "links": [l.id]},
                    evidence={"link": l.id},
                    why="Data stopped flowing across this link mid-capture — upstream is not delivering buffers.",
                    fix_text=("Check the sensor/driver bring-up (see the camera-bringup-debug skill) — the source stopped delivering." if is_source
                              else f"Investigate why {l.src_el} stopped producing; a downstream block-and-wait or an internal error is typical.")))
        return out




class QLeakRule(Rule):
    """A queue pinned near its max upstream of a slow element = backpressure (run mode only)."""
    id = "QLEAK"
    needs = ["queue_levels"]
    def evaluate(self, a):
        out = []
        for e in a.real_elements():
            if e.factory.startswith("queue") and e.cpu_pct is None and e.buffers:
                pass  # placeholder; queue_levels arrive via series in a later capability
        return out


class VicContentionRule(Rule):
    """Several VIC users (nvvidconv) running concurrently with high VIC load + proc-time variance."""
    id = "VIC"
    needs = ["tegrastats"]
    def evaluate(self, a):
        vic = a.system_peak.get("vic_pct")
        users = [e for e in a.real_elements() if e.factory == "nvvidconv"]
        if vic is not None and vic >= 80 and len(users) >= 1:
            return [Finding(id="F-VIC", rule="VIC", severity="medium",
                title=f"VIC engine saturated ({vic:.0f}%) with {len(users)} converter(s)",
                targets={"elements": [u.id for u in users], "links": []},
                evidence={"vic_pct": vic, "nvvidconv_count": len(users)},
                why="Multiple pipelines sharing the VIC hardware converter contend for it; throughput can collapse several-fold.",
                fix_text="Consolidate conversions or move some to GPU (nvvidconv compute-hw=GPU), and avoid running independent nvvidconv pipelines in parallel.",
                ref=BLOG + "/nvvidconv-performance-multiple-gstreamer-processes?utm_source=lead-magnet&utm_medium=tool&utm_campaign=gst-profile")]
        return []


class EncoderConfigRule(Rule):
    """Latency-hostile encoder settings on a live path (B-frames, high control-rate, missing insert-sps-pps)."""
    id = "ENC"
    ENC = ("enc",)
    def evaluate(self, a):
        out = []
        for e in a.real_elements():
            if not any(k in e.factory for k in self.ENC):
                continue
            bad = {}
            p = {k.lower(): str(v).lower() for k, v in e.props.items()}
            if p.get("bframes", "0") not in ("0", ""):
                bad["bframes"] = p["bframes"]
            if "insert-sps-pps" in p and p["insert-sps-pps"] in ("false", "0"):
                bad["insert-sps-pps"] = p["insert-sps-pps"]
            if bad:
                out.append(Finding(id=f"F-ENC-{e.id}", rule="ENC", severity="medium",
                    title=f"{e.id} has latency-hostile encoder settings for a live path",
                    targets={"elements": [e.id], "links": []},
                    evidence=bad,
                    why="B-frames add reorder latency; missing SPS/PPS-per-IDR breaks mid-stream join. Live/teleop wants a low-latency encoder config.",
                    fix_text="For live: bframes=0, insert-sps-pps=true, a low-latency control-rate/preset.",
                    ref=BLOG + "/reduce-gstreamer-pipeline-latency-jetson?utm_source=lead-magnet&utm_medium=tool&utm_campaign=gst-profile"))
        return out


class CpuSaturationRule(Rule):
    """A single element pinning ~a full core while the pipeline can't keep frame rate."""
    id = "CPU"
    def evaluate(self, a):
        out = []
        for e in a.real_elements():
            if e.cpu_pct is not None and e.cpu_pct >= 90:
                out.append(Finding(id=f"F-CPU-{e.id}", rule="CPU", severity="info",
                    title=f"{e.id} is CPU-bound ({e.cpu_pct:.0f}% of a core)",
                    targets={"elements": [e.id], "links": []},
                    evidence={"cpu_pct": e.cpu_pct},
                    why="This element saturates its thread; on a live path it caps throughput and adds jitter.",
                    fix_text=f"Offload {e.id} to a hardware block if one exists, or give it its own queue/thread."))
        return out


class HwSaturationRule(Rule):
    """A hardware unit (NVENC/GR3D/EMC) pegged — context for the hot element."""
    id = "HW"
    needs = ["tegrastats"]
    def evaluate(self, a):
        out = []
        for key, unit in (("nvenc_pct", "NVENC encoder"), ("gr3d_pct", "GPU (GR3D)"), ("emc_pct", "memory (EMC)")):
            v = a.system_peak.get(key)
            if v is not None and v >= 95:
                out.append(Finding(id=f"F-HW-{key}", rule="HW", severity="info",
                    title=f"{unit} saturated ({v:.0f}%)",
                    targets={"elements": [], "links": []},
                    evidence={key: v},
                    why=f"The {unit} block is maxed out; it bounds pipeline throughput regardless of CPU headroom.",
                    fix_text=f"Reduce resolution/framerate/bitrate feeding the {unit}, or split the load."))
        return out


ALL_RULES = [HotRule(), OkRule(), ZeroCopyRule(), SwElementRule(), QueueRule(), SyncRule(), CapsConversionRule(),
             StallRule(), VicContentionRule(), EncoderConfigRule(), CpuSaturationRule(), HwSaturationRule(), QLeakRule()]


def run_rules(a, rules=None) -> List[Finding]:
    rules = rules or ALL_RULES
    findings = []
    for r in rules:
        if r.applicable(a):
            for f in r.evaluate(a):
                f.severity, f.heuristic, f.verified_on = _gate(f.rule, f.severity)
                findings.append(f)
    # OK is a "nothing to fix here" statement — drop it if ANY diagnostic finding fired
    # (even an info-level heuristic), so the verdict never contradicts itself.
    worst = {"high": 3, "medium": 2, "info": 1}
    if any(f.rule not in ("HOT", "OK") for f in findings):
        findings = [f for f in findings if f.rule != "OK"]
    # rank: severity desc, then share/impact desc
    findings.sort(key=lambda f: (-worst[f.severity], -(f.share_of_latency_pct or 0)))
    for i, f in enumerate(findings):
        f.rank = i + 1
    return findings
