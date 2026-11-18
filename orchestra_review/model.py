"""One shape for every agent's sessions, so detectors never see a source format."""
from dataclasses import dataclass,field
from datetime import datetime,timezone
import hashlib
import json

KINDS={'bash':'shell','shell':'shell','read':'read','edit':'edit','write':'edit','multiedit':'edit','notebookedit':'edit',
       'grep':'search','glob':'search','webfetch':'web','websearch':'web'}


@dataclass
class Step:
    index:int
    tool:str
    kind:str
    target:str
    ok:bool|None=None  # None: no outcome recorded, or the call was blocked
    blocked:bool=False  # refused by a permission rule or interrupted by the user
    exit_code:int|None=None
    error:str|None=None
    digest:str|None=None
    at:datetime|None=None


@dataclass
class Session:
    source:str
    id:str
    title:str|None=None
    project:str|None=None
    started:datetime|None=None
    ended:datetime|None=None
    models:list[str]=field(default_factory=list)
    steps:list[Step]=field(default_factory=list)
    prompts:int=0
    skipped_lines:int=0

    def seen(self,at):
        if not isinstance(at,datetime): return
        if self.started is None or at<self.started: self.started=at
        if self.ended is None or at>self.ended: self.ended=at

    def model(self,name):
        if isinstance(name,str) and name and name not in self.models: self.models.append(name)


def kind_of(tool):
    return KINDS.get(tool.lower(),'other')


def target_of(tool,data):
    data=data if isinstance(data,dict) else {}
    kind=kind_of(tool)
    path=data.get('file_path') or data.get('path') or data.get('notebook_path')
    if kind=='shell': return ' '.join(str(data.get('command','')).split())
    if kind=='read':
        window=[str(data[k]) for k in ('offset','limit') if data.get(k) is not None]
        return str(path)+(':'+'+'.join(window) if window else '')
    if kind=='edit': return str(path)
    if kind=='search': return str(data.get('pattern',''))+(' in '+str(data['path']) if data.get('path') else '')
    if kind=='web': return str(data.get('url') or data.get('query') or '')
    return json.dumps(data,sort_keys=True,default=str)[:300]


def digest(text):
    return None if text is None else hashlib.sha256(text.encode('utf-8','replace')).hexdigest()[:16]


def tail(text,limit=240):
    lines=[line for line in (text or '').splitlines() if line.strip()]
    excerpt='\n'.join(lines[-4:])
    if not excerpt: return None
    return excerpt if len(excerpt)<=limit else '…'+excerpt[-(limit-1):]


def iso_time(value):
    if not isinstance(value,str) or not value: return None
    try: return datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except ValueError: return None


def ms_time(value):
    return datetime.fromtimestamp(value/1000,tz=timezone.utc) if isinstance(value,(int,float)) else None
