"""Recurring mistakes across 67,074 public coding-agent runs (nebius/SWE-rebench-openhands-trajectories, CC-BY-4.0).

OpenHands driving Qwen3-Coder-480B on real GitHub issues from 1,823 repositories. Each run is treated as one session,
so "recurring" means the same mistake in different runs; the stronger signal is the same mistake in different
repositories, which points at the environment or the agent rather than one codebase.

Needs pyarrow (not a dependency of orchestra-review itself):
  python -m venv /tmp/arrow && /tmp/arrow/bin/pip install pyarrow
  /tmp/arrow/bin/python research/swe_rebench.py trajectories.parquet --out research/results.json [--limit 2000]
"""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0,str(Path(__file__).parents[1]))

from orchestra_review.detectors import signature
from orchestra_review.facts import invokes
from orchestra_review.fixes import category,rule_fix
from orchestra_review.model import Step,tail

EXIT=re.compile(r'\[(?:The command|Command)[^\]]*?exit code (-?\d+)[^\]]*\]')
FOOTER=re.compile(r'^\[(?:Python interpreter|Current working directory|The command|Command)[^\]]*\]\s*$',re.M)  # OpenHands status lines
REPO_PATH=re.compile(r'/workspace/[^/\s\'"]+')
RECOVERY_WINDOW=5


def steps_of(trajectory):
    """OpenHands messages as steps: execute_bash is a shell call whose exit code is in the observation text;
    str_replace_editor is a read (view) or an edit, failing when its observation starts with ERROR."""
    calls,steps={},[]
    for message in trajectory:
        if message['role']=='assistant':
            for call in message.get('tool_calls') or []:
                fn=call.get('function') or {}
                try: args=json.loads(fn.get('arguments') or '{}')
                except ValueError: args={}
                name=fn.get('name','')
                if name=='execute_bash': kind,target='shell',' '.join(str(args.get('command','')).split())
                elif name=='str_replace_editor':
                    kind='read' if args.get('command')=='view' else 'edit'
                    target=str(args.get('path',''))
                else: kind,target='other',name
                step=Step(index=len(steps)+1,tool=name,kind=kind,target=REPO_PATH.sub('/workspace/<repo>',target))
                steps.append(step);calls[call.get('id')]=step
        elif message['role']=='tool' and message.get('tool_call_id') in calls:
            step=calls.pop(message['tool_call_id']);text=message.get('content') or ''
            if step.kind=='shell':
                code=EXIT.search(text)
                if code is None: continue  # timed out or still running: no outcome
                step.exit_code=int(code[1]);step.ok=step.exit_code==0
                body=REPO_PATH.sub('/workspace/<repo>',FOOTER.sub('',text))
            elif step.kind in ('read','edit'):
                step.ok=not text.lstrip().startswith('ERROR');body=REPO_PATH.sub('/workspace/<repo>',text)
            else: continue
            if step.ok is False: step.error=tail(body)
    return steps


def first_word(command):
    for segment in re.split(r'&&|\|\||;|\|',command):
        words=[w for w in segment.split() if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*=',w)]
        if words and words[0] not in ('cd','sudo','env','timeout'): return words[0]
    return ''


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('parquet');parser.add_argument('--out',required=True);parser.add_argument('--limit',type=int)
    args=parser.parse_args()
    import pyarrow.parquet as pq
    source=pq.ParquetFile(args.parquet)
    runs=steps_total=failed_total=resolved_total=0
    sigs=defaultdict(lambda:{'runs':0,'failures':0,'resolved':0,'repos':set(),'recovery':Counter(),'same_program':0,'recovered':0})
    run_hits=[]  # (resolved, failed steps on cross-repo mistakes) per run, filled in a second pass over this list
    started=time.time()
    for batch in source.iter_batches(batch_size=256,columns=['trajectory_id','repo','resolved','trajectory']):
        for row in batch.to_pylist():
            if args.limit and runs>=args.limit: break
            runs+=1;resolved=bool(row['resolved']);resolved_total+=resolved
            steps=steps_of(row['trajectory'] or [])
            steps_total+=len(steps);failed=[s for s in steps if s.ok is False];failed_total+=len(failed)
            mine=Counter()
            for step in failed:
                key=signature(step)
                if not key: continue
                mine[key]+=1
                sig=sigs[key]
                after=[s for s in steps[step.index:step.index+RECOVERY_WINDOW] if s.kind=='shell' and s.ok]
                if step.kind=='shell' and after:
                    sig['recovered']+=1;word=first_word(after[0].target)
                    sig['recovery'][word]+=1;sig['same_program']+=word==first_word(step.target)
            for key,count in mine.items():
                sig=sigs[key];sig['runs']+=1;sig['failures']+=count;sig['resolved']+=resolved;sig['repos'].add(row['repo'])
            run_hits.append((resolved,dict(mine)))
        if args.limit and runs>=args.limit: break
        print(f'{runs:,} runs, {time.time()-started:.0f}s',file=sys.stderr,flush=True)
    cross={key for key,sig in sigs.items() if len(sig['repos'])>=2}
    recurring_failures=sum(sig['failures'] for key,sig in sigs.items() if key in cross)
    hit=[r for r,mine in run_hits if any(k in cross for k in mine)];clean=[r for r,mine in run_hits if not any(k in cross for k in mine)]
    top=sorted(cross,key=lambda k:-sigs[k]['runs'])[:40]
    result={
        'dataset':'nebius/SWE-rebench-openhands-trajectories','runs':runs,'steps':steps_total,'failed_steps':failed_total,
        'resolved_runs':resolved_total,
        'failures_with_cause':sum(sig['failures'] for sig in sigs.values()),
        'cross_repo_failures':recurring_failures,'cross_repo_causes':len(cross),
        'runs_hitting_cross_repo_mistake':len(hit),
        'resolve_rate_hit':round(sum(hit)/len(hit),4) if hit else None,
        'resolve_rate_clean':round(sum(clean)/len(clean),4) if clean else None,
        'rule_covered_failures':sum(sigs[k]['failures'] for k in cross if rule_fix(k)),
        'top':[{'tool':k[0],'cause':k[1],'runs':sigs[k]['runs'],'repos':len(sigs[k]['repos']),'failures':sigs[k]['failures'],
                'resolve_rate':round(sigs[k]['resolved']/sigs[k]['runs'],4),'category':category(k),
                'rule_line':(rule_fix(k).line if rule_fix(k) else None),
                'recovered_share':round(sigs[k]['recovered']/sigs[k]['failures'],4) if sigs[k]['failures'] else None,
                'top_recoveries':sigs[k]['recovery'].most_common(5)} for k in top],
    }
    Path(args.out).write_text(json.dumps(result,indent=1))
    print(json.dumps({k:v for k,v in result.items() if k!='top'},indent=1))


if __name__=='__main__': main()
