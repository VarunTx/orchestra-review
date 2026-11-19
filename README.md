# Orchestra Review

![orchestra-review on the author's own sessions, run with --public so paths and names are scrubbed](docs/demo.gif)

**Your coding agent keeps making the same mistakes, because every session starts with no memory of your machine or its tools.** It calls a program that isn't installed, imports a module from the wrong Python, or trips over the same shell quirk, week after week.

**Try it in your browser: [review.varuntx.us](https://review.varuntx.us).** Drop your `.claude` or `.codex` folder; the analysis runs in the page and nothing is uploaded.

Orchestra Review reads the session logs that Claude Code, Codex CLI and OpenCode already keep on your computer. It finds the mistakes that recur across sessions and fixes each with one instruction line. It can also block a known mistake before it runs, and it measures whether a fix actually worked. Nothing leaves your machine.

```sh
pipx install orchestra-review
orchestra-review
```

## What it found

**In 67,074 public agent runs** (OpenHands with Qwen3-Coder on real GitHub issues from 1,823 repositories):
- **41% of the failures with an identifiable cause repeated a mistake seen in another repository.**
- **62% of runs** hit at least one of those mistakes.
- **The largest was asking to view lines past the end of a file:** 21,780 runs across 1,509 repositories.
- **Second was piping after `find -exec ... \;`,** which that shell tool rejects: 5,406 runs.
- **Built-in rules cover 59%** of those repeated failures, and the nine rules mined from this data ship with the tool.
- **Runs that hit a repeated mistake resolved their issue less often,** 44.5% against 53.6%. That's a correlation, not a measured effect.

Details and limits: [`research/`](research/).

**In the author's own logs** (as of 2026-11-16): 74 sessions across Claude Code, Codex and OpenCode, with 188 failed tool calls. **51 of those failures (27%) repeated a mistake from an earlier session.** The mistakes were all about the machine:
- `pdftoppm` missing for PDF reads (8 sessions);
- zsh treating `echo ====` as a command (7 sessions);
- `No module named 'fitz'` (7 sessions, across Claude Code and Codex);
- zsh erroring on a glob that matches nothing (5 sessions).

Six lines went into `~/.claude/CLAUDE.md` on 2026-11-13. Each line is judged only on sessions that **tried** the action it covers:

| Fix | Sessions that hit it / tried it, before | After | Verdict |
| --- | --- | --- | --- |
| zsh: a glob that matches nothing is an error | 5 / 15 | 0 / 7 | stopped |
| zsh: quote words starting with `=` | 5 / 14 | 2 / 4 | too early, still happening |
| `pdftoppm` missing for PDF reads | 8 / 9 | 0 / 0 | too early |
| `fitz`, `pypdf`, `docx` not importable | 5 / 10, 2 / 10, 2 / 4 | 0 / 0 | too early |

"Too early" means fewer than five sessions have tried the action since the line was added. One person's sessions are a small sample.

## Usage

```sh
orchestra-review                          # what your agents keep getting wrong, with a fix line for each
orchestra-review apply 6eab0c6e --to ~/.claude/CLAUDE.md   # add one line, with a timed marker
orchestra-review sync                     # add rule-based lines for mistakes in 3+ sessions, retire stale ones
orchestra-review undo 6eab0c6e            # remove a line; it will never be added back automatically
orchestra-review hook install             # Claude Code: block known mistakes live, and sync when a session ends
orchestra-review --public                 # scrub paths, file names, URLs and emails, for screenshots
orchestra-review --json                   # everything, as JSON
```

## How it works

- **Finding mistakes.** A recurring mistake is a failure in two or more sessions that shares the same last error line, ignoring numbers and ids. Some failures are left out:
  - test runs that fail, because the agent is checking its work;
  - calls refused by a permission rule or interrupted by you, which are counted as blocked;
  - error lines that say nothing about the cause, such as a bare exit code or a path.
- **Fix lines.** Lines come from built-in rules: missing programs and Python modules, zsh `=` and glob quirks, old-Python syntax, and misused file-viewing and editing tools. For other causes, a local model you run yourself (Ollama, `--model`) can draft a line. A draft is kept only if it names the cause and contains no URL or command that downloads or deletes anything, because log text is untrusted and the line ends up in a file your agent obeys. Drafted lines are never added automatically.
- **`sync`.** It adds a rule-based line once a mistake has hit three sessions. If the mistake was seen in only one project, the line goes into that project's instruction file, but only if the file already exists; otherwise it goes into the agent's global file. Before keeping a line, `sync` re-checks its fact on this machine: is the program still missing, can the module still not be imported, is the shell still zsh? When a fact stops being true, for example after you install `poppler`, the line is removed and logged. A line you delete by hand, or remove with `undo`, is never added back.
- **The hook.** `hook install` adds two Claude Code hooks to `~/.claude/settings.json`, keeping a `.bak` copy of the original:
  - **Before a tool call** that would repeat a known mistake (running a missing program, an unquoted zsh `=word`, or reading a PDF without `pdftoppm`), the hook re-checks the fact and blocks the call with the fix as the reason. The agent corrects course without the failed step.
  - **Never blocked:**
    - missing Python modules, because importability depends on the working directory and virtualenv (a replay of 67k public runs showed most such blocks would have been wrong; see [`research/`](research/));
    - zsh glob mistakes, because whether a glob matches depends on the directory at run time;
    - commands that install software or change PATH themselves.
  - **When a session ends,** the other hook runs `sync`.

  Any error in either hook lets the call through.
- **Measurement.** Before-and-after counts only sessions that tried the relevant action, so a change of task can't look like a cure.
- **Privacy.** Everything is read locally. Nothing is sent anywhere unless you point `--model` at a model server. `--public` and `share` drop paths, file names, project names and commands.

## Scope

- **Reads:**
  - Claude Code, `~/.claude/projects`, including subagents;
  - Codex CLI, `~/.codex/sessions`;
  - OpenCode, through `opencode session export`, for a project directory.

  Cursor is not supported.
- **Runs on:** macOS and Linux with Python 3.11 or later, with no dependencies. Windows is untested.
- **Maintained:** best-effort. Issues are welcome; there are no promised response times.

Changes: [`CHANGELOG.md`](CHANGELOG.md). Design notes: [`docs/design.md`](docs/design.md). MIT licensed.
