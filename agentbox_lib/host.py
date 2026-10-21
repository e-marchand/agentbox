"""Host commands: whitelisted programs a sandboxed agent may ask agentbox to run OUTSIDE the sandbox.

A broker process (unsandboxed, one per session) listens on a unix socket under
/private/tmp, which the sandbox can reach. The agent talks to it with
`agentbox-host`. Only the commands listed in the sandbox's `host_commands` can
be started, and their output goes to log files the agent can read.

Protocol: one JSON request line per connection, JSON reply lines.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import threading
import time

SOCK_NAME = "broker.sock"


def expand(path: str) -> str:
    # Not config.expand: the client runs inside the sandbox, where PyYAML (user site-packages) is hidden.
    return os.path.abspath(os.path.expanduser(path))


def session_dir(sid: str) -> str:
    # /private/tmp keeps the socket path short (sun_path is limited to 104 bytes).
    return f"/private/tmp/agentbox-{os.getuid()}-{sid}"


def normalize(commands: dict) -> dict:
    """Host command specs with defaults filled and paths expanded."""
    out = {}
    for name, spec in (commands or {}).items():
        exe = spec["cmd"][0]
        exe = expand(exe) if "/" in exe or exe.startswith("~") else (shutil.which(exe) or exe)
        cmd = [exe, *(expand(a) if a.startswith("~/") else a for a in spec["cmd"][1:])]
        out[name] = {
            "cmd": cmd,
            "cwd": expand(spec.get("cwd", os.path.dirname(exe))),
            "args": bool(spec.get("args", False)),
            "description": spec.get("description", ""),
        }
    return out


class Broker:
    def __init__(self, commands: dict, dirpath: str, watch_pid: int):
        self.commands = normalize(commands)
        self.dir = dirpath
        self.watch_pid = watch_pid
        self.jobs = {}
        self.lock = threading.Lock()

    # ------------------------------------------------------------ jobs
    def _job_view(self, name: str) -> dict:
        job = self.jobs[name]
        code = job["proc"].poll()
        return {"name": name, "args": job["args"], "log": job["log"], "started": job["started"],
                "running": code is None, "exit": code}

    def _start(self, name: str, args: list) -> dict:
        spec = self.commands.get(name)
        if spec is None:
            return {"error": f"unknown host command {name!r} (known: {', '.join(self.commands) or 'none'})"}
        if args and not spec["args"]:
            return {"error": f"host command {name!r} takes no arguments"}
        if not all(isinstance(a, str) and "\0" not in a for a in args):
            return {"error": "arguments must be strings"}
        with self.lock:
            if name in self.jobs and self.jobs[name]["proc"].poll() is None:
                return {"error": f"{name!r} is already running, use `agentbox-host wait {name}`"}
            log_path = os.path.join(self.dir, f"{name}.log")
            with open(log_path, "wb") as log:
                proc = subprocess.Popen([*spec["cmd"], *args], cwd=spec["cwd"], stdin=subprocess.DEVNULL,
                                        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            self.jobs[name] = {"proc": proc, "args": args, "log": log_path,
                               "started": time.strftime("%Y-%m-%d %H:%M:%S")}
            return {"started": name, "pid": proc.pid, "log": log_path}

    def _follow(self, name: str, send) -> None:
        job = self.jobs.get(name)
        if job is None:
            send({"error": f"{name!r} was never started in this session"})
            return
        with open(job["log"], "rb") as f:
            while True:
                chunk = f.read(65536)
                if chunk:
                    send({"out": chunk.decode("utf-8", "replace")})
                    continue
                if job["proc"].poll() is not None:
                    rest = f.read()
                    if rest:
                        send({"out": rest.decode("utf-8", "replace")})
                    send({"exit": job["proc"].returncode})
                    return
                time.sleep(0.2)

    def _kill(self, name: str) -> dict:
        job = self.jobs.get(name)
        if job is None or job["proc"].poll() is not None:
            return {"error": f"{name!r} is not running"}
        os.killpg(job["proc"].pid, signal.SIGTERM)
        return {"killed": name}

    # ------------------------------------------------------------ server
    def _handle(self, conn: socket.socket) -> None:
        f = conn.makefile("rwb")

        def send(obj):
            f.write((json.dumps(obj) + "\n").encode())
            f.flush()

        try:
            req = json.loads(f.readline() or b"{}")
            op, name, args = req.get("op"), req.get("name", ""), req.get("args", [])
            if op == "list":
                send({"commands": {n: {"description": s["description"], "args": s["args"]}
                                   for n, s in self.commands.items()}})
            elif op == "status":
                send({"jobs": [self._job_view(n) for n in self.jobs]})
            elif op == "start":
                send(self._start(name, args))
            elif op == "run":
                res = self._start(name, args)
                send(res)
                if "error" not in res:
                    self._follow(name, send)
            elif op == "wait":
                self._follow(name, send)
            elif op == "kill":
                send(self._kill(name))
            else:
                send({"error": f"unknown op {op!r}"})
        except (BrokenPipeError, ConnectionResetError):
            pass  # client went away (Ctrl-C, tool timeout): the job keeps running
        except ValueError as e:
            send({"error": f"bad request: {e}"})
        finally:
            conn.close()

    def _watchdog(self) -> None:
        """Exit with the agent: kill running jobs and remove the session dir."""
        while True:
            try:
                os.kill(self.watch_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(1)
        for job in self.jobs.values():
            if job["proc"].poll() is None:
                try:
                    os.killpg(job["proc"].pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        shutil.rmtree(self.dir, ignore_errors=True)
        os._exit(0)

    def serve(self) -> None:
        sock_path = os.path.join(self.dir, SOCK_NAME)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        os.chmod(sock_path, 0o600)
        srv.listen(8)
        threading.Thread(target=self._watchdog, daemon=True).start()
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()


# ---------------------------------------------------------------- client

def request(sock_path: str, req: dict, retries: float = 5.0):
    """Send one request, yield reply objects. Retries while the broker is starting."""
    deadline = time.time() + retries
    while True:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(sock_path)
            break
        except (FileNotFoundError, ConnectionRefusedError):
            s.close()
            if time.time() > deadline:
                raise
            time.sleep(0.2)
    with s:
        f = s.makefile("rwb")
        f.write((json.dumps(req) + "\n").encode())
        f.flush()
        for line in f:
            yield json.loads(line)
