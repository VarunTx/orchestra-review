"""Codex CLI rollouts in both shapes: function_call shells and `exec` custom tool calls with JSON chunks."""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).parents[1]))

from orchestra_review import cli,codex

T='2026-11-10T10:00:00.000Z'


def rollout(path,items):
    path.parent.mkdir(parents=True,exist_ok=True)
    lines=[{'timestamp':T,'type':'session_meta','payload':{'id':'01abc','cwd':'/work/app'}},
           {'timestamp':T,'type':'turn_context','payload':{'model':'gpt-test','cwd':'/work/app'}},
           {'timestamp':T,'type':'response_item','payload':{'type':'message','role':'user','content':[]}}]
    lines+=[{'timestamp':T,'type':'response_item','payload':p} for p in items]
    path.write_text('\n'.join(map(json.dumps,lines))+'\n{broken')
    return path


def exec_call(cid,cmd):
    return {'type':'custom_tool_call','name':'exec','call_id':cid,'input':f'text(await tools.exec_command({{cmd:"{cmd}",max_output_tokens:6000}}));'}


def exec_output(cid,code,output):
    chunk=json.dumps({'chunk_id':'a1','wall_time_seconds':0.1,'exit_code':code,'output':output})
    return {'type':'custom_tool_call_output','call_id':cid,'output':[{'type':'input_text','text':'Script completed\nOutput:\n'},
                                                                    {'type':'input_text','text':chunk}]}


def test_exec_calls_with_json_chunks(tmp_path):
    path=rollout(tmp_path/'2026'/'11'/'10'/'rollout-2026-11-10T10-00-00-01abc.jsonl',[
        exec_call('c1','python3 -c \\"import fitz\\"'),exec_output('c1',1,"Traceback\nModuleNotFoundError: No module named 'fitz'"),
        exec_call('c2','ls'),exec_output('c2',0,'a b'),
        {'type':'custom_tool_call','name':'exec','call_id':'c3','input':'x'},
        {'type':'custom_tool_call_output','call_id':'c3','output':[{'type':'input_text','text':'Output:\n{"chunk_id":"z","exit_code":1,"output":"trunc'}]}])
    s=codex.read(path)
    first,second,third=s.steps
    assert (first.kind,first.ok,first.exit_code,first.target)==('shell',False,1,'python3 -c "import fitz"')
    assert first.error.endswith("No module named 'fitz'")
    assert second.ok is True and third.kind=='other' and third.ok is None
    assert (s.id,s.project,s.models,s.prompts,s.skipped_lines)==('01abc','/work/app',['gpt-test'],1,1)


def test_function_call_shells_and_wrapped_parallel_chunks(tmp_path):
    wrapped=json.dumps({'i':0,'status':'fulfilled','value':{'chunk_id':'b','exit_code':127,'output':'zsh: command not found: jq'}})
    path=rollout(tmp_path/'r.jsonl',[
        {'type':'function_call','name':'shell','call_id':'f1','arguments':json.dumps({'command':['bash','-lc','jq .x a.json']})},
        {'type':'function_call_output','call_id':'f1','output':json.dumps({'output':'bash: jq: command not found','metadata':{'exit_code':127}})},
        exec_call('e1','jq . b.json'),
        {'type':'custom_tool_call_output','call_id':'e1','output':[{'type':'input_text','text':'Output:\n'+wrapped}]},
        {'type':'function_call','name':'spawn_agent','call_id':'f2','arguments':'{}'},
        {'type':'function_call_output','call_id':'f2','output':'error: nope'}])
    s=codex.read(path)
    assert [(x.target,x.ok,x.exit_code) for x in s.steps]==[('jq .x a.json',False,127),('jq . b.json',False,127),('spawn_agent',None,None)]
    assert s.steps[0].error=='bash: jq: command not found' and s.steps[1].error=='zsh: command not found: jq'


def test_cli_reads_codex(tmp_path,capsys):
    rollout(tmp_path/'codex'/'r.jsonl',[exec_call('c1','ls'),exec_output('c1',0,'x')])
    assert cli.main(['--source','codex','--codex-dir',str(tmp_path/'codex'),'--json'])==0
    assert json.loads(capsys.readouterr().out)['by_source']=={'codex':1}
