"""Entry point for the browser version (review.varuntx.us), which runs this package in Pyodide.

Agent logs run to hundreds of megabytes, so the page streams them: it hands over one file at a time, add_file()
parses it into a compact session and deletes the raw text, and finish() builds the report. A zip from the helper
command is read the same way, one entry at a time. Files are recognised by their content, not their paths,
because people drop ~/.claude, ~/.claude/projects, ~/.codex or a zip with any layout. Nothing here touches the
network; the page sends nothing anywhere."""
import json
import os
from pathlib import Path,PurePosixPath
import shutil
import zipfile

from . import claude_code,codex,opencode
from .report import build

HOMES=Path('/tmp/orchestra-review-homes')
WORK=Path('/tmp/orchestra-review-work')
GLOBAL_FILES={'CLAUDE.md':('.claude','claude','CLAUDE_CONFIG_DIR'),'AGENTS.md':('.codex','codex','CODEX_HOME')}
_sessions=[]
_counts={}


def start():
    """Forgets any earlier analysis and points the global instruction files at empty homes."""
    global _sessions,_counts
    _sessions,_counts=[],{'claude-code':0,'codex':0,'opencode':0,'unrecognised':0}
    for folder in (HOMES,WORK): shutil.rmtree(folder,ignore_errors=True);folder.mkdir(parents=True)
    for _,(_,home,variable) in GLOBAL_FILES.items():
        (HOMES/home).mkdir();os.environ[variable]=str(HOMES/home)


def wanted(name):
    """Which dropped files are worth reading: logs, exports and the two global instruction files."""
    return name.endswith(('.jsonl','.json')) or PurePosixPath(name).name in GLOBAL_FILES


def global_file(relative):
    """A dropped ~/.claude/CLAUDE.md or ~/.codex/AGENTS.md lets the report measure fixes already in place.
    Only the agent-wide copies count: the file at the top of the drop, or directly inside .claude/ or .codex/."""
    parts=PurePosixPath(relative).parts
    spec=GLOBAL_FILES.get(parts[-1]) if parts else None
    if not spec: return None
    return HOMES/spec[1]/parts[-1] if len(parts)==1 or parts[-2]==spec[0] else None


def sniff(path):
    """Which agent wrote this file, judged from its first readable lines."""
    try:
        with open(path,encoding='utf-8',errors='replace') as handle:
            if path.suffix=='.json':
                data=json.load(handle)
                return 'opencode' if isinstance(data,dict) and 'messages' in data and 'info' in data else None
            for _,line in zip(range(20),handle):
                try: entry=json.loads(line)
                except ValueError: continue
                if not isinstance(entry,dict): continue
                if 'payload' in entry and entry.get('type') in ('session_meta','response_item','turn_context','event_msg'): return 'codex'
                if 'sessionId' in entry or entry.get('type') in ('assistant','user','summary'): return 'claude-code'
    except (OSError,ValueError): return None
    return None


def add_file(path,relative=None,consume=True):
    """Reads one dropped file into a session. With `consume`, the browser's copy is deleted afterwards to keep memory
    flat; the folder-wide analyze() never deletes anything. Returns what the file was recognised as."""
    path=Path(path);relative=relative or path.name
    try:
        home=global_file(relative)
        if home: shutil.copyfile(path,home);return 'instructions'
        kind=sniff(path)
        if kind=='claude-code': session=claude_code.read(path)
        elif kind=='codex': session=codex.read(path)
        elif kind=='opencode': session=opencode.parse(json.loads(path.read_text(encoding='utf-8',errors='replace')))
        else: session=None
        if session is not None and session.steps:
            if kind=='claude-code': session.id=claude_id(relative,session.id)
            _sessions.append(session)
        _counts[kind or 'unrecognised']+=1
        return kind or 'unrecognised'
    finally:
        if consume and path.exists(): path.unlink()


def claude_id(relative,fallback):
    """Claude Code names files by session id; subagent files sit in <session>/subagents/, as in the CLI."""
    parts=PurePosixPath(relative).parts
    stem=PurePosixPath(relative).stem
    return parts[-3]+'/'+stem if len(parts)>=3 and parts[-2]=='subagents' else (stem or fallback)


def add_zip(path,consume=True):
    """Reads a zip one entry at a time, skipping anything that isn't a log or instruction file."""
    path=Path(path)
    try:
        with zipfile.ZipFile(path) as archive:
            for number,member in enumerate(archive.infolist()):
                if member.is_dir() or not wanted(member.filename) or member.filename.startswith('__MACOSX/'): continue
                target=WORK/f'{number}{PurePosixPath(member.filename).suffix}'
                with archive.open(member) as source,open(target,'wb') as out: shutil.copyfileobj(source,out)
                add_file(target,member.filename)  # the extracted copy is always deleted
    finally:
        if consume and path.exists(): path.unlink()


def finish(public=False,top=15):
    """The report as JSON text, plus how many files of each kind were read."""
    data=build(_sessions,top=top,public=public)
    data['files']=dict(_counts)
    return json.dumps(data)


def analyze(root,public=False,top=15):
    """Whole-folder version of the same flow, for tests and the command line."""
    start()
    root=Path(root)
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        relative=path.relative_to(root).as_posix()
        if path.suffix=='.zip': add_zip(path,consume=False)
        elif wanted(relative): add_file(path,relative,consume=False)
    return finish(public,top)
