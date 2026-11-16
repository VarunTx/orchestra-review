# Orchestra Review

![orchestra-review on the author's own sessions, run with --public so paths and names are scrubbed](docs/demo.gif)

**Your coding agent keeps making the same mistakes, because every session starts with no memory of your machine.** It calls a program that isn't installed, imports a module from the wrong Python, or trips over the same shell quirk, week after week. Orchestra Review reads the session logs that Claude Code and OpenCode already keep on your computer. It finds the mistakes that recur across sessions, gives you one instruction line to fix each, and then measures whether that line actually stopped the mistake. Nothing leaves your machine.

```sh
pipx install "git+https://github.com/VarunTx/orchestra-review"   # PyPI release coming
orchestra-review
```

## What it found

These are the author's own logs as of 2026-11-16: 53 sessions (49 Claude Code, 4 OpenCode), 5,634 tool calls and 130 failures.

- **39 of the 130 failures (30%) repeated a mistake from an earlier session.**
- The most common ones were all about the machine, not the code:
  - PDF reads failing because `pdftoppm` isn't installed (8 sessions);
  - zsh treating `echo ====` as a command (7 sessions);
  - `No module named 'fitz'` (5 sessions);
  - zsh erroring on a glob that matches nothing (5 sessions).

Six rule-based lines went into `~/.claude/CLAUDE.md` on 2026-11-13. Each line is judged only on sessions that **tried** the action it covers, such as globbing or reading a PDF:

| Fix | Sessions that hit it / tried it, before | After | Verdict |
| --- | --- | --- | --- |
| zsh: a glob that matches nothing is an error | 5 / 15 | 0 / 7 | stopped |
| zsh: quote words starting with `=` | 5 / 14 | 2 / 4 | too early, still happening |
| `pdftoppm` missing for PDF reads | 8 / 9 | 0 / 0 | too early |
| `fitz`, `pypdf`, `docx` not importable | 5 / 10, 2 / 10, 2 / 4 | 0 / 0 | too early |

"Too early" means fewer than five sessions have tried the action since the line was added. One person's sessions are a small sample, and the table will be updated as more arrive.

## Usage

```sh
orchestra-review                                  # report for Claude Code, plus this directory's OpenCode sessions
orchestra-review --since 30d --opencode-project ~/code/my-app
orchestra-review apply 6eab0c6e --to ~/.claude/CLAUDE.md   # add a suggested line, with a timed marker
orchestra-review                                  # later runs show each line's before-and-after
orchestra-review --public                         # scrub paths, file names, URLs and emails, for screenshots
orchestra-review --json                           # everything, as JSON
orchestra-review share > mine.json                # counts and scrubbed causes only, with a preview on stderr
```

## How it decides

- **A recurring mistake** is a failure in two or more sessions that shares the same last error line, ignoring numbers and ids. Calls refused by a permission rule or interrupted by you are counted as blocked, not failed.
- **Fix lines** come from rules for known causes: a missing program, a Python module that can't be imported, and zsh `=` and glob quirks. For other causes, a local model you run yourself through Ollama (`--model`) can draft a line. A draft is kept only if it names the cause and contains no URL or command that downloads or deletes anything, because log text is untrusted and the line ends up in a file your agent obeys. `apply` writes drafted lines only with `--include-drafted`.
- **Measurement** counts only sessions that tried the relevant action, so a change of task can't look like a cure. Each line's marker carries the exact UTC time it was added.
- **Privacy:** everything is read locally, and nothing is sent anywhere unless you point `--model` at a model server. Evidence is redacted for credential-shaped strings, and `--public` and `share` also drop paths, file names, project names and commands.

## Scope

- **Reads:** Claude Code (`~/.claude/projects`, including subagents) and OpenCode (through `opencode session export`). Codex CLI is next.
- **Runs on:** macOS and Linux with Python 3.11 or later, with no dependencies. Windows is untested.
- **Maintained:** best-effort. Issues are welcome; there are no promised response times.
- **Planned:**
  - add rule-based lines automatically once a mistake has hit three sessions, with `undo`;
  - re-check each line's fact and retire lines that no longer hold;
  - a Claude Code hook that blocks a known-bad command before it runs.

Design notes and their history: [`docs/design.md`](docs/design.md). MIT licensed.
