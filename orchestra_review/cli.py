"""Find the mistakes your coding agents repeat across sessions. Nothing leaves this machine.

Reads Claude Code transcripts (~/.claude/projects), Codex CLI rollouts (~/.codex/sessions) and OpenCode
sessions for the given project directories (default: the current directory).

  orchestra-review                         report, with a suggested instruction line per recurring mistake
  orchestra-review apply ID --to FILE      append those lines to an instruction file, dated for later measurement
  orchestra-review sync                    add rule-based lines for mistakes in 3+ sessions, retire lines whose fact changed
  orchestra-review undo ID                 remove a line and never add it back automatically
  orchestra-review hook install            block known mistakes live in Claude Code, and sync when a session ends
  orchestra-review share > mine.json       counts and scrubbed causes only, safe to send to someone else
  orchestra-review combine a.json b.json   which mistakes recur for how many people"""
import argparse
import importlib.metadata
from datetime import datetime,timedelta,timezone
import json
import os
import re
import sys

from . import claude_code,codex,opencode
from .detectors import recurring
from .fixes import suggest
from . import hooks,share
from . import state as st
from .instructions import apply
from .sync import record,sync,undo
from .report import build,render


def version():
    try: return importlib.metadata.version('orchestra-review')
    except importlib.metadata.PackageNotFoundError: return 'unknown'


def since(value):
    if value=='all': return None
    match=re.fullmatch(r'(\d+)([dh])',value)
    if not match: raise argparse.ArgumentTypeError('use a number of days or hours, such as 30d or 12h, or all')
    amount=int(match.group(1))
    return datetime.now(timezone.utc)-(timedelta(days=amount) if match.group(2)=='d' else timedelta(hours=amount))


def collect(args):
    sessions=[]
    if args.source in ('all','claude-code'): sessions+=claude_code.load(args.claude_dir)
    if args.source in ('all','codex'): sessions+=codex.load(args.codex_dir)
    if args.source in ('all','opencode'):
        for path in args.opencode_export: sessions+=opencode.load_exports(path)
        if not args.opencode_export:
            for directory in args.opencode_project or ['.']: sessions+=opencode.load_project(directory)
    if args.since: sessions=[s for s in sessions if s.ended and s.ended>=args.since]
    if args.session: sessions=[s for s in sessions if s.id.startswith(args.session)]
    return [s for s in sessions if s.steps]


def sources(parser):
    parser.add_argument('--source',choices=['all','claude-code','codex','opencode'],default='all')
    parser.add_argument('--since',type=since,default=None,help='only sessions active within this window, such as 30d (default: all)')
    parser.add_argument('--claude-dir',default=claude_code.default_root(),help='Claude Code projects directory')
    parser.add_argument('--codex-dir',default=codex.default_root(),help='Codex CLI sessions directory')
    parser.add_argument('--opencode-project',action='append',help='project directory whose OpenCode sessions to read; repeatable')
    parser.add_argument('--opencode-export',action='append',default=[],help='OpenCode export file or directory of them; repeatable')
    parser.add_argument('--session',help='only sessions whose id starts with this')
    parser.add_argument('--model',help='local Ollama model that drafts a line when no rule matches, such as qwen3:4b')
    parser.add_argument('--model-url',default=os.environ.get('OLLAMA_HOST','http://127.0.0.1:11434'))


