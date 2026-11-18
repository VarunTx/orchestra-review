"""Readers meet logs from versions we have never seen: any line, any shape, must never crash a report."""
import json
from pathlib import Path
import random
import sys

sys.path.insert(0,str(Path(__file__).parents[1]))

from orchestra_review import claude_code,codex,opencode
from orchestra_review.report import build,render
from orchestra_review.share import summary

ODD=[None,0,1.5,'',"x",[],{},[1,'a',None],{'type':None},{'content':5},True]


def mutate(value,rng,depth=0):
    """Replaces, drops or retypes parts of a valid record at random."""
    if isinstance(value,dict):
        out={}
        for key,item in value.items():
            roll=rng.random()
            if roll<0.1: continue
            out[key]=rng.choice(ODD) if roll<0.25 else mutate(item,rng,depth+1)
        return out
    if isinstance(value,list):
        return [mutate(item,rng,depth+1) for item in value if rng.random()>0.1]+([rng.choice(ODD)] if rng.random()<0.2 else [])
    return rng.choice(ODD) if rng.random()<0.15 else value


CLAUDE=[{'type':'assistant','timestamp':'2026-11-01T10:00:00Z','cwd':'/w','message':{'id':'m','model':'x','content':[
            {'type':'tool_use','id':'t1','name':'Bash','input':{'command':'ls'}}]}},
        {'type':'user','timestamp':'2026-11-01T10:00:01Z','toolUseResult':{'interrupted':False},'message':{'content':[
            {'type':'tool_result','tool_use_id':'t1','content':[{'type':'text','text':'Exit code 1\nboom'}],'is_error':True}]}},
        {'type':'user','message':{'content':'hello'}},{'type':'custom-title','customTitle':'t'}]
CODEX=[{'timestamp':'2026-11-01T10:00:00Z','type':'session_meta','payload':{'id':'s','cwd':'/w'}},
       {'timestamp':'2026-11-01T10:00:00Z','type':'turn_context','payload':{'model':'m'}},
       {'timestamp':'2026-11-01T10:00:00Z','type':'response_item','payload':{'type':'custom_tool_call','name':'exec','call_id':'c','input':'tools.exec_command({cmd:"ls"})'}},
       {'timestamp':'2026-11-01T10:00:00Z','type':'response_item','payload':{'type':'custom_tool_call_output','call_id':'c','output':[{'type':'input_text','text':'{"chunk_id":"a","exit_code":2,"output":"bad"}'}]}},
       {'timestamp':'2026-11-01T10:00:00Z','type':'response_item','payload':{'type':'function_call','name':'shell','call_id':'d','arguments':'{"command":["bash","-lc","x"]}'}},
       {'timestamp':'2026-11-01T10:00:00Z','type':'response_item','payload':{'type':'function_call_output','call_id':'d','output':'{"output":"e","metadata":{"exit_code":1}}'}}]
OPENCODE={'info':{'id':'s','title':'t','cost':1},'messages':[{'type':'user','time':{'created':1}},
          {'type':'assistant','time':{'created':2},'model':{'id':'m'},'content':[
              {'type':'tool','name':'shell','time':{'created':3},'state':{'status':'completed','input':{'command':'x'},
               'content':[{'type':'text','text':'err'}],'metadata':{'exit':1}}}]}]}


def test_readers_and_report_survive_random_damage(tmp_path):
    rng=random.Random(7)
    sessions=[]
    for case in range(300):
        claude=tmp_path/f'c{case}.jsonl';cx=tmp_path/f'x{case}.jsonl'
        lines=[mutate(entry,rng) for entry in CLAUDE*2]
        text='\n'.join(json.dumps(x) for x in lines)
        if rng.random()<0.3: text=text[:rng.randrange(len(text))]  # truncated mid-line
        claude.write_text(text)
        cx.write_text('\n'.join(json.dumps(mutate(entry,rng)) for entry in CODEX*2))
        sessions+=[claude_code.read(claude),codex.read(cx),opencode.parse(mutate(OPENCODE,rng))]
    sessions=[s for s in sessions if s.steps]
    assert sessions
    render(build(sessions));render(build(sessions,public=True));summary(sessions)


def test_binary_and_empty_files_are_tolerated(tmp_path):
    (tmp_path/'a.jsonl').write_bytes(b'\x00\xff\xfe garbage\n\x89PNG')
    (tmp_path/'b.jsonl').write_text('')
    assert all(not s.steps for s in claude_code.load(tmp_path)+codex.load(tmp_path))
