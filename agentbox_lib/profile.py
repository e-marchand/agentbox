"""Seatbelt (SBPL) profile generation.

Strategy: allow everything, hide /Users and /Volumes, forbid writes outside
temp dirs, then re-allow the configured paths. In SBPL the last matching rule
wins, so the order of the sections below matters.
"""
from __future__ import annotations

import os

from .config import ConfigError, expand

OPS = {"ro": "file-read*", "rw": "file-read* file-write*"}
_REGEX_SPECIAL = set(".^$*+?()[]{}|\\")


def _str(path: str) -> str:
    if any(c in path for c in '"\\\n'):
        raise ConfigError(f"unsupported character in path: {path!r}")
    return f'"{path}"'


def _re_escape(text: str) -> str:
    return "".join("\\" + c if c in _REGEX_SPECIAL else c for c in text)


def _variants(path: str) -> list:
    """The path as written (parent resolved) and fully resolved; Seatbelt matches resolved vnode paths."""
    p = expand(path)
    parent_resolved = os.path.join(os.path.realpath(os.path.dirname(p)), os.path.basename(p))
    out = []
    for v in (parent_resolved, os.path.realpath(p)):
        if v not in out:
            out.append(v)
    return out


def filters(path: str, mode: str) -> list:
    """SBPL filters for one configured path.

    A directory becomes a subpath. A file (or a missing path) becomes a literal;
    in rw mode, sibling temp names (`f.tmp.123`, `f~`, `.f.swp`) are allowed too
    so atomic write-then-rename keeps working.
    """
    out = []
    for p in _variants(path):
        if os.path.isdir(p):
            out.append(f"(subpath {_str(p)})")
            continue
        out.append(f"(literal {_str(p)})")
        if mode == "rw":
            d, name = os.path.split(p)
            d, name = _re_escape(d), _re_escape(name)
            out.append(f'(regex #"^{d}/\\.?{name}[.~][^/]*$")')
    return out


def build(box: dict, agent: dict, extra_ro: list = (), protect: list = ()) -> str:
    lines = [
        "(version 1)",
        "(allow default)",
        ";; hide every home directory and external volume",
        '(deny file-read* file-write* (subpath "/Users") (subpath "/Volumes"))',
        ";; no writes anywhere ...",
        '(deny file-write* (subpath "/"))',
        ";; ... except temp dirs and devices",
        '(allow file-write* (subpath "/private/tmp") (subpath "/private/var/folders") (subpath "/dev"))',
        ";; stat() of parents is needed for path resolution (no listing, no content)",
        '(allow file-read-metadata (subpath "/Users"))',
    ]

    seen = set()

    def emit(comment: str, entries) -> None:
        rules = []
        for e in entries:
            mode = e.get("mode", "rw")
            f = " ".join(filters(e["path"], mode))
            if mode == "deny":
                rule = f"(deny file-read* file-write* {f})"
            elif mode == "ro":
                # Also deny writes, so a ro path nested in an rw folder stays read-only.
                rule = f"(allow file-read* {f}) (deny file-write* {f})"
            else:
                rule = f"(allow {OPS[mode]} {f})"
            if rule not in seen:
                seen.add(rule)
                rules.append(f"{rule}  ; {e['path']}")
        if rules:
            lines.append(f";; {comment}")
            lines.extend(rules)

    emit("agent binary", ({"path": p, "mode": "ro"} for p in extra_ro))
    emit("agent state", agent.get("paths", []))
    emit("sandbox paths", (e for e in box["paths"] if e.get("mode", "rw") != "deny"))
    if protect:
        lines.append(";; agent config read by unsandboxed runs: never writable")
        for p in protect:
            lines.append(f"(deny file-write* {' '.join(filters(p, 'ro'))})  ; {p}")
    emit("explicit denies", (e for e in box["paths"] if e.get("mode") == "deny"))
    return "\n".join(lines) + "\n"
