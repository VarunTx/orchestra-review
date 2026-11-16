"""Turns sessions into one structure about repeated mistakes, rendered as text or JSON."""
from collections import Counter
from pathlib import Path

from .detectors import by_signature,recurring
from .fixes import exposure,fix_id,suggest
from .instructions import global_files,governed,markers,measure
from .redact import redact
from .share import scrub


def short(text,limit=110,public=False):
    text=scrub(text) if public else ' '.join(redact(text or '').split())
    return text if len(text)<=limit else text[:limit-1]+'…'


def build(sessions,top=10,model=None,model_url=None,instruction_files=(),public=False):
    """`public` scrubs paths, file names, URLs and emails from every quoted cause and example, for screenshots."""
    failed=sum(1 for s in sessions for x in s.steps if x.ok is False)
    repeats=recurring(sessions)
    times=[t for s in sessions for t in (s.started,s.ended) if t]
    return {
        'sessions':len(sessions),
        'by_source':dict(Counter(s.source for s in sessions)),
        'period':[min(times).isoformat(),max(times).isoformat()] if times else None,
        'steps':sum(len(s.steps) for s in sessions),'failed_steps':failed,
        'blocked_steps':sum(1 for s in sessions for x in s.steps if x.blocked),
        'skipped_lines':sum(s.skipped_lines for s in sessions),
        'recurring_failed_steps':sum(len(v) for _,hits in repeats for v in hits.values()),
        'recurring':[recurring_row(key,hits,suggest(key,hits,model,model_url),public) for key,hits in repeats[:top]],
        'fixes_in_place':fixes_in_place(sessions,instruction_files,public),
    }


def recurring_row(key,hits,fix,public=False):
    first=next(iter(hits.values()))[0]
    return {'kind':key[0],'cause':short(key[1],160,public),'sessions':len(hits),'failed_steps':sum(map(len,hits.values())),
            # Commands can name hosts and projects, so a public report shows none.
            'example':None if public else short(first.target,200),'fix':{'id':fix.id,'line':fix.line,'source':fix.source,'note':fix.note}}


def instruction_paths(sessions,extra=()):
    paths=[*global_files().values(),*map(Path,extra)]
    for project in sorted({s.project for s in sessions if s.project}):
        paths+=[Path(project)/'AGENTS.md',Path(project)/'CLAUDE.md']
    unique=[]
    for path in paths:
        if path.expanduser().resolve() not in [p.expanduser().resolve() for p in unique]: unique.append(path)
    return unique


def fixes_in_place(sessions,extra=(),public=False):
    signatures=by_signature(sessions)
    hits={fix_id(key):set(by_session) for key,by_session in signatures.items()}
    keys={fix_id(key):key for key in signatures}
    rows=[]
    for path in instruction_paths(sessions,extra):
        for fid,added in markers(path):
            tools={x.tool for steps in signatures[keys[fid]].values() for x in steps} if fid in keys else None
            tried=exposure(keys[fid],tools) if fid in keys else None  # unknown when the mistake is absent from these logs
            rows.append({'file':path.name if public else str(path),**measure(fid,added,governed(path,sessions),hits,tried)})
    return rows


def number(n):
    return f'{n:,}'


def render(data):
    if not data['sessions']: return 'No agent sessions found.'
    out=[]
    period=f" · {data['period'][0][:10]} → {data['period'][1][:10]}" if data['period'] else ''
    sources=', '.join(f'{k} {v}' for k,v in sorted(data['by_source'].items()))
    out.append(f"Orchestra Review — {data['sessions']} sessions ({sources}){period}")
    failed,recurring_steps=data['failed_steps'],data['recurring_failed_steps']
    share=f" ({recurring_steps/failed:.0%})" if failed else ''
    out.append(f"{number(data['steps'])} tool calls · {number(failed)} failed · {number(recurring_steps)} of those repeat "
               f"a mistake from another session{share}")
    notes=[f"{number(data['blocked_steps'])} blocked by permissions or the user, not counted as failures"]*bool(data['blocked_steps'])
    notes+=[f"skipped {number(data['skipped_lines'])} unreadable log lines"]*bool(data['skipped_lines'])
    if notes: out.append(' · '.join(notes))
    out.append('')
    if not data['recurring']: out.append('No mistake has repeated across sessions yet.')
    else:
        out.append('Mistakes your agent repeats')
        for r in data['recurring']:
            out.append(f"  {r['sessions']} sessions, {r['failed_steps']} failures — {short(r['cause'],100)}")
            if r['example']: out.append(f"    e.g. {short(r['example'],100)}")
            fix=r['fix']
            out.append(f"    fix [{fix['id']}, {fix['source']}]: {fix['line']}" if fix['line'] else f"    no fix: {fix['note']}")
        if any(r['fix']['line'] for r in data['recurring']):
            out.append('  Apply one with: orchestra-review apply <id> --to <instruction file>')
    if data['fixes_in_place']:
        out.append('')
        out.append('Fixes in place: sessions that hit the mistake / sessions that tried the action, before → after')
        for f in data['fixes_in_place']:
            side=lambda s:f"{s['hit']}/{s['tried']}" if s['tried'] is not None else f"{s['hit']}/{s['sessions']} (all sessions)"
            out.append(f"  [{f['id']}] {f['added']} {Path(f['file']).name}: {side(f['before'])} → {side(f['after'])} — {f['verdict']}")
    return '\n'.join(out)
