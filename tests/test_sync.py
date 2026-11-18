"""Auto-apply, retiring, undo, hand removal and the Claude Code hooks, against temporary files only."""
from datetime import datetime,timezone
import io
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]))

from orchestra_review import facts,hooks
from orchestra_review import state as st
from orchestra_review.fixes import fix_id
from orchestra_review.instructions import markers
from orchestra_review.model import Session,Step
from orchestra_review.sync import sync,targets,undo

MISSING=('shell','(eval):#: command not found: jq')
MODULE=('shell',"ModuleNotFoundError: No module named 'fitz'")


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    for name,folder in (('ORCHESTRA_REVIEW_HOME','state'),('CLAUDE_CONFIG_DIR','claude'),('XDG_CONFIG_HOME','config'),('CODEX_HOME','codex')):
        monkeypatch.setenv(name,str(tmp_path/folder))
    monkeypatch.setattr(facts.shutil,'which',lambda name:None)  # nothing is installed
    facts._modules.clear()
    monkeypatch.setattr(facts,'module_missing',lambda name:True)
    return tmp_path


def failing(sid,error,project='/work/a',source='claude-code',command='jq . x.json'):
    s=Session(source=source,id=sid,project=project,started=datetime(2026,11,1,tzinfo=timezone.utc))
    s.steps.append(Step(index=1,tool='Bash',kind='shell',target=command,ok=False,error=error))
    return s


def jq_sessions(n,projects=('/work/a','/work/b')):
    return [failing(f's{i}','zsh: x\n(eval):1: command not found: jq',project=projects[i%len(projects)]) for i in range(n)]


def test_sync_adds_rule_lines_only_from_three_sessions(isolated):
    assert sync(jq_sessions(2))==[]
    changes=sync(jq_sessions(3))
    claude=isolated/'claude'/'CLAUDE.md'
    assert [c[0] for c in changes]==['added'] and changes[0][2]==str(claude)
    assert [fid for fid,_ in markers(claude)]==[fix_id(MISSING)]
    assert sync(jq_sessions(3))==[]  # already present
    entry=st.load()['fixes'][fix_id(MISSING)]
    assert entry['how']=='auto' and entry['fact']=={'type':'program-missing','name':'jq','via':'shell'}


def test_one_project_mistakes_go_to_that_project(isolated):
    (isolated/'repo').mkdir()
    sessions=jq_sessions(3,projects=(str(isolated/'repo'),))
    hits={(s.source,s.id) for s in sessions}
    assert targets(hits,sessions)==[isolated/'claude'/'CLAUDE.md']  # no CLAUDE.md in the project: never create one
    (isolated/'repo'/'CLAUDE.md').write_text('# project\n')
    assert targets(hits,sessions)==[isolated/'repo'/'CLAUDE.md']
    (isolated/'repo2').mkdir();(isolated/'repo2'/'AGENTS.md').write_text('# agents\n')
    opencode=[failing(f'o{i}','x\n(eval):1: command not found: jq',source='opencode',project=str(isolated/'repo2')) for i in range(3)]
    assert targets({(s.source,s.id) for s in opencode},opencode)==[isolated/'repo2'/'AGENTS.md']
    gone=[failing(f'd{i}','x\n(eval):1: command not found: jq',project=str(isolated/'deleted')) for i in range(3)]
    assert targets({(s.source,s.id) for s in gone},gone)==[isolated/'claude'/'CLAUDE.md']
    spread=jq_sessions(3)+[failing('o','x\n(eval):1: command not found: jq',source='opencode',project='/work/c')]
    assert targets({(s.source,s.id) for s in spread},spread)==[isolated/'claude'/'CLAUDE.md',isolated/'config'/'opencode'/'AGENTS.md']


def test_model_drafted_and_ruleless_causes_are_never_auto_added(isolated):
    sessions=[failing(f's{i}','x\nThis tab shows a local file, not a web page') for i in range(5)]
    assert sync(sessions)==[]


