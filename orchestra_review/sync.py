"""Keeps instruction files in step with the logs: adds rule-based lines for mistakes that keep recurring,
retires lines whose fact no longer holds, and respects lines you removed.

Model-drafted lines are never added here; they need `apply --include-drafted`."""
from pathlib import Path

from . import state as st
from .detectors import by_signature
from .facts import holds
from .fixes import Fix,fact,fix_id,rule_fix
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


def files_of(entry):
    """A fix can sit in several files, one per agent (state written by 0.2.0 kept a single `file`)."""
    return list(entry.get('files') or ([entry['file']] if entry.get('file') else []))


def record(state,fix,key,path,how,added=None):
    entry=state['fixes'].get(fix.id) or {'line':fix.line,'key':list(key) if key else None,'fact':fact(key) if key else None,
                                         'applied':added or st.now(),'how':how}
    files=files_of(entry)
    if str(path) not in files: files.append(str(path))
    entry['files']=files;entry.pop('file',None)
    state['fixes'][fix.id]=entry
    state['retired'].pop(fix.id,None)
    if how=='manual': state['suppressed'].pop(fix.id,None)  # applying by hand overrides an earlier undo


def adopt(state,signatures):
    """Lines already in instruction files (added by hand or before state existed) are taken into account."""
    keys={fix_id(key):key for key in signatures}
    known={Path(f) for entry in state['fixes'].values() for f in files_of(entry)}
    for path in {*global_files().values(),*known}:
        for fid,added in markers(path):
            if fid in state['suppressed'] and fid not in state['fixes']: continue
            key=keys.get(fid)
            fix=rule_fix(key) if key else None
            entry=state['fixes'].get(fid)
            if entry and str(path) in files_of(entry): continue
            line=fix.line if fix else (entry or {}).get('line')
            record(state,Fix(fid,line,'rule'),key,path,'adopted',added.strftime('%Y-%m-%dT%H:%MZ'))


def sync(sessions,state=None,dry_run=False,minimum=AUTO_MIN_SESSIONS):
    """One pass: notice hand removals, retire stale lines, add new rule-based lines. Returns the changes made.
    Removing a line by hand from any file stops sync adding that fix anywhere again; copies elsewhere stay."""
    state=state if state is not None else st.load()
    signatures=by_signature(sessions)
    adopt(state,signatures)
    changes=[]
    for fid,entry in list(state['fixes'].items()):
        files=files_of(entry)
        gone=[f for f in files if fid not in {m for m,_ in markers(f)}]
        for f in gone:
            changes.append(('removed by hand',fid,f,None))
            if not dry_run:
                state['suppressed'][fid]={'at':st.now(),'reason':'removed by hand'};st.log(state,'removed by hand',fid,f)
        files=[f for f in files if f not in gone]
        if not dry_run: entry['files']=files;entry.pop('file',None)
        if not files:
            if not dry_run: del state['fixes'][fid]
            continue
        if holds(entry.get('fact')) is False:
            for f in files: changes.append(('retired',fid,f,describe(entry['fact'])))
            if not dry_run:
                for f in files: remove(f,fid)
                state['retired'][fid]={'at':st.now(),'files':files,'reason':describe(entry['fact'])}
                del state['fixes'][fid];st.log(state,'retired',fid,', '.join(files),describe(entry['fact']))
    for key,hits in signatures.items():
        fid=fix_id(key)
        if len(hits)<minimum or fid in state['suppressed']: continue
        fix=rule_fix(key)
        if not fix or holds(fact(key)) is False: continue
        everywhere={m for path in global_files().values() for m,_ in markers(path)}
        for path in targets(hits,sessions):
            if fid in {m for m,_ in markers(path)}: continue
            if fid in everywhere and path not in global_files().values(): continue  # a global file already covers it
            changes.append(('added',fid,str(path),fix.line))
            if not dry_run:
                apply(path,[fix]);record(state,fix,key,path,'auto');st.log(state,'added',fid,path,fix.line)
    if not dry_run: st.save(state)
    return changes


def undo(fid,state=None):
    """Removes a line wherever orchestra-review knows it to be, and never adds it back automatically."""
    state=state if state is not None else st.load()
    files={*global_files().values()}
    if fid in state['fixes']: files.update(Path(f) for f in files_of(state['fixes'][fid]))
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
