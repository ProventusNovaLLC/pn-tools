"""Render an Analysis + ranked findings into the human verdict (terminal + a structured dict for the panel/Skill)."""
from typing import List
from gst_profile import rules as R


def header(a) -> str:
    lat = a.latency_ms_p95
    fp = a.frame_period_ms
    parts = []
    if lat is not None:
        parts.append(f"pipeline latency p95 {lat:.1f} ms" + (f" (frame period {fp:.1f} ms)" if fp is not None else ""))
    elif fp is not None:
        parts.append(f"frame period {fp:.1f} ms")
    hot = a.hot_share()
    if hot:
        where = " · ".join(f"{eid} {share:.0f}%" for eid, _, share in hot[:3])
        parts.append("where the time goes: " + where)
    return "  ·  ".join(parts) if parts else "no per-element timing on this capture"


def render_text(a, findings: List) -> str:
    lines = ["", "gst-profile verdict", "  " + header(a)]
    if not findings:
        lines.append("  no findings.")
        return "\n".join(lines)
    lines.append("")
    for f in findings:
        tag = {"high": "!!", "medium": "! ", "info": "  "}[f.severity]
        heur = "  (heuristic — not yet bench-verified)" if f.heuristic and f.severity == "info" and f.rule not in ("HOT", "OK") else ""
        lines.append(f"  {tag}[{f.severity:<6}] {f.rule:<5} {f.title}{heur}")
        lines.append(f"          why: {f.why}")
        lines.append(f"          fix: {f.fix_text}")
    lines.append("")
    lines.append(f"  scoping: {R.SCOPE}")
    return "\n".join(lines)


def to_dict(a, findings: List) -> dict:
    return {
        "header": header(a),
        "scope": R.SCOPE,
        "latency_ms_p95": a.latency_ms_p95,
        "frame_period_ms": a.frame_period_ms,
        "hot": [{"element": e, "proc_ms_p95": round(m, 3), "share_pct": round(s, 1)} for e, m, s in a.hot_share()[:8]],
        "findings": [{"id": f.id, "rule": f.rule, "severity": f.severity, "title": f.title, "rank": f.rank,
                      "targets": f.targets, "evidence": f.evidence, "why": f.why, "fix_text": f.fix_text,
                      "fix_patch": f.fix_patch, "ref": f.ref, "heuristic": f.heuristic,
                      "verified_on": f.verified_on, "share_of_latency_pct": f.share_of_latency_pct}
                     for f in findings],
        "has_high_or_medium": any(f.severity in ("high", "medium") for f in findings),
    }
