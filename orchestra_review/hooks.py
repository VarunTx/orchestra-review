"""Claude Code hooks: block a known mistake before it runs, and keep instruction files in step when a session ends.

Both hooks fail open. Any error, unreadable input or unknown fact lets the tool call through untouched:
a broken hook must never stop the agent working."""
import json
from pathlib import Path
import shlex
import sys

from . import state as st
from .facts import blocks,holds

PRE='pre-tool-use'
END='session-end'


def reason(entry):
    line=entry.get('line') or 'This call repeats a mistake recorded in your instruction file.'
    return f'orchestra-review: {line} (checked just now; run `orchestra-review undo {entry["id"]}` if this is wrong)'


def decide(payload,state):
    """The deny decision for one PreToolUse call, or None to let it run."""
    tool,data=payload.get('tool_name'),payload.get('tool_input')
    for fid,entry in state['fixes'].items():
        spec=entry.get('fact')
        if not spec or not blocks(spec,tool,data): continue
        if holds(spec) is not True: continue  # the fact must be confirmed live, not assumed
        return {'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny',
                                      'permissionDecisionReason':reason({**entry,'id':fid})}}
    return None


def pre_tool_use(stdin=None,stdout=None):
    stdin,stdout=stdin or sys.stdin,stdout or sys.stdout
    try:
        decision=decide(json.loads(stdin.read() or '{}'),st.load())
        if decision: stdout.write(json.dumps(decision))
    except Exception: pass  # fail open
    return 0


def session_end(collect):
    """Runs a sync over the logs. Changes go to the state log, and the next report shows them."""
    from .sync import sync
    try: sync(collect())
    except Exception as error:
        try:
            state=st.load();st.log(state,'session-end failed',None,None,type(error).__name__);st.save(state)
        except Exception: pass
    return 0


def command(event):
    return f'{shlex.quote(sys.executable)} -m orchestra_review hook {event}'


def entries():
    return {'PreToolUse':{'matcher':'Bash|Read','hooks':[{'type':'command','command':command(PRE),'timeout':15}]},
            'SessionEnd':{'hooks':[{'type':'command','command':command(END),'timeout':60}]}}


def ours(group):
    return any('orchestra_review hook' in h.get('command','') for h in group.get('hooks',[]))


def install(settings):
    """Adds both hooks to a Claude Code settings file, keeping everything else and a .bak copy of the original."""
    settings=Path(settings).expanduser()
    data=json.loads(settings.read_text(encoding='utf-8')) if settings.is_file() else {}
    if settings.is_file(): settings.with_name(settings.name+'.bak').write_text(settings.read_text(encoding='utf-8'),encoding='utf-8')
    hooks=data.setdefault('hooks',{})
    for event,group in entries().items():
        hooks[event]=[g for g in hooks.get(event,[]) if not ours(g)]+[group]
    settings.parent.mkdir(parents=True,exist_ok=True)
    settings.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')


def uninstall(settings):
    settings=Path(settings).expanduser()
    if not settings.is_file(): return False
    data=json.loads(settings.read_text(encoding='utf-8'))
    hooks=data.get('hooks',{})
    changed=False
    for event in list(hooks):
        kept=[g for g in hooks[event] if not ours(g)]
        changed|=len(kept)!=len(hooks[event])
        if kept: hooks[event]=kept
        else: del hooks[event]
    if not hooks: data.pop('hooks',None)
    settings.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    return changed
