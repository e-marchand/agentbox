#!/bin/sh
# Install agentbox: link the CLI into a bin dir on PATH and, optionally, the Claude Code skill.
#
# usage: ./install.sh [--skill] [--bin-dir DIR] [--uninstall]
#   --skill       also link skills/agentbox into ~/.claude/skills (or install the plugin instead,
#                 see README)
#   --bin-dir     where to put the `agentbox` link (default: ~/.local/bin)
#   --uninstall   remove the links created by this script
set -eu

ROOT="$(cd "$(dirname "$0")" && pwd -P)"
BIN_DIR="$HOME/.local/bin"
SKILL_DIR="$HOME/.claude/skills"
SKILL=0
UNINSTALL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --skill) SKILL=1 ;;
    --bin-dir) BIN_DIR="$2"; shift ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "install.sh: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done

if [ -t 1 ]; then G='\033[32m' Y='\033[33m' R='\033[31m' N='\033[0m'; else G='' Y='' R='' N=''; fi
ok() { printf "  ${G}✓${N} %s\n" "$1"; }
warn() { printf "  ${Y}!${N} %s\n" "$1"; }
fail() { printf "  ${R}✗${N} %s\n" "$1" >&2; exit 1; }

unlink_if_ours() {
  if [ -L "$1" ] && [ "$(readlink "$1")" = "$2" ]; then
    rm "$1"
    ok "removed $1"
  fi
}

if [ "$UNINSTALL" = 1 ]; then
  unlink_if_ours "$BIN_DIR/agentbox" "$ROOT/agentbox"
  unlink_if_ours "$SKILL_DIR/agentbox" "$ROOT/skills/agentbox"
  echo "Config (~/.config/agentbox) and state (~/.local/state/agentbox) were left in place."
  exit 0
fi

echo "Checking requirements"
[ "$(uname -s)" = "Darwin" ] || fail "agentbox needs macOS (it uses sandbox-exec / Seatbelt)"
[ -x /usr/bin/sandbox-exec ] || fail "/usr/bin/sandbox-exec not found"
ok "macOS with sandbox-exec"

# The CLI runs with the first python3 on PATH (#!/usr/bin/env python3).
PY="$(command -v python3 || true)"
[ -n "$PY" ] || fail "python3 not found (install the Xcode command line tools: xcode-select --install)"
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 9))' \
  || fail "python3 >= 3.9 required, found $("$PY" --version 2>&1)"
ok "$("$PY" --version 2>&1) ($PY)"

if "$PY" -c 'import yaml' 2>/dev/null; then
  ok "PyYAML $("$PY" -c 'import yaml; print(yaml.__version__)')"
else
  warn "PyYAML missing, installing it for this user: $PY -m pip install --user pyyaml"
  "$PY" -m pip install --user --quiet pyyaml || fail "could not install PyYAML; run: $PY -m pip install --user pyyaml"
  "$PY" -c 'import yaml' || fail "PyYAML still not importable by $PY"
  ok "PyYAML installed"
fi

echo "Installing"
chmod +x "$ROOT/agentbox" "$ROOT/bin/agentbox-host"
mkdir -p "$BIN_DIR"
if [ -e "$BIN_DIR/agentbox" ] && [ ! -L "$BIN_DIR/agentbox" ]; then
  fail "$BIN_DIR/agentbox exists and is not a link, not touching it"
fi
ln -sfn "$ROOT/agentbox" "$BIN_DIR/agentbox"
ok "$BIN_DIR/agentbox -> $ROOT/agentbox"

if [ "$SKILL" = 1 ]; then
  mkdir -p "$SKILL_DIR"
  if [ -e "$SKILL_DIR/agentbox" ] && [ ! -L "$SKILL_DIR/agentbox" ]; then
    fail "$SKILL_DIR/agentbox exists and is not a link, not touching it"
  fi
  ln -sfn "$ROOT/skills/agentbox" "$SKILL_DIR/agentbox"
  ok "Claude Code skill: $SKILL_DIR/agentbox -> $ROOT/skills/agentbox"
fi

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) warn "$BIN_DIR is not on your PATH; add to ~/.zshrc: export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac

echo
echo "Done. Next:"
echo "  cd ~/git/myproject && agentbox init myproject && agentbox run myproject"
