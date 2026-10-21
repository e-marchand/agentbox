---
name: agentbox
description: Run AI coding agents (Claude Code, GitHub Copilot CLI, or any command) in a macOS Seatbelt sandbox that only sees an allowlist of folders and single files, using the `agentbox` CLI. Use this skill when the user wants to sandbox or confine an agent, create or edit an agentbox sandbox (paths ro/rw/deny, host commands, agent arguments), launch/stop/list sandboxed sessions, debug "Operation not permitted" errors from a sandboxed tool, or when you are yourself running inside an agentbox session (the AGENTBOX environment variable is set) and need to build, run a whitelisted host command with `agentbox-host`, or understand why a path is not accessible.
---

# agentbox

`agentbox` launches an agent under `sandbox-exec` (macOS Seatbelt) with a generated profile:
everything under `/Users` and `/Volumes` is hidden, writes are denied everywhere except temp
dirs, then the configured paths are re-allowed. Child processes (git, npm, compilers...) inherit
the sandbox. No VM, no daemon: Python 3.9+ and PyYAML.

Config: `~/.config/agentbox/config.yaml` (override with `AGENTBOX_CONFIG`).
Sessions and logs: `~/.local/state/agentbox` (override with `AGENTBOX_STATE`).

## First, find out where you are

- `AGENTBOX` is set → you are **inside** a sandbox named `$AGENTBOX`. You cannot change its
  rules from inside; read "Working inside a sandbox" below.
- Otherwise you are on the host and can manage sandboxes with the CLI. Check it is installed
  with `command -v agentbox` (if not: clone https://github.com/e-marchand/agentbox and run
  `./install.sh`).

## Managing sandboxes (host side)

```sh
agentbox init <box> [--workdir DIR] [--agent claude|copilot]   # workdir (default: cwd) is added rw
agentbox add <box> <path>... [--rw|--ro|--deny]                 # rw is the default
agentbox rm <box> <path>...
agentbox ls [box]                                               # paths, kind (dir/file/missing), host commands
agentbox edit                                                   # $EDITOR, validated before saving
agentbox drop <box>                                             # delete the definition, files untouched
agentbox profile <box>                                          # print the generated Seatbelt profile
```

Running:

```sh
agentbox run <box>                          # interactive agent (default agent of the box)
agentbox run <box> --agent copilot          # another agent
agentbox run <box> -- -p "fix the tests"    # everything after -- goes to the agent
agentbox run <box> -d -- -p "..."           # detached, output in ~/.local/state/agentbox/logs
agentbox shell <box>                        # sandboxed zsh with the same rules, to test by hand
agentbox ps                                 # live sessions
agentbox stop <box|session-id|pid|--all>    # SIGTERM then SIGKILL on the whole process group
```

### Config format

```yaml
sandboxes:
  myproj:
    agent: claude
    workdir: ~/git/myproj
    paths:
      - {path: ~/git/myproj, mode: rw}             # folder
      - {path: ~/git/lib, mode: ro}
      - {path: ~/notes/todo.md, mode: rw}          # a single file (siblings stay hidden)
      - {path: ~/git/myproj/.git/hooks, mode: ro}  # nested: later entries win
      - {path: ~/git/myproj/.env, mode: deny}      # hidden even inside an allowed folder
    env: {FOO: bar}
    agent_args:                                    # extra args, per agent name
      claude: [--add-dir, ~/git/lib]
    host_commands:                                 # run OUTSIDE the sandbox on request
      build:
        cmd: [~/bin/build.sh]
        args: true                                 # allow the agent to pass arguments
        description: "build the project"
    # protect: false                               # see "Protections"
agents:                                            # optional: override or add agents
  claude: {cmd: [claude, --settings, '{"sandbox":{"enabled":false}}']}
  mytool: {cmd: [mytool], paths: [{path: ~/.mytool, mode: rw}]}
```

Rules to apply when editing a config for the user:

- **Order matters**: in Seatbelt the last matching rule wins. Put a broad `rw` folder first and
  narrower `ro`/`deny` entries after it.
- **Single files**: a `rw` file also allows its temp siblings (`f.tmp.123`, `f~`, `.f.swp`) so
  atomic write-then-rename works; creating any other file next to it is denied.
- **Git repos given rw**: add `.git/hooks` and `.git/config` as `ro` (not `deny`: git must read
  its config). Otherwise the agent could plant code that runs when the user uses git outside.
- **Claude Code's own permissions** still apply inside: it only allows its cwd. Pass the other
  allowed folders with `agent_args: {claude: [--add-dir, <dir>, ...]}`, or
  `--dangerously-skip-permissions` if the user trusts the sandbox.
- **Host commands** must not be writable from the sandbox: agentbox refuses to start otherwise.
  Keep their scripts in a `ro` path or outside the allowlist.
- Prefer editing the YAML with an editor tool over `agentbox add/rm`, which rewrite the file
  and drop comments.

### Built-in defaults

- Every agent can read `~/.gitconfig` and `~/.config/git` (git aborts on EPERM there).
- `claude`: `~/.claude` and `~/.claude.json` rw, its install dirs ro, `~/Library/Keychains` ro,
  runs with Claude's internal sandbox disabled (Seatbelt cannot nest) and auto-update off.
- `copilot`: `~/.copilot`, `~/Library/Caches/copilot` rw, `~/.config/gh` ro.
- Network is open. Environment variables of the launching terminal are inherited.

### Protections

Writes are always denied to agent config that an *unsandboxed* run would later execute:
`~/.claude/settings*.json`, `~/.claude/CLAUDE.md`, `~/.claude/{hooks,agents,commands,skills,plugins,output-styles}`,
`~/.copilot/{mcp-config.json,agents,skills,hooks}`. `protect: false` on a sandbox lifts this.

## Debugging "Operation not permitted"

1. `agentbox ls <box>`: is the path listed, with the right mode, and does it exist (`missing`
   paths are treated as files)?
2. `agentbox profile <box> | grep <path>`: check the rule and its position (a later rule wins).
3. Watch denials live while reproducing in `agentbox shell <box>`:
   `/usr/bin/log stream --style compact --predicate 'sender == "Sandbox"'`
   (use the full path: in zsh, `log` is a builtin). Add only what the tool really needs.
   Denied *listings* of ancestors (`file-read-data /Users/<me>`) are normal and usually harmless.
4. Known by design: setuid binaries (`ps`, `sudo`, `top`) cannot run; `sandbox-exec` cannot be
   nested; user site-packages (`~/Library/Python`) are hidden.

## Working inside a sandbox

You only see what the sandbox allows; an EPERM on a path means it is outside the allowlist,
not that it is missing. Do not try to work around the sandbox; tell the user which path you
need and in which mode, so they can `agentbox add` it.

When the sandbox declares host commands, `agentbox-host` is on your `PATH`:

```sh
agentbox-host list                    # what you may run outside the sandbox
agentbox-host run <name> [args...]    # run, stream output; exit code is the command's
agentbox-host start <name> [args...]  # background (long builds), prints the log path
agentbox-host wait <name>             # re-attach / stream until it ends
agentbox-host status                  # running / finished, with log paths (readable from inside)
agentbox-host kill <name>
```

For anything longer than your tool timeout, use `start` then `wait`: interrupting the client
never kills the command, and `wait` re-attaches.