def test_stale_fact_retires_the_line_and_blocks_re_adding(isolated,monkeypatch):
    sync(jq_sessions(3))
    monkeypatch.setattr(facts.shutil,'which',lambda name:'/usr/bin/'+name)  # jq got installed
    changes=sync(jq_sessions(3))
    assert changes==[('retired',fix_id(MISSING),str(isolated/'claude'/'CLAUDE.md'),'`jq` is now installed')]
    assert markers(isolated/'claude'/'CLAUDE.md')==[]
    assert fix_id(MISSING) in st.load()['retired']
    assert sync(jq_sessions(4))==[]  # the fact is false now, so the old failures don't bring it back


def test_hand_removal_and_undo_are_respected(isolated):
    sync(jq_sessions(3))
    claude=isolated/'claude'/'CLAUDE.md'
    claude.write_text('# mine\n')
    assert [c[0] for c in sync(jq_sessions(3))]==['removed by hand']
    assert sync(jq_sessions(6))==[] and markers(claude)==[]
    module=[failing(f'm{i}',"Traceback\nModuleNotFoundError: No module named 'fitz'",command='python3 -c "import fitz"') for i in range(3)]
    sync(module)
    assert undo(fix_id(MODULE))==[str(claude)]
    assert sync(module)==[] and fix_id(MODULE) in st.load()['suppressed']


def test_adopts_lines_added_before_state_existed(isolated):
    claude=isolated/'claude'/'CLAUDE.md';claude.parent.mkdir(parents=True)
    claude.write_text(f'- old line <!-- orchestra-review:{fix_id(MISSING)} 2026-11-13T17:58Z -->\n')
    assert sync(jq_sessions(3))==[]
    entry=st.load()['fixes'][fix_id(MISSING)]
    assert entry['how']=='adopted' and entry['fact']['name']=='jq' and 'jq' in entry['line']


def call(tool,data):
    out=io.StringIO()
    hooks.pre_tool_use(io.StringIO(json.dumps({'hook_event_name':'PreToolUse','tool_name':tool,'tool_input':data})),out)
    return json.loads(out.getvalue()) if out.getvalue() else None


def test_hook_blocks_a_known_mistake_only_while_its_fact_holds(isolated,monkeypatch):
    sync(jq_sessions(3))
    denied=call('Bash',{'command':'cat a.json | jq .x'})
    out=denied['hookSpecificOutput']
    assert out['permissionDecision']=='deny' and 'jq' in out['permissionDecisionReason'] and 'undo' in out['permissionDecisionReason']
    assert call('Bash',{'command':'which jq'}) is None and call('Bash',{'command':'echo jquery'}) is None
    monkeypatch.setattr(facts.shutil,'which',lambda name:'/usr/bin/jq')
    assert call('Bash',{'command':'jq . a.json'}) is None


def test_hook_blocks_pdf_reads_and_zsh_equals_but_never_globs(isolated,monkeypatch):
    monkeypatch.setenv('SHELL','/bin/zsh')
    pdf=[Session(source='claude-code',id=f'p{i}',project=f'/w/{i}',started=datetime(2026,11,1,tzinfo=timezone.utc),
                 steps=[Step(index=1,tool='Read',kind='read',target='/a/x.pdf',ok=False,error='pdftoppm is not installed. Install poppler')])
         for i in range(3)]
    zsh=[failing(f'z{i}','x\n(eval):1: ===== not found',command='echo =====') for i in range(3)]
    glob=[failing(f'g{i}','x\n(eval):1: no matches found: /tmp/*.txt',command='ls /tmp/*.txt') for i in range(3)]
    sync(pdf+zsh+glob)
    assert call('Read',{'file_path':'/docs/Paper.PDF'}) is not None and call('Read',{'file_path':'/docs/a.md'}) is None
    assert call('Bash',{'command':'echo ===='}) is not None and call('Bash',{'command':"echo '===='"}) is None
    assert call('Bash',{'command':'ls /tmp/*.txt'}) is None
    monkeypatch.setenv('SHELL','/bin/bash')
    assert call('Bash',{'command':'echo ===='}) is None


def test_hook_fails_open_on_bad_input(isolated):
    out=io.StringIO()
    assert hooks.pre_tool_use(io.StringIO('not json'),out)==0 and out.getvalue()==''


