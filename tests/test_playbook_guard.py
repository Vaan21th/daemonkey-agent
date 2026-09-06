"""手册落点闸：吞异常、cwd 相对写、shutil/rename。"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def pb_home(tmp_path, monkeypatch):
    home = tmp_path / "playbooks"
    home.mkdir()
    monkeypatch.setattr("workers.playbooks.PLAYBOOK_DIR", home)
    monkeypatch.setattr("workers.playbooks.INDEX_PATH", home / "_index.json")
    monkeypatch.setattr("workers.memory_index.incremental_update", lambda *a, **k: None)
    return home


def test_refuse_script_blocks_shutil_and_rename():
    from workers.playbook_guard import refuse_script
    assert refuse_script("print(open('data/playbooks/x.md', encoding='utf-8').read())") is None
    assert refuse_script("shutil.copy('data/playbooks/a.md', 'out.md')")
    assert refuse_script("os.rename('data/playbooks/a.md', 'data/playbooks/b.md')")
    assert refuse_script("Path('data/playbooks/x.md').write_text('hi')")


def test_refuse_script_cwd_relative(pb_home: Path):
    from workers.playbook_guard import refuse_script
    assert refuse_script("echo hi > foo.md", cwd=pb_home)
    assert refuse_script("Path('foo.md').write_text('hi')", cwd=pb_home)
    assert refuse_script("print(open('foo.md', encoding='utf-8').read())", cwd=pb_home) is None
    assert refuse_script("echo hi > foo.md", cwd=".") is None


def test_check_path_fails_closed(monkeypatch):
    from agent_tools.write_file import _run as write_run
    from workers.playbook_guard import check_path
    from workers.playbooks import ROOT

    def boom(*_a, **_k):
        raise RuntimeError("gate down")

    monkeypatch.setattr("workers.playbook_guard.refuse_path", boom)
    assert "闸" in (check_path(Path("x.txt"), "hi") or "")
    scratch = ROOT / "data" / "runtime" / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    target = scratch / "guard_failclosed.txt"
    if target.exists():
        target.unlink()
    out = write_run({"path": str(target), "content": "hi"})
    assert not out.ok
    assert "闸" in (out.error or "")
    assert not target.exists()
