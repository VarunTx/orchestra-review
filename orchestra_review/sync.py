"""Keeps instruction files in step with the logs: adds rule-based lines for mistakes that keep recurring,
retires lines whose fact no longer holds, and respects lines you removed.

Model-drafted lines are never added here; they need `apply --include-drafted`."""
from pathlib import Path

from . import state as st
from .detectors import by_signature
from .facts import holds
from .fixes import fact,fix_id,rule_fix
from .instructions import apply,global_files,markers,remove

AUTO_MIN_SESSIONS=3
PROJECT_FILE={'claude-code':'CLAUDE.md','opencode':'AGENTS.md','codex':'AGENTS.md'}


def targets(hits,sessions):
    """Machine-wide mistakes go to each agent's global file. A mistake seen in only one project goes to that project's
    instruction file, but only if the project already has one: sync never creates files inside your projects."""
    by_id={(s.source,s.id):s for s in sessions}
    hit=[by_id[k] for k in hits if k in by_id]
    projects={s.project for s in hit}
    files=global_files()
    chosen=[]
    for source in sorted({s.source for s in hit}):
        local=Path(next(iter(projects)))/PROJECT_FILE.get(source,'AGENTS.md') if len(projects)==1 and None not in projects else None
        if local and local.is_file(): chosen.append(local)
        elif source in files: chosen.append(files[source])
    return chosen


def record(state,fix,key,path,how):
    state['fixes'][fix.id]={'line':fix.line,'key':list(key),'fact':fact(key),'file':str(path),'applied':st.now(),'how':how}
    state['retired'].pop(fix.id,None)
    state['suppressed'].pop(fix.id,None)  # applying by hand overrides an earlier undo


def adopt(state,signatures):
    """Lines already in instruction files (added by hand or before state existed) are taken into account."""
    keys={fix_id(key):key for key in signatures}
    for path in {*global_files().values(),*(Path(f['file']) for f in state['fixes'].values())}:
        for fid,added in markers(path):
            if fid in state['fixes'] or fid in state['suppressed']: continue
            key=keys.get(fid)
            fix=rule_fix(key) if key else None
            state['fixes'][fid]={'line':fix.line if fix else None,'key':list(key) if key else None,'fact':fact(key) if key else None,
                                 'file':str(path),'applied':added.strftime('%Y-%m-%dT%H:%MZ'),'how':'adopted'}


def sync(sessions,state=None,dry_run=False,minimum=AUTO_MIN_SESSIONS):
    """One pass: notice hand removals, retire stale lines, add new rule-based lines. Returns the changes made."""
    state=state if state is not None else st.load()
    signatures=by_signature(sessions)
    adopt(state,signatures)
    changes=[]
    for fid,entry in list(state['fixes'].items()):
        if fid not in {m for m,_ in markers(entry['file'])}:
            changes.append(('removed by hand',fid,entry['file'],None))
            if not dry_run:
                state['suppressed'][fid]={'at':st.now(),'reason':'removed by hand'};del state['fixes'][fid]
                st.log(state,'removed by hand',fid,entry['file'])
            continue
        if holds(entry.get('fact')) is False:
            changes.append(('retired',fid,entry['file'],describe(entry['fact'])))
            if not dry_run:
                remove(entry['file'],fid)
                state['retired'][fid]={'at':st.now(),'file':entry['file'],'reason':describe(entry['fact'])}
                del state['fixes'][fid];st.log(state,'retired',fid,entry['file'],describe(entry['fact']))
    for key,hits in signatures.items():
        fid=fix_id(key)
        if len(hits)<minimum or fid in state['fixes'] or fid in state['suppressed']: continue
        fix=rule_fix(key)
        if not fix or holds(fact(key)) is False: continue
        for path in targets(hits,sessions):
            if fid in {m for m,_ in markers(path)}: continue
            changes.append(('added',fid,str(path),fix.line))
            if not dry_run:
                apply(path,[fix]);record(state,fix,key,path,'auto');st.log(state,'added',fid,path,fix.line)
    if not dry_run: st.save(state)
    return changes


def undo(fid,state=None):
    """Removes a line wherever orchestra-review knows it to be, and never adds it back automatically."""
    state=state if state is not None else st.load()
    files={*global_files().values()}
    if fid in state['fixes']: files.add(Path(state['fixes'][fid]['file']))
    removed=[str(path) for path in files if remove(path,fid)]
    state['fixes'].pop(fid,None)
    state['suppressed'][fid]={'at':st.now(),'reason':'undo'}
    st.log(state,'undo',fid,', '.join(removed) or None)
    st.save(state)
    return removed


def describe(spec):
    if not spec: return None
    if spec['type']=='program-missing': return f"`{spec['name']}` is now installed"
    if spec['type']=='module-missing': return f"`{spec['name']}` is now importable"
    if spec['type']=='shell-is-zsh': return 'the shell is no longer zsh'
    return None