def main(argv=None):
    argv=sys.argv[1:] if argv is None else argv
    if argv[:1]==['apply']: return apply_main(argv[1:])
    if argv[:1]==['share']: return share_main(argv[1:])
    if argv[:1]==['combine']: return combine_main(argv[1:])
    if argv[:1]==['sync']: return sync_main(argv[1:])
    if argv[:1]==['undo']: return undo_main(argv[1:])
    if argv[:1]==['hook']: return hook_main(argv[1:])
    parser=argparse.ArgumentParser(prog='orchestra-review',description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--version',action='version',version=f'orchestra-review {version()}')
    sources(parser)
    parser.add_argument('--instructions',action='append',default=[],help='extra instruction file to measure fixes in; repeatable')
    parser.add_argument('--top',type=int,default=10)
    parser.add_argument('--json',action='store_true',help='print the full result as JSON')
    parser.add_argument('--public',action='store_true',help='scrub paths, file names, URLs and emails from the output, for screenshots')
    args=parser.parse_args(argv)
    data=build(collect(args),top=args.top,model=args.model,model_url=args.model_url,instruction_files=args.instructions,public=args.public)
    print(json.dumps(data,indent=2) if args.json else render(data))
    return 0


def apply_main(argv):
    parser=argparse.ArgumentParser(prog='orchestra-review apply',
                                   description='Append suggested lines to an instruction file, each with a dated marker.')
    parser.add_argument('ids',nargs='+',help='fix ids from the report')
    parser.add_argument('--to',required=True,help='instruction file, such as ~/.claude/CLAUDE.md or ./AGENTS.md')
    parser.add_argument('--include-drafted',action='store_true',
                        help='also write lines drafted by a model; by default only rule-based lines are written')
    sources(parser)
    args=parser.parse_args(argv)
    fixes,keys={},{}
    for key,hits in recurring(collect(args)):
        fix=suggest(key,hits,args.model,args.model_url)
        fixes[fix.id]=fix;keys[fix.id]=key
    chosen=[]
    for fid in args.ids:
        fix=fixes.get(fid)
        if not fix or not fix.line: print(f'{fid}: no suggested line for this id',file=sys.stderr);return 1
        if fix.source=='model' and not args.include_drafted:
            print(f'{fid}: drafted by a model; review it and pass --include-drafted to write it',file=sys.stderr);return 1
        chosen.append(fix)
    path=os.path.expanduser(args.to)
    written=apply(path,chosen)
    state=st.load()
    for fix in chosen:
        record(state,fix,keys[fix.id],path,'manual')
        if fix.id in written: st.log(state,'added',fix.id,path,fix.line)
    st.save(state)
    for fix in chosen: print(('added   ' if fix.id in written else 'present ')+f'[{fix.id}] {fix.line}')
    print(f'→ {path}')
    return 0


def sync_main(argv):
    parser=argparse.ArgumentParser(prog='orchestra-review sync',description='Add rule-based lines for mistakes seen in 3 or more '
                                   'sessions, retire lines whose fact no longer holds, and respect lines you removed.')
    parser.add_argument('--dry-run',action='store_true',help='show what would change without writing anything')
    sources(parser)
    args=parser.parse_args(argv)
    changes=sync(collect(args),dry_run=args.dry_run)
    for action,fid,path,detail in changes: print(f'{action:<16} [{fid}] {path}' + (f' — {detail}' if detail else ''))
    if not changes: print('Nothing to change.')
    return 0


def undo_main(argv):
    parser=argparse.ArgumentParser(prog='orchestra-review undo',description='Remove a line and never add it back automatically.')
    parser.add_argument('id')
    args=parser.parse_args(argv)
    removed=undo(args.id)
    print(f'removed [{args.id}] from {", ".join(removed)}' if removed else f'[{args.id}] was not in any known instruction file; it will not be added automatically')
    return 0


def hook_main(argv):
    parser=argparse.ArgumentParser(prog='orchestra-review hook',description='Claude Code hooks.')
    parser.add_argument('action',choices=['install','uninstall',hooks.PRE,hooks.END])
    parser.add_argument('--settings',default=os.path.expanduser('~/.claude/settings.json'),help='Claude Code settings file')
    sources(parser)
    args=parser.parse_args(argv)
    if args.action==hooks.PRE: return hooks.pre_tool_use()
    if args.action==hooks.END: return hooks.session_end(lambda:collect(args))
    if args.action=='install':
        hooks.install(args.settings)
        print(f'Installed the PreToolUse and SessionEnd hooks in {args.settings} (original saved as {args.settings}.bak).')
        print('Run `orchestra-review sync` once so the hook knows which mistakes to block.')
        return 0
    print('Removed the orchestra-review hooks.' if hooks.uninstall(args.settings) else 'No orchestra-review hooks were installed.')
    return 0



def share_main(argv):
    parser=argparse.ArgumentParser(prog='orchestra-review share',
                                   description='Print a share (JSON) on stdout and a preview of everything in it on stderr.')
    sources(parser)
    args=parser.parse_args(argv)
    data=share.summary(collect(args))
    print(share.preview(data),file=sys.stderr)
    print(json.dumps(data,indent=2))
    return 0


def combine_main(argv):
    parser=argparse.ArgumentParser(prog='orchestra-review combine',description='Combine shares from several people.')
    parser.add_argument('files',nargs='+')
    parser.add_argument('--json',action='store_true')
    args=parser.parse_args(argv)
    try: data=share.combine(share.load(args.files))
    except (OSError,ValueError) as error: print(error,file=sys.stderr);return 1
    print(json.dumps(data,indent=2) if args.json else share.render_combined(data))
    return 0


if __name__=='__main__': sys.exit(main())
