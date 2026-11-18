"""Replays the public runs through the blocking hook's decision, to measure what it would block and how often wrongly.

Within each run, once a call fails because a program is missing or a module can't be imported, that fact is
"known", exactly as `sync` would record it. Every later shell call in the same run is then checked with the hook's
own `blocks()` rule. A blocked call that went on to fail with the same mistake is a correct block, saving one failed
step. A blocked call that went on to succeed would have been a wrong block.

The live hook re-checks each fact before blocking. The replay can't re-run that check inside the original
container, so it reports two numbers: wrong blocks with no re-check at all, and wrong blocks left after
approximating the re-check. The approximation treats every fact as stale once the run installs anything (the
live `which` check would see a program however it arrived) or once a call running it has succeeded.

  /tmp/arrow/bin/python research/hook_replay.py trajectories.parquet --out research/hook_replay.json
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).parents[1]))
sys.path.insert(0,str(Path(__file__).parent))

from orchestra_review.detectors import signature
from orchestra_review.facts import blocks
from orchestra_review.fixes import fact
from swe_rebench import steps_of

# Any install may provide a program under another package name (poppler-utils provides pdffonts), and the live
# hook's `which` check would see it. So after any install, every known fact is treated as possibly stale.
INSTALL=re.compile(r'\b(?:pip3?|pipx|conda|mamba|apt(?:-get)?|brew|npm|uv|cargo)\b[^;&|]*\binstall\b|\btar\b.*\bx|\bmake install\b')


def known_fact(step):
    """The blockable fact this failure establishes, if any."""
    key=signature(step)
    spec=fact(key) if key else None
    if spec and spec['type'] in ('program-missing','module-missing') and spec.get('via','shell')=='shell': return key,spec
    return None,None


def installs(command,name):
    return INSTALL.search(command) is not None


def replay(steps,totals):
    facts={}  # key -> spec, learned from failures earlier in this run
    stale=set()
    for step in steps:
        if step.kind!='shell': continue
        for key,spec in facts.items():
            if not blocks(spec,'Bash',{'command':step.target}): continue
            same=step.ok is False and signature(step)==key
            totals['blocked']+=1
            if same: totals['correct']+=1
            elif step.ok: totals['wrong_raw']+=1
            else: totals['blocked_other_failure']+=1
            if key not in stale:  # the live hook's re-check would still find the program missing and block
                totals['live_blocked']+=1;totals['live_blocked_then_succeeded']+=bool(step.ok)
            break
        if step.ok is False:
            key,spec=known_fact(step)
            if key:
                totals['repeat_failures']+=key in facts  # a second or later failure of an already known mistake
                facts.setdefault(key,spec)
        for key,spec in facts.items():
            if installs(step.target,spec['name']) or (step.ok and blocks(spec,'Bash',{'command':step.target})): stale.add(key)


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('parquet');parser.add_argument('--out',required=True);parser.add_argument('--limit',type=int)
    args=parser.parse_args()
    import pyarrow.parquet as pq
    totals=Counter();runs=0
    for batch in pq.ParquetFile(args.parquet).iter_batches(batch_size=512,columns=['trajectory']):
        for row in batch.to_pylist():
            if args.limit and runs>=args.limit: break
            runs+=1;before=totals['blocked']
            replay(steps_of(row['trajectory'] or []),totals)
            totals['runs_with_a_block']+=totals['blocked']>before
        if args.limit and runs>=args.limit: break
    result={'runs':runs,**totals}
    if totals['blocked']:
        result['precision']=round(totals['correct']/totals['blocked'],4)
        result['wrong_block_rate_raw']=round(totals['wrong_raw']/totals['blocked'],4)
    if totals['live_blocked']:
        result['live_wrong_block_rate']=round(totals['live_blocked_then_succeeded']/totals['live_blocked'],4)
    if totals['repeat_failures']: result['repeat_failures_prevented']=round(totals['correct']/totals['repeat_failures'],4)
    Path(args.out).write_text(json.dumps(result,indent=1))
    print(json.dumps(result,indent=1))


if __name__=='__main__': main()
