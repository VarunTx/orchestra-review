# Changelog

## 0.2.0 — 2026-11-16

- `sync`: adds a rule-based line once a mistake has hit 3 sessions. A mistake seen in one project goes into that project's existing instruction file, otherwise into the agent's global file. `sync` never creates files inside a project.
- Lines are retired when their fact stops being true, for example after the missing program is installed. Each fact is re-checked live.
- `undo <id>`: removes a line. Neither an undone line nor a line you delete by hand is ever added back automatically.
- `hook install`/`uninstall`: a Claude Code PreToolUse hook blocks calls that would repeat a known mistake, after re-checking its fact. A SessionEnd hook runs `sync`. Both hooks fail open.
- Codex CLI reader (`~/.codex/sessions`), covering both `function_call` shells and `exec` scripts.
- Nine rules mined from 67,074 public OpenHands runs: file-viewing ranges, `find -exec \;` piping, old-Python f-strings and `capture_output`, `setup.py test`, `grep` on a directory, and editor misuse. See `research/`.
- Failing test runs, bare exit codes and bare paths are no longer treated as mistakes.
- `apply` now records what it wrote, so `sync` and the hook know about it.

## 0.1.0 — 2026-11-15

- First standalone release, moved from the `review/` folder of VarunTx/orchestra-ai with its history.
- Finds mistakes that recur across Claude Code and OpenCode sessions, suggests a line per mistake, and has `apply` with timed markers and a before-and-after measurement that counts only sessions that tried the action.
- `--public` scrubbing, `share`/`combine`, and an optional local-model drafter with grounding and safety checks.