def test_install_is_idempotent_and_keeps_other_settings(isolated):
    settings=isolated/'settings.json'
    settings.write_text(json.dumps({'model':'x','hooks':{'PreToolUse':[{'matcher':'Bash','hooks':[{'type':'command','command':'other'}]}]}}))
    hooks.install(settings);hooks.install(settings)
    data=json.loads(settings.read_text())
    assert data['model']=='x' and len(data['hooks']['PreToolUse'])==2 and len(data['hooks']['SessionEnd'])==1
    assert json.loads((isolated/'settings.json.bak').read_text())['model']=='x'
    assert hooks.uninstall(settings)
    data=json.loads(settings.read_text())
    assert data['hooks']=={'PreToolUse':[{'matcher':'Bash','hooks':[{'type':'command','command':'other'}]}]}


def test_hook_never_blocks_module_imports_path_changes_or_quoted_text(isolated):
    module=[failing(f'm{i}',"Traceback\nModuleNotFoundError: No module named 'fitz'",command='python3 -c "import fitz"') for i in range(3)]
    sync(module+jq_sessions(3))
    assert call('Bash',{'command':'python3 -c "import fitz"'}) is None  # module facts depend on cwd and venv
    for command in ['export PATH=$PATH:/opt/jq/bin && jq . a','pip install jq && jq . a','source .venv/bin/activate && jq . a',
                    'python3 -c "print(1); jq(2)"','npx jq . a']:
        assert call('Bash',{'command':command}) is None,command
    assert call('Bash',{'command':'cd x && jq . a'}) is not None


def test_one_fix_can_live_in_each_agents_file(isolated):
    claude=isolated/'claude'/'CLAUDE.md';claude.parent.mkdir(parents=True)
    claude.write_text(f'- old <!-- orchestra-review:{fix_id(MISSING)} 2026-11-13T17:58Z -->\n')
    codex=[failing(f'x{i}','x\n(eval):1: command not found: jq',source='codex',project=f'/w/{i}') for i in range(3)]
    changes=sync(jq_sessions(3)+codex)
    assert changes==[('added',fix_id(MISSING),str(isolated/'codex'/'AGENTS.md'),changes[0][3])]
    entry=st.load()['fixes'][fix_id(MISSING)]
    assert entry['files']==[str(claude),str(isolated/'codex'/'AGENTS.md')]
    claude.write_text('# mine\n')  # removed by hand from one file only
    assert [c[0] for c in sync(jq_sessions(3)+codex)]==['removed by hand']
    assert markers(claude)==[] and [f for f,_ in markers(isolated/'codex'/'AGENTS.md')]==[fix_id(MISSING)]
    assert sync(jq_sessions(4)+codex)==[]  # not re-added to Claude's file


def test_reads_state_written_by_0_2_0(isolated):
    claude=isolated/'claude'/'CLAUDE.md';claude.parent.mkdir(parents=True)
    claude.write_text(f'- l <!-- orchestra-review:{fix_id(MISSING)} 2026-11-13T17:58Z -->\n')
    old=st.empty();old['fixes'][fix_id(MISSING)]={'line':'l','key':list(MISSING),'fact':{'type':'program-missing','name':'jq','via':'shell'},
                                                  'file':str(claude),'applied':'2026-11-13T17:58Z','how':'manual'}
    st.save(old)
    assert sync(jq_sessions(3))==[]
    assert st.load()['fixes'][fix_id(MISSING)]['files']==[str(claude)]


def test_no_project_copy_when_a_global_file_already_has_the_line(isolated):
    claude=isolated/'claude'/'CLAUDE.md';claude.parent.mkdir(parents=True)
    claude.write_text(f'- l <!-- orchestra-review:{fix_id(MISSING)} 2026-11-13T17:58Z -->\n')
    (isolated/'repo').mkdir();(isolated/'repo'/'CLAUDE.md').write_text('# project\n')
    assert sync(jq_sessions(3,projects=(str(isolated/'repo'),)))==[]
    assert markers(isolated/'repo'/'CLAUDE.md')==[]
