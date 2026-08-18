"""gst-profile command line. Plan 2: the rule engine's verdict is the default output of
run/wrap/analyze; run/wrap serve a live view over SSE unless --no-ui; analyze --serve browses a
recorded session; report writes a self-contained HTML; exit code 1 signals a high/medium finding."""
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
from . import analysis, rules, verdict, server as srv

EXIT_CLEAN, EXIT_FINDINGS, EXIT_CHILD_FAILED, EXIT_USAGE = 0, 1, 2, 3

_PAGE = os.path.join(os.path.dirname(__file__), "panel", "live.html")


class UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise UsageError(message)


def _parse_duration(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    s = s.strip().lower()
    if s.endswith("ms"):
        return float(s[:-2]) / 1000.0
    mult = 1.0
    if s.endswith("s"):
        s = s[:-1]
    elif s.endswith("m"):
        s, mult = s[:-1], 60.0
    return float(s) * mult


def _page() -> str:
    try:
        with open(_PAGE, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return "<html><body>gst-profile live view</body></html>"


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="gst-profile", description="Live GStreamer pipeline profiler: where does the time go?")
    p.add_argument("--version", action="version", version=f"gst-profile {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
    sub.add_parser("check", help="preflight: what can this machine measure?")

    def common(sp):
        sp.add_argument("--duration", help="stop after e.g. 30s / 2m (default: until Ctrl-C or the pipeline ends)")
        sp.add_argument("--out", help="write session JSON here (default: ./gst-profile-<id>.json)")
        sp.add_argument("--no-ui", action="store_true", help="headless: capture and print the verdict, no live server")
        sp.add_argument("--port", type=int, default=8790, help="live view port (default 8790; 0 = pick a free port)")
        sp.add_argument("--host", default="0.0.0.0", help="live view bind address (default all interfaces; use 127.0.0.1 to lock down)")
        sp.add_argument("--hold", default="0", help="seconds to keep the live view up after capture ends (default 0 = exit when done; e.g. 300 to keep viewing)")
        sp.add_argument("--lite", action="store_true", help="latency tracer only (no stats): minimal overhead, no bytes/s")
        sp.add_argument("--tracers", help="override GST_TRACERS verbatim")
        sp.add_argument("--label", default="", help="session label (v2 A/B)")

    r = sub.add_parser("run", help="launch a gst-launch pipeline string under the profiler")
    r.add_argument("launch", help="pipeline description, quoted")
    common(r)
    w = sub.add_parser("wrap", help="run your own binary under the profiler: gst-profile wrap [flags] -- ./app args")
    w.add_argument("command", nargs=argparse.REMAINDER, help="-- your command and its arguments")
    common(w)
    a = sub.add_parser("analyze", help="build a session from an existing GST_DEBUG log or a session JSON, print the verdict")
    a.add_argument("path")
    a.add_argument("--dot", action="append", default=[], help="dot dump(s) to merge for topology/caps")
    a.add_argument("--out")
    a.add_argument("--serve", action="store_true", help="serve the recorded session for browsing")
    a.add_argument("--port", type=int, default=8790)
    a.add_argument("--host", default="0.0.0.0")
    rp = sub.add_parser("report", help="write a self-contained HTML report from a session JSON")
    rp.add_argument("path")
    rp.add_argument("-o", "--out", required=True, help="output .html path")
    return p


# ---- verdict helpers -------------------------------------------------------------------
def _verdict_of(session_dict):
    # rules.VERIFIED_RULES is populated by Plan 4; empty here means every diagnostic finding is info.
    a = analysis.build(session_dict)
    fs = rules.run_rules(a)
    return a, fs


def _has_high_or_medium(findings) -> bool:
    return any(f.severity in ("high", "medium") for f in findings)


def _print_verdict(session_dict) -> int:
    a, fs = _verdict_of(session_dict)
    print(verdict.render_text(a, fs))
    return EXIT_FINDINGS if _has_high_or_medium(fs) else EXIT_CLEAN


def _findings_payload(session_dict):
    a, fs = _verdict_of(session_dict)
    return verdict.to_dict(a, fs)


# ---- capture (headless or live) --------------------------------------------------------
def _capture(session, cmd, mode, args, caps=None) -> int:
    caps = caps or check()
    session.target = caps.to_target()
    session.graph.platform = caps.platform
    try:
        duration = _parse_duration(args.duration)
        hold = _parse_duration(args.hold) if getattr(args, "hold", None) else 0.0
    except ValueError:
        print("gst-profile: --duration/--hold must be a number like 30s, 2m, 500ms", file=sys.stderr)
        return EXIT_USAGE
    live = not args.no_ui
    lock = threading.Lock()
    broker = srv.Broker() if live else None
    server = None
    last_rows = [0]

    def on_line(line):
        with lock:
            session.ingest_line(line)

    def on_dot(text):
        with lock:
            changed = session.ingest_dot(text)
        if changed and broker:
            with lock:
                broker.publish("graph", session.graph.to_dict(), sticky=True)

    launcher = Launcher(cmd, on_line, on_dot, mode=mode, element_latency=caps.element_latency, lite=args.lite, tracers=args.tracers)
    tegra = TegrastatsSource()
    try:
        launcher.start()
    except OSError as e:
        launcher.cleanup()
        print(f"gst-profile: cannot start {cmd[0]}: {e}", file=sys.stderr)
        return EXIT_USAGE
    tegra.start()
    ps = ProcStat(launcher.proc.pid)
    stopping = {"flag": False}

    if live:
        try:
            server = srv.LiveServer(broker, lambda: _snapshot(session, lock), lambda req: _control(req, session, lock, stopping),
                                    _page(), host=args.host, port=args.port)
            server.start()
        except OSError as e:
            launcher.stop(); tegra.stop(); launcher.cleanup()
            print(f"gst-profile: cannot open the live view on {args.host}:{args.port} ({e}); try --port 0 or --no-ui", file=sys.stderr)
            return EXIT_USAGE
        broker.publish("status", {"state": "capturing", "port": server.port}, sticky=True)
        url_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
        print(f"gst-profile: live view  http://{url_host}:{server.port}   (Ctrl-C to stop)", file=sys.stderr)
    print(f"gst-profile: capturing ({mode})  pid={launcher.proc.pid}" + (f"  duration={duration}s" if duration else ""), file=sys.stderr)

    started = time.monotonic()
    t_start = time.time()
    handlers = []
    def on_stop_signal(_s, _f):
        stopping["flag"] = True
    is_main = threading.current_thread() is threading.main_thread()
    if is_main:                                        # signal handlers only work on the main thread
        for signame in ("SIGINT", "SIGTERM", "SIGHUP"):
            sig = getattr(signal, signame, None)
            if sig is not None:
                try:
                    handlers.append((sig, signal.signal(sig, on_stop_signal)))
                except (ValueError, OSError):
                    pass
    child_self_exited = False
    try:
        try:
            while launcher.running() and not stopping["flag"]:
                time.sleep(0.25)
                now = time.monotonic()
                with lock:
                    session.ingest_cpu(ps.sample(now))
                    if tegra.available:
                        session.ingest_tegrastats(tegra.latest())
                    d = session.to_dict()
                    nrows = len(d["series"]["t"])
                if broker and nrows > last_rows[0]:
                    last_rows[0] = nrows
                    broker.publish("tick", {"t": d["series"]["t"][-1], "rows": nrows,
                                            "latency_ms_p95": d["series"]["pipeline"]["latency_ms_p95"][-1]})
                    broker.publish("findings", _findings_payload(d), sticky=True)
                if duration and now - started >= duration:
                    break
            child_self_exited = not launcher.running() and not stopping["flag"]
            code = launcher.stop()
        finally:
            tegra.stop()
            launcher.cleanup()

        with lock:
            session.flush_pending()
            session.duration_s = round(time.time() - t_start, 3)     # wall-clock duration (Plan 1 F13)
            session.add_event("child-exit", f"exit code {code}")
            session.notes.append(f"lines read {launcher.lines_read}, dropped {launcher.dropped}, dot files dropped {launcher.dots_dropped}")
            d = session.to_dict()

        out = args.out or f"gst-profile-{session.id}.json"
        with open(out, "w") as fh:
            fh.write(json.dumps(d))
        print(f"gst-profile: session written to {out}", file=sys.stderr)

        a, fs = _verdict_of(d)
        print(verdict.render_text(a, fs))
        exit_findings = _has_high_or_medium(fs)

        if server:
            broker.publish("findings", verdict.to_dict(a, fs), sticky=True)
            broker.publish("status", {"state": "done"}, sticky=True)
            if hold and not stopping["flag"]:
                url_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
                print(f"gst-profile: capture done — live view held at http://{url_host}:{server.port} for {int(hold)}s (Ctrl-C to exit now)", file=sys.stderr)
                deadline = time.monotonic() + hold
                try:
                    while time.monotonic() < deadline and not stopping["flag"]:
                        time.sleep(0.2)
                except KeyboardInterrupt:
                    pass
    finally:
        if server:
            server.stop()                            # always tear down the HTTP server + restore signals
        for sig, old in handlers:
            signal.signal(sig, old)

    if child_self_exited and code not in (0, None):
        return EXIT_CHILD_FAILED
    return EXIT_FINDINGS if exit_findings else EXIT_CLEAN


def _snapshot(session, lock):
    with lock:
        return session.to_dict()


def _control(req, session, lock, stopping):
    if req.get("action") == "stop":
        stopping["flag"] = True
    elif req.get("action") == "mark":
        with lock:
            session.add_event("mark", str(req.get("text", "mark")))
    return {"ok": True}


# ---- commands --------------------------------------------------------------------------
def cmd_check(_args) -> int:
    print(render(check()))
    return EXIT_CLEAN


def cmd_run(args) -> int:
    caps = check()
    if not caps.gst_launch:
        print("gst-profile: gst-launch-1.0 not found; `run` needs it (use `wrap` for your own binary)", file=sys.stderr)
        return EXIT_USAGE
    try:
        parse_launch(args.launch, platform=caps.platform)      # validate syntax; graph comes from runtime dot dumps
    except LaunchParseError as e:
        print(f"gst-profile: cannot parse pipeline: {e}", file=sys.stderr)
        return EXIT_USAGE
    session = Session(mode="run", launch=args.launch, label=args.label)
    cmd = [caps.gst_launch, "-q"] + shlex.split(args.launch)
    return _capture(session, cmd, "run", args, caps=caps)


def cmd_wrap(args) -> int:
    cmd = list(args.command)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("gst-profile wrap: give the command after `--`", file=sys.stderr)
        return EXIT_USAGE
    session = Session(mode="wrap", command=cmd, label=args.label)
    return _capture(session, cmd, "wrap", args)


def _load_session_dict(path, dots=()):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rb") as fh:
        head = fh.read(64)
    if head.lstrip().startswith(b"{"):
        with opener(path, "rt") as fh:
            return json.load(fh)
    session = Session(mode="analyze")
    with opener(path, "rt", errors="replace") as fh:
        for line in fh:
            session.ingest_line(line)
    for dp in dots:
        with open(dp, encoding="utf-8", errors="replace") as fh:
            session.ingest_dot(fh.read())
    session.flush_pending()
    return session.to_dict()


def cmd_analyze(args) -> int:
    if not os.path.exists(args.path):
        print(f"gst-profile: {args.path} not found", file=sys.stderr)
        return EXIT_USAGE
    try:
        d = _load_session_dict(args.path, args.dot)
        _verdict_of(d)                                   # validate it is a usable session
    except (KeyError, ValueError, TypeError) as e:
        print(f"gst-profile: {args.path} is not a usable session ({e})", file=sys.stderr)
        return EXIT_USAGE
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(json.dumps(d))
        print(f"gst-profile: session written to {args.out}", file=sys.stderr)
    code = _print_verdict(d)
    if args.serve:
        broker = srv.Broker()
        broker.publish("graph", d["graph"], sticky=True)
        broker.publish("findings", _findings_payload(d), sticky=True)
        broker.publish("status", {"state": "done"}, sticky=True)
        server = srv.LiveServer(broker, lambda: d, lambda req: {"ok": True}, _page(), host=args.host, port=args.port)
        server.start()
        url_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
        print(f"gst-profile: serving {args.path} at http://{url_host}:{server.port} (Ctrl-C to exit)", file=sys.stderr)
        try:
            while True:
                time.sleep(0.3)
        except KeyboardInterrupt:
            pass
        server.stop()
    return code


def cmd_report(args) -> int:
    if not os.path.exists(args.path):
        print(f"gst-profile: {args.path} not found", file=sys.stderr)
        return EXIT_USAGE
    try:
        d = _load_session_dict(args.path)
        payload = _findings_payload(d)
    except (KeyError, ValueError, TypeError) as e:
        print(f"gst-profile: {args.path} is not a usable session ({e})", file=sys.stderr)
        return EXIT_USAGE
    meta = f"{d['session'].get('mode','?')} · {d['session'].get('duration_s',0)}s · {len(d['series']['t'])} windows"
    page = _page()
    def _embed(obj):
        return json.dumps(obj).replace("<", "\\u003c")   # so pipeline text containing </script> can't break out
    inject = ("<script>window.__VERDICT__=" + _embed(payload) + ";window.__META__=" + _embed(meta) + ";</script>")
    html = page.replace("<script>", inject + "\n<script>", 1)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"gst-profile: report written to {args.out}", file=sys.stderr)
    return EXIT_CLEAN


def main(argv: Optional[List[str]] = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except UsageError:
        return EXIT_USAGE
    return {"check": cmd_check, "run": cmd_run, "wrap": cmd_wrap,
            "analyze": cmd_analyze, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
