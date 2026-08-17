"""gst-profile command line: check | run | wrap | analyze (Plan 1: headless; live UI and report arrive in later plans)."""
import argparse
import gzip
import json
import os
import shlex
import signal
import sys
import threading
import time
from typing import List, Optional

from . import __version__
from .preflight import check, render
from .model import Session
from .launcher import Launcher
from .procstat import ProcStat
from .tegrastats import TegrastatsSource
from .launchparse import parse_launch, LaunchParseError

EXIT_CLEAN, EXIT_FINDINGS, EXIT_CHILD_FAILED, EXIT_USAGE = 0, 1, 2, 3


def _parse_duration(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    s = s.strip().lower()
    mult = 1.0
    if s.endswith("ms"):
        return float(s[:-2]) / 1000.0
    if s.endswith("s"):
        s = s[:-1]
    elif s.endswith("m"):
        s, mult = s[:-1], 60.0
    return float(s) * mult


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gst-profile", description="Live GStreamer pipeline profiler: where does the time go?")
    p.add_argument("--version", action="version", version=f"gst-profile {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="preflight: what can this machine measure?")

    def common(sp):
        sp.add_argument("--duration", help="stop after e.g. 30s / 2m (default: until Ctrl-C or the pipeline ends)")
        sp.add_argument("--out", help="write session JSON here (default: ./gst-profile-<id>.json)")
        sp.add_argument("--no-ui", action="store_true", help="headless capture (Plan 1: always headless)")
        sp.add_argument("--print", dest="print_summary", action="store_true", help="print the model summary at the end")
        sp.add_argument("--lite", action="store_true", help="latency tracer only (no stats): minimal overhead, no bytes/s")
        sp.add_argument("--tracers", help="override GST_TRACERS verbatim")
        sp.add_argument("--label", default="", help="session label (v2 A/B)")

    r = sub.add_parser("run", help="launch a gst-launch pipeline string under the profiler")
    r.add_argument("launch", help="pipeline description, quoted")
    common(r)
    w = sub.add_parser("wrap", help="run your own binary under the profiler: gst-profile wrap [flags] -- ./app args")
    w.add_argument("command", nargs=argparse.REMAINDER, help="-- your command and its arguments")
    common(w)
    a = sub.add_parser("analyze", help="build a session from an existing GST_DEBUG log (or re-print a session JSON)")
    a.add_argument("path")
    a.add_argument("--dot", action="append", default=[], help="dot dump(s) to merge for topology/caps")
    a.add_argument("--out")
    a.add_argument("--print", dest="print_summary", action="store_true")
    return p


# ---- summary (pre-verdict; the rule engine replaces this in Plan 2) -----------------
def summarize(session: Session) -> str:
    d = session.to_dict()
    g, s = d["graph"], d["series"]
    lines = [f"session {d['session']['id']}  mode={d['session']['mode']}  duration={d['session']['duration_s']}s  "
             f"records={d['session']['parse']['records']}  unparsed={d['session']['parse']['unparsed']}",
             f"target: gstreamer {d['target']['gstreamer'] or '?'}  platform {d['target']['platform']}  "
             f"sources {', '.join(d['target']['sources_present'])}"]
    lines.append("pipeline:")
    for l in g["links"]:
        lines.append(f"  {l['src']:>28} -> {l['sink']:<28} [{l['memory']}{(' ' + l['format']) if l['format'] else ''}]")
    rows = len(s["t"])
    if rows:
        def last_valid(vals):
            v = [x for x in vals if x is not None]
            return v[-1] if v else None
        def p95_of(vals):
            v = sorted(x for x in vals if x is not None)
            return v[int(0.95 * (len(v) - 1))] if v else None
        lat = p95_of(s["pipeline"]["latency_ms_p95"])
        lines.append(f"pipeline latency p95: {lat:.2f} ms" if lat is not None else "pipeline latency: n/a (no source->sink latency records)")
        hot = []
        for eid, cols in s["elements"].items():
            p = p95_of(cols["proc_ms_p95"])
            c = last_valid(cols["cpu_pct"])
            if p is not None or c is not None:
                hot.append((p or 0.0, eid, p, c))
        hot.sort(reverse=True)
        total = sum(h[0] for h in hot) or 1.0
        lines.append("where the time goes (proc p95, share, cpu%):")
        for _, eid, p, c in hot[:8]:
            lines.append(f"  {eid:<24} {('%.3f ms' % p) if p is not None else '   n/a  ':>10}  {100.0 * (p or 0) / total:5.1f}%  {('%.0f%%' % c) if c is not None else ''}")
        for lid, cols in s["links"].items():
            if any(cols["stalled"]):
                lines.append(f"  STALLED at some point: {lid}")
    else:
        lines.append("no windows aggregated (pipeline produced no tracer records)")
    return "\n".join(lines)


# ---- commands ------------------------------------------------------------------------
def cmd_check(_args) -> int:
    print(render(check()))
    return EXIT_CLEAN


def _capture(session: Session, cmd: List[str], mode: str, args) -> int:
    caps = check()
    session.target = caps.to_target()
    session.graph.platform = caps.platform
    duration = _parse_duration(args.duration)
    lock = threading.Lock()

    def on_line(line):
        with lock:
            session.ingest_line(line)

    def on_dot(text):
        with lock:
            session.ingest_dot(text)

    launcher = Launcher(cmd, on_line, on_dot, mode=mode, element_latency=caps.element_latency, lite=args.lite, tracers=args.tracers)
    tegra = TegrastatsSource()
    launcher.start()
    tegra.start()
    ps = ProcStat(launcher.proc.pid)
    started = time.time()
    print(f"gst-profile: capturing ({mode})  pid={launcher.proc.pid}  Ctrl-C to stop"
          + (f"  duration={duration}s" if duration else ""), file=sys.stderr)
    stopping = {"flag": False}

    def on_sigint(_s, _f):
        stopping["flag"] = True
    old = signal.signal(signal.SIGINT, on_sigint)
    try:
        while launcher.running() and not stopping["flag"]:
            time.sleep(0.25)
            now = time.time()
            with lock:
                session.ingest_cpu(ps.sample(now))
                if tegra.available:
                    session.ingest_tegrastats(tegra.latest())
                # tick in the tracer's clock domain: latest record ts (wall clock of the child) + window
                if session.agg.t0_ns is not None and session.agg._win_start is not None:
                    session.agg.close_window(session.agg._win_start)   # no-op unless a record moved us past a window
            if duration and now - started >= duration:
                break
    finally:
        signal.signal(signal.SIGINT, old)
    code = launcher.stop()
    tegra.stop()
    with lock:
        if session.agg._win_start is not None:
            session.agg.close_window(session.agg._win_start + session.agg.window_ns)
        session.add_event("child-exit", f"exit code {code}")
        session.notes.append(f"lines read {launcher.lines_read}, dropped {launcher.dropped}")
    launcher.cleanup()
    out = args.out or f"gst-profile-{session.id}.json"
    with open(out, "w") as fh:
        fh.write(session.to_json())
    print(f"gst-profile: session written to {out}", file=sys.stderr)
    if args.print_summary:
        print(summarize(session))
    if code not in (0, None) and not stopping["flag"] and not duration:
        return EXIT_CHILD_FAILED
    return EXIT_CLEAN


def cmd_run(args) -> int:
    caps = check()
    if not caps.gst_launch:
        print("gst-profile: gst-launch-1.0 not found; `run` needs it (use `wrap` for your own binary)", file=sys.stderr)
        return EXIT_USAGE
    try:
        static_graph, notes = parse_launch(args.launch, platform=caps.platform)
    except LaunchParseError as e:
        print(f"gst-profile: cannot parse pipeline: {e}", file=sys.stderr)
        return EXIT_USAGE
    session = Session(mode="run", launch=args.launch, label=args.label)
    session.notes.extend(notes)
    # pre-seed the graph from the launch string so static facts (props, caps filters) exist before first buffer
    for el in static_graph.elements.values():
        e = session.graph.add_element(el.id, factory=el.factory)
        e.props.update(el.props)
    for l in static_graph.links.values():
        session.graph.add_link(l.src, l.sink, caps=l.caps)
    cmd = [caps.gst_launch, "-q"] + shlex.split(args.launch)
    return _capture(session, cmd, "run", args)


def cmd_wrap(args) -> int:
    cmd = list(args.command)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("gst-profile wrap: give the command after `--`", file=sys.stderr)
        return EXIT_USAGE
    session = Session(mode="wrap", command=cmd, label=args.label)
    return _capture(session, cmd, "wrap", args)


def cmd_analyze(args) -> int:
    if not os.path.exists(args.path):
        print(f"gst-profile: {args.path} not found", file=sys.stderr)
        return EXIT_USAGE
    opener = gzip.open if args.path.endswith(".gz") else open
    with opener(args.path, "rb") as fh:
        head = fh.read(64)
    if head.lstrip().startswith(b"{"):
        with opener(args.path, "rt") as fh:
            session = Session.from_dict(json.load(fh))
    else:
        session = Session(mode="analyze")
        with opener(args.path, "rt", errors="replace") as fh:
            for line in fh:
                session.ingest_line(line)
        for dp in args.dot:
            with open(dp) as fh:
                session.ingest_dot(fh.read())
        if session.agg._win_start is not None:
            session.agg.close_window(session.agg._win_start + session.agg.window_ns)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(session.to_json())
        print(f"gst-profile: session written to {args.out}", file=sys.stderr)
    if args.print_summary or not args.out:
        print(summarize(session))
    return EXIT_CLEAN


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return {"check": cmd_check, "run": cmd_run, "wrap": cmd_wrap, "analyze": cmd_analyze}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
