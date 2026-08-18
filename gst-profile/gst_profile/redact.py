"""Redact credentials and endpoints from a session dict before it is shared:
`user:pass@` in URLs, values of location/uri-like properties, and token-looking
strings. Returns a deep copy; the live session is never mutated. Design: report
and Save-session redact by default; --no-redact opts out."""
import copy
import re

# properties whose VALUES are sensitive wherever they appear (element props, launch string)
SENSITIVE_PROPS = ("location", "uri", "url", "address", "host", "auth-token", "user-id",
                   "user-pw", "passwd", "password", "proxy", "extra-headers")
_CRED_URL = re.compile(r"([a-z][a-z0-9+.-]*://)([^/@\s\"']+)@", re.IGNORECASE)
_TOKEN = re.compile(r"\b(?=[A-Za-z0-9+/_-]*[0-9])(?=[A-Za-z0-9+/_-]*[A-Za-z])[A-Za-z0-9+/_-]{24,}\b")
_PROP_IN_TEXT = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in SENSITIVE_PROPS) + r")\s*=\s*(\"[^\"]*\"|'[^']*'|\S+)",
    re.IGNORECASE)
REDACTED = "[redacted]"


def redact_text(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text
    out = _CRED_URL.sub(lambda m: m.group(1) + REDACTED + "@", text)
    out = _PROP_IN_TEXT.sub(lambda m: f"{m.group(1)}={REDACTED}", out)
    out = _TOKEN.sub(REDACTED, out)
    return out


def redact_session(session: dict) -> dict:
    d = copy.deepcopy(session)
    sess = d.get("session") or {}
    if sess.get("launch"):
        sess["launch"] = redact_text(sess["launch"])
    if sess.get("command"):
        sess["command"] = [redact_text(str(c)) for c in sess["command"]]
    sess["notes"] = [redact_text(str(n)) for n in sess.get("notes", [])]
    for el in (d.get("graph") or {}).get("elements", []):
        props = el.get("props") or {}
        for k in list(props):
            if k.lower() in SENSITIVE_PROPS:
                props[k] = REDACTED
            else:
                props[k] = redact_text(str(props[k]))
    for ev in d.get("events", []):
        ev["text"] = redact_text(str(ev.get("text", "")))
    for f in d.get("findings", []):
        for key in ("why", "fix_text", "title"):
            if f.get(key):
                f[key] = redact_text(str(f[key]))
    return d
