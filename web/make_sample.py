"""Builds the made-up logs behind the example report on review.varuntx.us, and that report itself.

The sessions are invented: a Claude Code user on a Mac whose agent keeps reading PDFs without pdftoppm, typing
`echo ====` in zsh and calling jq, which isn't installed, plus a few Codex sessions with the same jq habit. They
exist so the page opens showing what a report looks like, and are labelled as made up wherever they appear.

  python web/make_sample.py --out web/build"""
import argparse
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).parents[1]))

from orchestra_review.web import analyze

START=datetime(2026,10,6,9,0,tzinfo=timezone.utc)
FIX_ADDED=START+timedelta(days=21)  # the example's CLAUDE.md line for pdftoppm is added here

# (tool, input, result text, failed) per mistake
PDF=('Read',{'file_path':'/Users/sam/papers/attention.pdf'},'pdftoppm is not installed. Install poppler-utils (e.g. `brew install poppler` or `apt-get install poppler-utils`) to enable PDF page rendering.',True)
EQUALS=('Bash',{'command':'cat notes.md; echo ====; cat todo.md'},'Exit code 1\n(eval):1: ==== not found',True)
JQ=('Bash',{'command':'cat package.json | jq .scripts'},'Exit code 127\n(eval):1: command not found: jq',True)
YAML=('Bash',{'command':'python3 scripts/check_config.py'},"Exit code 1\nTraceback (most recent call last):\n  File \"scripts/check_config.py\", line 2, in <module>\n    import yaml\nModuleNotFoundError: No module named 'yaml'",True)
FINE=[('Bash',{'command':'git status --short'},' M src/app.ts',False),('Read',{'file_path':'/Users/sam/app/src/app.ts'},'export const app = 1',False),
      ('Edit',{'file_path':'/Users/sam/app/src/app.ts'},'The file has been updated.',False),('Bash',{'command':'npm test'},'Tests: 42 passed',False)]
PDF_OK=('Read',{'file_path':'/Users/sam/papers/notes.txt'},'plain text notes',False)

CLAUDE_SESSIONS=[[PDF,EQUALS],[JQ,PDF],[EQUALS,YAML],[PDF,JQ,EQUALS],[YAML],[JQ],[EQUALS,PDF],[],[PDF_OK,('Read',{'file_path':'/Users/sam/papers/b.pdf'},'(PDF page images)',False)],
                 [('Read',{'file_path':'/Users/sam/papers/c.pdf'},'(PDF page images)',False)],[('Read',{'file_path':'/Users/sam/papers/d.pdf'},'(PDF page images)',False)],
                 [('Read',{'file_path':'/Users/sam/papers/e.pdf'},'(PDF page images)',False),EQUALS],[('Read',{'file_path':'/Users/sam/papers/f.pdf'},'(PDF page images)',False)],
                 [('Read',{'file_path':'/Users/sam/papers/g.pdf'},'(PDF page images)',False)],
                 [('Read',{'file_path':'/Users/sam/papers/h.pdf'},'(PDF page images)',False),JQ],[('Read',{'file_path':'/Users/sam/papers/i.pdf'},'(PDF page images)',False)]]
CODEX_SESSIONS=[[JQ],[JQ],[]]


def claude_session(number,mistakes):
    at=START+timedelta(days=number*2,hours=number%5)
    lines=[{'type':'user','timestamp':at.isoformat(),'sessionId':f's{number}','cwd':'/Users/sam/app','message':{'role':'user','content':'Help me with the app'}}]
    for step,(tool,data,text,failed) in enumerate(FINE[:2]+list(mistakes)+FINE[2:]):
        stamp=(at+timedelta(minutes=step+1)).isoformat();uid=f't{number}_{step}'
        lines.append({'type':'assistant','timestamp':stamp,'sessionId':f's{number}','cwd':'/Users/sam/app',
                      'message':{'id':f'm{number}_{step}','model':'claude-sonnet-example','content':[{'type':'tool_use','id':uid,'name':tool,'input':data}]}})
        lines.append({'type':'user','timestamp':stamp,'sessionId':f's{number}',
                      'message':{'content':[{'type':'tool_result','tool_use_id':uid,'content':text,'is_error':failed}]}})
    return f'.claude/projects/-Users-sam-app/{number:04d}-example.jsonl','\n'.join(map(json.dumps,lines))+'\n'


def codex_session(number,mistakes):
    at=START+timedelta(days=number*5+1)
    lines=[{'timestamp':at.isoformat(),'type':'session_meta','payload':{'id':f'codex-{number}','cwd':'/Users/sam/api'}},
           {'timestamp':at.isoformat(),'type':'turn_context','payload':{'model':'gpt-example','cwd':'/Users/sam/api'}}]
    for step,(_,data,text,failed) in enumerate([('Bash',{'command':'ls'},'src',False)]+list(mistakes)):
        cid=f'c{number}_{step}';code=int(text.split('\n')[0].split()[-1]) if failed else 0
        body=text.split('\n',1)[1] if failed else text
        lines.append({'timestamp':at.isoformat(),'type':'response_item','payload':{'type':'custom_tool_call','name':'exec','call_id':cid,
                      'input':'text(await tools.exec_command({cmd:'+json.dumps(data['command'])+'}));'}})
        chunk=json.dumps({'chunk_id':'x','exit_code':code,'output':body})
        lines.append({'timestamp':at.isoformat(),'type':'response_item','payload':{'type':'custom_tool_call_output','call_id':cid,
                      'output':[{'type':'input_text','text':'Script completed\nOutput:\n'},{'type':'input_text','text':chunk}]}})
    return f'.codex/sessions/2026/10/{number:02d}/rollout-example-{number}.jsonl','\n'.join(map(json.dumps,lines))+'\n'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);args=parser.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    files=[claude_session(n,m) for n,m in enumerate(CLAUDE_SESSIONS)]+[codex_session(n,m) for n,m in enumerate(CODEX_SESSIONS)]
    pdf_line=('- Reading PDFs with the Read tool fails here because `pdftoppm` is not installed; extract the text with an '
              'installed tool or library instead. <!-- orchestra-review:6eab0c6e '+FIX_ADDED.strftime('%Y-%m-%dT%H:%MZ')+' -->\n')
    files.append(('.claude/CLAUDE.md','# My notes\n\n## Known environment mistakes\n\n'+pdf_line))
    sample=out/'sample-logs.zip'
    with zipfile.ZipFile(sample,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,text in files: archive.writestr(name,text)
    staging=out/'.sample';staging.mkdir(exist_ok=True)
    (staging/'sample-logs.zip').write_bytes(sample.read_bytes())
    (out/'sample-report.json').write_text(analyze(staging))
    (staging/'sample-logs.zip').unlink();staging.rmdir()


if __name__=='__main__': main()
