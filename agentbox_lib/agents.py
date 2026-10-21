"""Built-in agent definitions: the command to run and the state paths it needs."""
from __future__ import annotations

import json
import shutil

from .config import ConfigError

# Claude Code's own Bash sandbox also uses sandbox-exec, which cannot nest:
# turn it off, we are already the sandbox.
_CLAUDE_SETTINGS = json.dumps({"sandbox": {"enabled": False}})

DEFAULT_AGENTS = {
    "claude": {
        "cmd": ["claude", "--settings", _CLAUDE_SETTINGS],
        "env": {"DISABLE_AUTOUPDATER": "1"},
        "paths": [
            {"path": "~/.claude", "mode": "rw"},
            {"path": "~/.claude.json", "mode": "rw"},
            {"path": "~/.local/share/claude", "mode": "ro"},
            {"path": "~/.local/state/claude", "mode": "rw"},
            {"path": "~/.cache/claude", "mode": "rw"},
            {"path": "~/.local/bin/claude", "mode": "ro"},
            {"path": "~/Library/Keychains", "mode": "ro"},
        ],
    },
    "copilot": {
        "cmd": ["copilot"],
        "env": {},
        "paths": [
            {"path": "~/.copilot", "mode": "rw"},
            {"path": "~/Library/Caches/copilot", "mode": "rw"},
            {"path": "~/.config/gh", "mode": "ro"},
            {"path": "~/Library/Keychains", "mode": "ro"},
        ],
    },
}

# Read-only paths given to every agent: git aborts when ~/.gitconfig exists but
# cannot be read (EPERM is fatal for git, unlike ENOENT).
COMMON_PATHS = [
    {"path": "~/.gitconfig", "mode": "ro"},
    {"path": "~/.config/git", "mode": "ro"},
]

# Files an agent re-reads when it later runs OUTSIDE the sandbox (hooks, MCP
# servers, settings...). Writing them would be a sandbox escape, so writes are
# denied even inside an allowed rw directory. Disable with `protect: false`.
PROTECTED = [
    "~/.claude/settings.json",
    "~/.claude/settings.local.json",
    "~/.claude/CLAUDE.md",
    "~/.claude/hooks",
    "~/.claude/agents",
    "~/.claude/commands",
    "~/.claude/skills",
    "~/.claude/plugins",
    "~/.claude/output-styles",
    "~/.copilot/mcp-config.json",
    "~/.copilot/agents",
    "~/.copilot/skills",
    "~/.copilot/hooks",
]


def get_agent(cfg: dict, name: str) -> dict:
    """Built-in definition merged with the optional `agents:` override from the YAML."""
    override = cfg.get("agents", {}).get(name, {})
    base = DEFAULT_AGENTS.get(name)
    if base is None and not override:
        known = ", ".join(sorted(set(DEFAULT_AGENTS) | set(cfg.get("agents", {}))))
        raise ConfigError(f"unknown agent {name!r} (known: {known})")
    agent = {"cmd": [], "env": {}, "paths": [], **(base or {})}
    agent.update(override)
    agent["paths"] = COMMON_PATHS + agent["paths"]
    if not agent["cmd"]:
        raise ConfigError(f"agent {name!r} has no 'cmd'")
    return agent


def resolve_cmd(cmd: list, required: bool = True) -> list:
    exe = shutil.which(cmd[0])
    if exe is None:
        if not required:
            return list(cmd)
        raise ConfigError(f"agent command not found in PATH: {cmd[0]}")
    return [exe, *cmd[1:]]
