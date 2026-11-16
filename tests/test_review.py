"""Importers, waste rules and redaction against synthetic transcripts; no real session is read."""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).parents[1]))

from orchestra_review import claude_code,cli,opencode
from orchestra_review.detectors import recurring
from orchestra_review.model import Session,Step
from orchestra_review.redact import redact
from orchestra_review.report import build,render

T='2026-11-01T10:00:00Z'


def call(uid,name,data,mid='m1',usage=None):
    message={'id':mid,'model':'claude-test','content':[{'type':'tool_use','id':uid,'name':name,'input':data}]}
    if usage: message['usage']=usage
    return {'type':'assistant','timestamp':T,'cwd':'/work','message':message}


def result(uid,text,error=False,**extra):
    return {'type':'user','timestamp':T,'message':{'content':[{'type':'tool_result','tool_use_id':uid,'content':text,'is_error':error}]},**extra}


def transcript(path,entries):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('\n'.join(e if isinstance(e,str) else json.dumps(e) for e in entries)+'\n')
    return path


def steps(*specs):
    """(kind, target, ok, output) tuples become a session; output stands in for the result digest."""
    s=Session(source='test',id='s')
    for i,(kind,target,ok,output) in enumerate(specs,1):
        s.steps.append(Step(index=i,tool=kind,kind=kind,target=target,ok=ok,digest=output,error=output if ok is False else None))
    return s


def test_claude_outcomes_exit_codes_and_blocked_calls(tmp_path):
    path=transcript(tmp_path/'p'/'abc.jsonl',[
        call('t1','Bash',{'command':'python  x.py'}),result('t1','Exit code 127\nzsh: command not found: python',error=True),
        call('t2','Read',{'file_path':'/a.py'}),result('t2','contents'),
        call('t3','Bash',{'command':'rm -rf /'}),result('t3','Permission for this command was denied',error=True,toolDenialKind='permission-rule'),
        call('t4','Bash',{'command':'sleep 9'}),
        '{not json',{'type':'custom-title','customTitle':'Fix it'}])
    s=claude_code.read(path)
    first,second,third,fourth=s.steps
    assert (first.ok,first.exit_code,first.target)==(False,127,'python x.py')
    assert 'command not found' in first.error
    assert second.ok is True and second.kind=='read'
    assert third.ok is None and third.blocked
    assert fourth.ok is None and not fourth.blocked
    assert (s.skipped_lines,s.title,s.project,s.models)==(1,'Fix it','/work',['claude-test'])


def test_claude_subagents_are_separate_sessions(tmp_path):
    transcript(tmp_path/'p'/'abc.jsonl',[call('t1','Bash',{'command':'ls'}),result('t1','x')])
    transcript(tmp_path/'p'/'abc'/'subagents'/'agent-1.jsonl',[call('t1','Bash',{'command':'ls'}),result('t1','x')])
    assert sorted(s.id for s in claude_code.load(tmp_path))==['abc','abc/agent-1']


def opencode_export():
    def tool(name,data,status='completed',exit=None,text='ok'):
        return {'type':'tool','name':name,'time':{'created':1762000000000},
                'state':{'status':status,'input':data,'content':[{'type':'text','text':text}],'metadata':{'exit':exit} if exit is not None else {}}}
    return {'info':{'id':'ses_1','title':'Build it','cost':0.5},'messages':[
        {'type':'user','time':{'created':1762000000000}},
        {'type':'assistant','time':{'created':1762000001000},'model':{'id':'deepseek-flash'},'cost':0.5,
         'tokens':{'input':3,'output':4,'reasoning':2,'cache':{'read':50,'write':1}},
         'content':[tool('shell',{'command':'npm test'},exit=1,text='1 failing'),tool('read',{'path':'a.ts'}),
                    tool('webfetch',{'url':'https://x'},status='error',text=''),tool('shell',{'command':'npm run dev'},status='running')]}]}


def test_opencode_export_steps_and_outcomes(tmp_path):
    s=opencode.parse(opencode_export())
    assert [(x.kind,x.ok) for x in s.steps]==[('shell',False),('read',True),('web',False),('shell',None)]
    assert s.steps[0].exit_code==1 and s.steps[0].error=='1 failing'
    assert (s.prompts,s.models,s.title)==(1,['deepseek-flash'],'Build it')


def test_recurring_mistakes_ignore_numbers_and_skip_bare_exit_codes():
    a=steps(('shell','python a.py',False,'Traceback\nModuleNotFoundError: No module named fitz'),('shell','x',False,'Exit code 1'))
    b=steps(('shell','python3 b.py 2',False,'line 7\nModuleNotFoundError: No module named fitz'),('shell','y',False,'Exit code 1'))
    b.id='other'
    found=recurring([a,b])
    assert len(found)==1 and found[0][0]==('shell','ModuleNotFoundError: No module named fitz')
    assert sum(map(len,found[0][1].values()))==2


def test_redaction_scrubs_credential_shapes():
    text=('curl -H "Authorization: Bearer abc.def.ghi123" https://u:pw@host '
          'API_KEY=hunter2 OPENAI_TOKEN: "s p" sk-abcdefghijklmnop12 ghp_abcdefghijklmnopqrstu '
          + 'a'*40 + ' ' + 'f'*32)
    clean=redact(text)
    for secret in ('abc.def.ghi123','pw@','hunter2','s p','sk-abc','ghp_','a'*40,'f'*32): assert secret not in clean
    assert redact('/Users/me/project/src/module.py')=='/Users/me/project/src/module.py'


def test_cli_reads_both_sources_without_touching_real_logs(tmp_path,capsys):
    transcript(tmp_path/'claude'/'p'/'abc.jsonl',[call('t1','Bash',{'command':'ls'}),result('t1','x')])
    export=tmp_path/'oc.json';export.write_text(json.dumps(opencode_export()))
    assert cli.main(['--claude-dir',str(tmp_path/'claude'),'--opencode-export',str(export),'--json'])==0
    data=json.loads(capsys.readouterr().out)
    assert data['by_source']=={'claude-code':1,'opencode':1} and data['steps']==5 and data['failed_steps']==2


def test_public_report_scrubs_paths_and_names():
    s=steps(('shell','ssh alex-laptop 10.1.2.3 cat /Users/alex/acme/notes.md',False,'cat: /Users/alex/acme/notes.md: No such file or directory'))
    other=steps(('shell','cat /Users/alex/acme/notes.md',False,'cat: /Users/alex/acme/notes.md: No such file or directory'));other.id='o'
    text=json.dumps(build([s,other],public=True))
    assert 'alex' not in text and 'acme' not in text and 'notes.md' not in text and '10.1.2.3' not in text
    assert 'alex' in json.dumps(build([s,other]))
    assert 'repeat a mistake from another session' in render(build([s,other],public=True))
