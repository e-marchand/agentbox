"""Running sandboxed processes and tracking them with session files."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

STATE_DIR = Path(os.environ.get("AGENTBOX_STATE", "~/.local/state/agentbox")).expanduser()
SESSIONS_DIR = STATE_DIR / "sessions"
LOGS_DIR = STATE_DIR / "logs"


def _alive(info: dict) -> bool:
    try:
        return os.getpgid(info["pid"]) == info["pgid"]
    except (ProcessLookupError, PermissionError):
        return False


def _write(info: dict) -> Path:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = SESSIONS_DIR / f"{info['id']}.json"
    path.write_text(json.dumps(info, indent=2))
    return path


def list_sessions() -> list:
    """Live sessions; files of dead ones are pruned on the way."""
    out = []
    for f in sorted(SESSIONS_DIR.glob("*.json")) if SESSIONS_DIR.exists() else []:
        try:
            info = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if _alive(info):
            out.append(info)
        else:
            f.unlink(missing_ok=True)
    return out


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def _info(sid: str, box: str, agent: str, cmd: list, cwd: str, pid: int) -> dict:
    return {
        "id": sid,
        "box": box,
        "agent": agent,
        "pid": pid,
        "pgid": pid,
        "cwd": cwd,
        "cmd": cmd,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def run_foreground(sid: str, box: str, agent: str, argv: list, cwd: str, env: dict, display_cmd: list,
                   on_start=None) -> int:
    """Run in its own process group that owns the terminal, so `agentbox stop` can kill the whole tree."""
    tty = sys.stdin.fileno() if sys.stdin.isatty() else None

    def child_setup():
        os.setpgid(0, 0)
        if tty is not None:
            signal.signal(signal.SIGTTOU, signal.SIG_IGN)
            os.tcsetpgrp(tty, os.getpgrp())
            signal.signal(signal.SIGTTOU, signal.SIG_DFL)

    proc = subprocess.Popen(argv, cwd=cwd, env=env, preexec_fn=child_setup)
    info = _info(sid, box, agent, display_cmd, cwd, proc.pid)
    session_file = _write(info)
    if on_start:
        on_start(proc.pid)
    old_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
    old_ttou = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
    try:
        while True:
            _, status = os.waitpid(proc.pid, os.WUNTRACED)
            if os.WIFSTOPPED(status):
                # Ctrl-Z: there is no shell job control around us, resume the agent.
                if tty is not None:
                    os.tcsetpgrp(tty, proc.pid)
                os.killpg(proc.pid, signal.SIGCONT)
                continue
            code = os.waitstatus_to_exitcode(status)
            proc.returncode = code
            return code if code >= 0 else 128 - code
    finally:
        if tty is not None:
            os.tcsetpgrp(tty, os.getpgrp())
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTTOU, old_ttou)
        session_file.unlink(missing_ok=True)


def run_detached(sid: str, box: str, agent: str, argv: list, cwd: str, env: dict, display_cmd: list,
                 on_start=None) -> dict:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"{box}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    info = _info(sid, box, agent, display_cmd, cwd, proc.pid)
    info["log"] = str(log_path)
    _write(info)
    if on_start:
        on_start(proc.pid)
    return info


def stop(info: dict, timeout: float = 5.0) -> None:
    try:
        os.killpg(info["pgid"], signal.SIGTERM)
        deadline = time.time() + timeout
        while time.time() < deadline and _alive(info):
            time.sleep(0.1)
        if _alive(info):
            os.killpg(info["pgid"], signal.SIGKILL)
    except ProcessLookupError:
        pass
    (SESSIONS_DIR / f"{info['id']}.json").unlink(missing_ok=True)
