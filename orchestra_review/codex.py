"""Codex CLI keeps one JSONL rollout per session under ~/.codex/sessions/YYYY/MM/DD.

Shell calls appear in two shapes, depending on the Codex version: a `function_call` (shell, shell_command,
exec_command) whose output carries an exit code, or a `custom_tool_call` named `exec` whose input is a short
script calling tools.exec_command({cmd: ...}) and whose output holds JSON chunks with an exit_code."""
import json
import os
from pathlib import Path
import re

from .model import Session,Step,digest,iso_time,tail

SHELL_FUNCTIONS={'shell','shell_command','exec_command','local_shell','container.exec'}
CMD=re.compile(r'\bcmd\s*:\s*"((?:[^"\\]|\\.)*)"')
EXIT=re.compile(r'"exit_code"\s*:\s*(-?\d+)|Exit code:?\s*(-?\d+)|"exit_code\\?"\s*:\s*(-?\d+)')


def default_root():
    return Path(os.environ.get('CODEX_HOME') or Path.home()/'.codex')/'sessions'


def load(root):
    root=Path(root)
    return [read(path) for path in sorted(root.rglob('*.jsonl'))] if root.is_dir() else []


def text_of(output):
    """Outputs are a string, a JSON string, or a list of {type: input_text, text} parts."""
    if isinstance(output,list): return '\n'.join(p.get('text','') for p in output if isinstance(p,dict))
    if isinstance(output,dict): return json.dumps(output)
    return str(output or '')


def command_of(name,arguments):
    try: data=json.loads(arguments) if isinstance(arguments,str) else (arguments or {})
    except ValueError: return None
    command=data.get('command') if isinstance(data,dict) else None
    if command is None and isinstance(data,dict): command=data.get('cmd')
    if isinstance(command,list):
        # ["bash", "-lc", "real command"] is the common wrapper; keep the real command.
        command=command[-1] if len(command)>=3 and command[1] in ('-lc','-c') else ' '.join(map(str,command))
    return ' '.join(str(command).split()) if command else None


def outcome(text):
    """ok and exit code from every exit code in the output: any non-zero means the call failed."""
    codes=[int(next(g for g in m.groups() if g is not None)) for m in EXIT.finditer(text)]
    if not codes: return None,None
    bad=[c for c in codes if c!=0]
    return (False,bad[0]) if bad else (True,0)


def chunks(text):
    """JSON chunks from an `exec` output: each sits on its own line after the "Output:" header."""
    for line in text.splitlines():
        if line.startswith('{') and '"exit_code"' in line:
            try: data=json.loads(line)
            except ValueError: continue  # truncated by Codex
            # Parallel calls arrive wrapped as {"i": n, "status": ..., "value": {chunk}}.
            yield data.get('value') if isinstance(data.get('value'),dict) else data


def error_text(text):
    """The `output` field of the failing chunk, or of a JSON output; otherwise the raw tail."""
    for chunk in chunks(text):
        if chunk.get('exit_code') not in (0,None): return tail(str(chunk.get('output','')))
    if '"chunk_id"' in text: return None  # the failing chunk was truncated: no cause rather than a wrong one
    try:
        data=json.loads(text)
        if isinstance(data,dict) and 'output' in data: return tail(str(data['output']))
    except ValueError: pass
    return tail(text)


def read(path):
    path=Path(path)
    s=Session(source='codex',id=path.stem.split('-',6)[-1] if path.stem.startswith('rollout-') else path.stem)
    pending={}
    with path.open(encoding='utf-8',errors='replace') as lines:
        for line in lines:
            try: entry=json.loads(line)
            except ValueError: s.skipped_lines+=1;continue
            if not isinstance(entry,dict): s.skipped_lines+=1;continue
            at=iso_time(entry.get('timestamp'));payload=entry.get('payload')
            if not isinstance(payload,dict): continue
            try: take(s,entry,payload,at,pending)
            except (TypeError,AttributeError,KeyError,ValueError): s.skipped_lines+=1  # a shape this version doesn't know
    return s


def take(s,entry,payload,at,pending):
    """One rollout entry. Raises on shapes it does not know; read() counts those as skipped lines."""
    kind=entry.get('type');ptype=payload.get('type')
    if kind=='session_meta':
        s.project=s.project or (payload.get('cwd') if isinstance(payload.get('cwd'),str) else None);s.id=str(payload.get('id') or s.id)
    elif kind=='turn_context':
        s.model(payload.get('model'));s.project=s.project or (payload.get('cwd') if isinstance(payload.get('cwd'),str) else None)
    if kind!='response_item': return
    s.seen(at)
    if ptype=='message' and payload.get('role')=='user': s.prompts+=1
    elif ptype in ('function_call','custom_tool_call'):
        name=str(payload.get('name',''))
        if ptype=='custom_tool_call' and name=='exec':
            cmds=[bytes(c,'utf-8').decode('unicode_escape') for c in CMD.findall(str(payload.get('input','')))]
            command=' ; '.join(' '.join(c.split()) for c in cmds) or None
        else: command=command_of(name,payload.get('arguments')) if name in SHELL_FUNCTIONS else None
        step=Step(index=len(s.steps)+1,tool=name,kind='shell' if command else ('edit' if name=='apply_patch' else 'other'),
                  target=command or name,at=at)
        s.steps.append(step);pending[payload.get('call_id')]=step
    elif ptype in ('function_call_output','custom_tool_call_output') and payload.get('call_id') in pending:
        step=pending.pop(payload['call_id'])
        text=text_of(payload.get('output'))
        step.digest=digest(text)
        if step.kind=='shell':  # only shell calls report an outcome Codex records reliably
            step.ok,step.exit_code=outcome(text)
            if step.ok is False: step.error=error_text(text)
