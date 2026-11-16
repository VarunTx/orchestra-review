"""Every test runs against empty temporary homes, so no test can read real logs or touch real instruction files."""
import pytest


@pytest.fixture(autouse=True)
def private_homes(tmp_path_factory,monkeypatch):
    base=tmp_path_factory.mktemp('homes')
    for name in ('ORCHESTRA_REVIEW_HOME','CLAUDE_CONFIG_DIR','XDG_CONFIG_HOME','CODEX_HOME'):
        monkeypatch.setenv(name,str(base/name.lower()))
