# Repeated mistakes in 67,074 public agent runs

[`swe_rebench.py`](swe_rebench.py) runs Orchestra Review's mistake detection over **nebius/SWE-rebench-openhands-trajectories** (CC-BY-4.0). The dataset is 67,074 runs of the OpenHands agent driving Qwen3-Coder-480B on real GitHub issues from 1,823 repositories, and each run records whether the issue was resolved.

Each run is treated as one session. "Recurring" here means the same mistake in **two or more different repositories**: a mistake that follows the agent from codebase to codebase belongs to the agent or its tools, not to any one project. Results are in [`results.json`](results.json). The full pass takes about a minute.

## Results

| | |
| --- | --- |
| Runs / tool calls / failed calls | 67,074 / 4,316,760 / 386,869 |
| Failed calls with an identifiable cause (test runs failing on purpose excluded) | 196,984 |
| **…of which repeat a mistake seen in another repository** | **80,187 (41%)**, from 2,861 distinct causes |
| Runs that hit at least one of those mistakes | 41,562 (62%) |
| Of the repeated failures, covered by Orchestra Review's built-in rules | 47,152 (59%) |

**The top recurring mistakes were about the tools, not the code:**

| Mistake | Runs | Repositories | Failed calls |
| --- | --- | --- | --- |
| Viewing a file with a line range past its end | 21,780 + 2,286 | 1,509 + 429 | 31,782 |
| `find ... -exec ... {} \;` followed by a pipe: a syntax error in this shell tool | 5,406 | 682 | 6,273 |
| `SyntaxError: invalid syntax` (no rule: too general) | 745 | 317 | 930 |
| An f-string with a backslash, on Python older than 3.12 | 663 | 228 | 849 |
| Calling the edit tool with identical old and new text | 514 | 243 | 585 |
| `python setup.py test`, which modern setuptools removed | 420 | 52 | 421 |
| `grep` on a directory without `-r` | 398 | 200 | 406 |
| `create` on a file that already exists | 364 | 164 | 364 |
| `subprocess.run(capture_output=...)` on Python older than 3.7 | 340 | 76 | 358 |

In the first two rows the agent hit the same wall 1.2 to 1.4 times per affected run. In the `find` row it recovered by rewriting the `find` command in 99.8% of cases. Each of these failures has a one-line fix, and the nine mined rules now ship with Orchestra Review.

**Runs that hit a recurring mistake resolved their issue less often: 44.5% against 53.6% for runs that didn't.** This is a correlation, not a measured effect of the mistakes. Harder issues produce longer runs, and longer runs have more chances to hit anything. Measuring the effect would mean re-running the agent with the instruction lines added, which this analysis does not do.

## Replaying the blocking hook

[`hook_replay.py`](hook_replay.py) runs every public run through the hook's own blocking rule. Within each run, once a call fails because a program or module is missing, every later shell call is checked with `blocks()`. The question is whether the hook would have stopped a repeat of the failure, or blocked a call that worked. Results are in [`hook_replay.json`](hook_replay.json).

**The first replay changed the product.** As first built, the hook also blocked imports of modules seen missing earlier. It would have blocked 20,907 calls, and 18,223 of those then succeeded. Whether a module imports depends on the working directory, the interpreter and the virtualenv. The typical case: "No module named X" from one directory, then a working `import X` from the repository root. So:
- Missing-module mistakes now get an instruction line, but are **never blocked**.
- Two bugs in the program check were found and fixed:
  - text inside quoted code (`python -c "... file(...)"`) was read as running `file`;
  - commands that change PATH or install something in the same line (`export PATH=... && go version`) could be blocked.

**After those changes**, program-missing facts produce 315 matching calls in 67,074 runs. In almost all of them the agent had installed something in between, often under a different package name: `poppler-utils` provides `pdffonts`, `netcat` provides `nc`. The live hook re-checks with `which` before blocking, so it would let those calls through. Only 10 calls would have been blocked after an approximated re-check, and that sample is too small to estimate how often a block is wrong.

**What this says.** In throwaway containers where agents install whatever is missing, a repeated program-missing failure is rare and blocking adds little. The hook is for machines where a tool stays missing for weeks, such as the author's Mac, where `pdftoppm` failed in 8 of 9 sessions that read a PDF. Its precision there is not yet measured.

## Drafting lines with a small local model

When no rule covers a mistake, Orchestra Review can ask a local model to draft the line. The gate set before testing was: at most 30 seconds per draft, and at least 8 of 10 drafts passing the grounding and safety checks. [`nitro_drafter.json`](nitro_drafter.json) has the run: Qwen3 4B Instruct (Q4) on a GTX 1650 laptop, reached through Ollama over Tailscale, on 10 real causes with no rule (5 from the author's logs, 5 from the public runs).

- **Speed passed easily:** 1.7 to 5.3 seconds per draft, and 6.6 seconds including a cold model load.
- **The checks passed, but the lines were weak.** With the first prompt, all 10 drafts passed. By the author's reading, about 3 were useful: two about browser tabs that show a local file, and one about pytest conftests. The rest were confident advice for ordinary code bugs, such as "Stop using shell with invalid syntax; switch to Python".
- **Asking the model to decline didn't work.** A stricter prompt told it to answer `null` for code bugs. It never did, though three drafts then failed the checks and were dropped.

So passing the checks does not mean the advice is good, and the gate as set was too weak to catch it. Two changes followed:
- Generic exceptions (`SyntaxError`, `IndexError`, `AttributeError` and the like) are never sent to the model.
- Drafted lines stay suggestions, never added automatically.

The usefulness judgments come from the author's reading, not from blind labels.

## Method and limits

- **Failures:** a shell call failed when OpenHands reports a non-zero exit code. An editor call failed when its observation starts with `ERROR`. Calls with no recorded outcome (timeouts) are left out.
- **Same mistake:** two failures count as one mistake when their last error line matches, ignoring numbers, ids and the `/workspace/<repo>` prefix. OpenHands status lines are stripped first.
- **Excluded:** test runs that fail (`AssertionError`, `FAILED (...)`, "tests failed", reproduce scripts) are not counted as mistakes, because the agent is checking its work. Bare `Exit code N` lines and bare paths are also left out.
- **Generalisation:** this is one agent and one model. Two of the top mistakes, `view_range` and the `find ... \; |` parsing, are specific to OpenHands' tools. They show what the method finds, not how often Claude Code or Codex make the same mistakes.
- **Recovery:** "recovered" means a successful shell call within the next five steps. The program it ran is counted as the recovery.

Reproduce it (pyarrow is needed only for these scripts):

```sh
curl -L -o trajectories.parquet https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories/resolve/main/trajectories.parquet   # 2.08 GB
python -m venv /tmp/arrow && /tmp/arrow/bin/pip install pyarrow
/tmp/arrow/bin/python research/swe_rebench.py trajectories.parquet --out research/results.json
/tmp/arrow/bin/python research/hook_replay.py trajectories.parquet --out research/hook_replay.json
```
