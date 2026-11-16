"""Machine facts behind rule-based mistakes, checked live.

A line such as "pdftoppm is not installed" is only true until someone installs it. Before a fix is applied, kept,
or used to block a command, its fact is checked again on this machine; a fact that no longer holds retires the fix."""
import os
import re
import shutil
import subprocess

_modules={}
# Where a program sits in command position: the start, or after a pipe, `&&`, `;`, `(`, `$(` or a backtick.
COMMAND_START=r'(?:^|[;&|(`]|\$\()\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*(?:sudo\s+|env\s+|command\s+|exec\s+)?'
EQUALS_WORD=re.compile(r'(?:^|[\s;&|(])=\S')  # a lone `=`, as in `[ a = b ]`, is not expanded


def holds(spec):
    """True if the fact is still true here, False if it no longer is, None if it cannot be checked."""
    if not spec: return None
    kind=spec.get('type')
    if kind=='program-missing': return shutil.which(spec['name']) is None
    if kind=='shell-is-zsh': return os.path.basename(os.environ.get('SHELL','')).startswith('zsh') if os.environ.get('SHELL') else None
    if kind=='module-missing': return module_missing(spec['name'])
    return None


def module_missing(name):
    """Asks the default `python3`, not this interpreter: that is the one agents call."""
    if name in _modules: return _modules[name]
    python=shutil.which('python3')
    if not python or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',name): return None
    try:
        done=subprocess.run([python,'-c',f'import importlib.util,sys; sys.exit(0 if importlib.util.find_spec({name!r}) else 3)'],
                            capture_output=True,timeout=10)
    except (OSError,subprocess.TimeoutExpired): return None
    _modules[name]={0:False,3:True}.get(done.returncode)
    return _modules[name]


def invokes(command,name):
    return re.search(COMMAND_START+re.escape(name)+r'(?=\s|$|[;&|)])',command) is not None


def imports(command,module):
    """A python3 call in the command that imports the module, inline (`-c`) or as `-m`."""
    if not re.search(r'\bpython3?\b',command): return False
    m=re.escape(module)
    return re.search(rf'\bimport\s+{m}\b|\bfrom\s+{m}\b|\s-m\s+{m}\b',command) is not None


def blocks(spec,tool,data):
    """Whether a tool call would hit this fact's mistake. Only certain cases block: an empty glob, for one,
    depends on the directory's contents at run time, so zsh glob mistakes are never blocked."""
    data=data if isinstance(data,dict) else {}
    kind=spec.get('type')
    command=str(data.get('command','')) if tool=='Bash' else ''
    if kind=='program-missing':
        if spec.get('via')=='read-pdf': return tool=='Read' and str(data.get('file_path','')).lower().endswith('.pdf')
        return bool(command) and invokes(command,spec['name'])
    if kind=='module-missing': return bool(command) and imports(command,spec['name'])
    if kind=='shell-is-zsh' and spec.get('rule')=='zsh-equals-expansion':
        return bool(command) and EQUALS_WORD.search(strip_quoted(command)) is not None
    return False


def strip_quoted(command):
    """Text zsh never equals-expands is ignored when looking for an `=word`: quoted strings, `[[ ... ]]` tests
    and here-document bodies."""
    command=command.split('<<',1)[0]
    command=re.sub(r'\[\[.*?\]\]','',command)
    return re.sub(r"'[^']*'|\"(?:[^\"\\\\]|\\\\.)*\"",'""',command)
