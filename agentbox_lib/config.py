"""Loading, validating and saving ~/.config/agentbox/config.yaml."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

CONFIG_PATH = Path(os.environ.get("AGENTBOX_CONFIG", "~/.config/agentbox/config.yaml")).expanduser()
MODES = ("ro", "rw", "deny")
HOME = os.path.realpath(os.path.expanduser("~"))


class ConfigError(Exception):
    pass


def expand(path: str) -> str:
    """Absolute, user-expanded path (symlinks are NOT resolved here)."""
    return os.path.abspath(os.path.expanduser(path))


def abbrev(path: str) -> str:
    """Absolute path written with ~ when it lives under $HOME, for readable YAML."""
    path = expand(path)
    home = os.path.expanduser("~")
    if path == home or path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


def load() -> dict:
    if not CONFIG_PATH.exists():
        return {"sandboxes": {}}
    with CONFIG_PATH.open() as f:
        cfg = yaml.safe_load(f) or {}
    validate(cfg)
    return cfg


def save(cfg: dict) -> None:
    validate(cfg)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".yaml.tmp")
    with tmp.open("w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, default_flow_style=None, allow_unicode=True)
    tmp.replace(CONFIG_PATH)


def _check_path_list(where: str, paths) -> None:
    if not isinstance(paths, list):
        raise ConfigError(f"{where}: 'paths' must be a list")
    for i, entry in enumerate(paths):
        if not isinstance(entry, dict) or "path" not in entry:
            raise ConfigError(f"{where}: paths[{i}] must be a mapping with a 'path' key")
        mode = entry.get("mode", "rw")
        if mode not in MODES:
            raise ConfigError(f"{where}: paths[{i}] mode must be one of {MODES}, got {mode!r}")
        if any(c in str(entry["path"]) for c in '"\\\n'):
            raise ConfigError(f"{where}: paths[{i}] contains an unsupported character (quote, backslash or newline)")


def validate(cfg: dict) -> None:
    if not isinstance(cfg, dict):
        raise ConfigError("top level must be a mapping")
    boxes = cfg.setdefault("sandboxes", {})
    if not isinstance(boxes, dict):
        raise ConfigError("'sandboxes' must be a mapping")
    for name, box in boxes.items():
        if not isinstance(box, dict):
            raise ConfigError(f"sandbox {name!r} must be a mapping")
        _check_path_list(f"sandbox {name!r}", box.setdefault("paths", []))
        if not isinstance(box.get("env", {}), dict):
            raise ConfigError(f"sandbox {name!r}: 'env' must be a mapping")
        agent_args = box.get("agent_args", {})
        if not (isinstance(agent_args, dict) and all(isinstance(v, list) for v in agent_args.values())):
            raise ConfigError(f"sandbox {name!r}: 'agent_args' must map agent names to argument lists")
        hosts = box.get("host_commands", {})
        if not isinstance(hosts, dict):
            raise ConfigError(f"sandbox {name!r}: 'host_commands' must be a mapping")
        for hname, spec in hosts.items():
            if not (isinstance(spec, dict) and isinstance(spec.get("cmd"), list) and spec["cmd"]):
                raise ConfigError(f"sandbox {name!r}: host_commands.{hname} needs a non-empty 'cmd' list")
    agents = cfg.get("agents", {})
    if not isinstance(agents, dict):
        raise ConfigError("'agents' must be a mapping")
    for name, agent in agents.items():
        if not isinstance(agent, dict):
            raise ConfigError(f"agent {name!r} must be a mapping")
        if "cmd" in agent and not (isinstance(agent["cmd"], list) and agent["cmd"]):
            raise ConfigError(f"agent {name!r}: 'cmd' must be a non-empty list")
        if "paths" in agent:
            _check_path_list(f"agent {name!r}", agent["paths"])


def get_box(cfg: dict, name: str) -> dict:
    try:
        return cfg["sandboxes"][name]
    except KeyError:
        known = ", ".join(cfg["sandboxes"]) or "none"
        raise ConfigError(f"unknown sandbox {name!r} (known: {known})") from None
