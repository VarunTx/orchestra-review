"""The browser entry point: recognises logs by content, streams them, measures dropped instruction files,
and never deletes anything it was pointed at from the command line."""
import json
from pathlib import Path
import subprocess
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).parents[1]))

from orchestra_review import web

CLAUDE=[{'type':'assistant','timestamp':'2026-11-01T10:00:00Z','sessionId':'s','cwd':'/w','message':{'id':'m','model':'x','content':[
            {'type':'tool_use','id':'t','name':'Bash','input':{'command':'jq . a'}}]}},
        {'type':'user','timestamp':'2026-11-01T10:00:01Z','sessionId':'s','message':{'content':[
            {'type':'tool_result','tool_use_id':'t','content':'Exit code 127\n(eval):1: command not found: jq','is_error':True}]}}]


def claude_log(n):
    return '\n'.join(json.dumps(x) for x in CLAUDE).replace('2026-11-01',f'2026-11-{n+1:02d}')+'\n'


def test_zip_with_any_layout_is_recognised_and_left_in_place(tmp_path):
    archive=tmp_path/'agent-logs.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for n in range(3): z.writestr(f'.claude/projects/p/s{n}.jsonl',claude_log(n))
        z.writestr('.claude/projects/p/s0/subagents/agent-a.jsonl',claude_log(0))
        z.writestr('.claude/CLAUDE.md','- jq line <!-- orchestra-review:00000000 2026-11-02T00:00Z -->\n')
        z.writestr('notes/README.md','not a log');z.writestr('../escape.jsonl',claude_log(0))
    data=json.loads(web.analyze(tmp_path))
    assert archive.exists()  # analyze() never deletes what it was pointed at
    assert data['files']['claude-code']==5 and data['by_source']=={'claude-code':5}
    assert data['recurring'][0]['sessions']==5 and data['recurring'][0]['fix']['line']
    assert not (tmp_path.parent/'escape.jsonl').exists()


def test_streaming_api_deletes_only_its_own_copies(tmp_path):
    web.start()
    upload=tmp_path/'upload-1.jsonl';upload.write_text(claude_log(0))
    assert web.add_file(upload,'.claude/projects/p/abc.jsonl')=='claude-code' and not upload.exists()
    kept=tmp_path/'kept.jsonl';kept.write_text(claude_log(1))
    web.add_file(kept,'x/kept.jsonl',consume=False)
    assert kept.exists() and json.loads(web.finish())['sessions']==2


def test_only_agent_wide_instruction_files_count():
    assert web.global_file('CLAUDE.md') and web.global_file('.claude/CLAUDE.md') and web.global_file('.codex/AGENTS.md')
    assert web.global_file('repo/CLAUDE.md') is None and web.global_file('.claude/projects/x/CLAUDE.md') is None


def test_sample_builder_produces_a_report(tmp_path):
    subprocess.run([sys.executable,str(Path(__file__).parents[1]/'web'/'make_sample.py'),'--out',str(tmp_path)],check=True)
    report=json.loads((tmp_path/'sample-report.json').read_text())
    assert report['sessions']>=15 and report['fixes_in_place'][0]['verdict']=='stopped'
    assert (tmp_path/'sample-logs.zip').exists()
