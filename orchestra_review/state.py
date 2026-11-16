"""What orchestra-review has written and why, so it never re-adds a line you removed and can retire stale ones.

Kept in ~/.orchestra-review/state.json (or $ORCHESTRA_REVIEW_HOME). Instruction files stay the source of truth for
what the agent reads; this file only remembers decisions about them."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import tempfile

LOG_LIMIT=200


def home():
    return Path(os.environ.get('ORCHESTRA_REVIEW_HOME') or Path.home()/'.orchestra-review')


def empty():
    return {'version':1,'fixes':{},'suppressed':{},'retired':{},'log':[]}


def load():
    path=home()/'state.json'
    try: data=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError): return empty()
    return {**empty(),**data} if isinstance(data,dict) else empty()


def save(state):
    """Written atomically, so a hook reading it mid-update sees the old or the new state, never half of one."""
    folder=home();folder.mkdir(parents=True,exist_ok=True)
    state['log']=state['log'][-LOG_LIMIT:]
    handle,temp=tempfile.mkstemp(dir=folder,prefix='.state-')
    with os.fdopen(handle,'w',encoding='utf-8') as out: json.dump(state,out,indent=1)
    os.replace(temp,folder/'state.json')


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')


def log(state,action,fid,file=None,detail=None):
    state['log'].append({'at':now(),'action':action,'id':fid,'file':str(file) if file else None,'detail':detail})
