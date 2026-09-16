"""记忆落点闸：受管四文件、读放行/写拦、cwd 相对、fail-closed。

对称 tests/test_playbook_guard.py 的四类：
  ① 路径检查：四个受管文件（含新旧双名）拦，非受管放行
  ② 脚本检查：读放行，各种写姿势拦
  ③ cwd 在 soul/ 下时，相对路径写也拦
  ④ check_path 吞异常 = fail-closed（闸坏了宁可全拦，不许漏放）

注意：本测试全程【只做文本/路径检查，不执行任何写入】；
唯一的真链路写目标是 data/runtime/scratch/ 下的临时文件，
且该场景本来就是"闸全拦"，所以断言的是"文件不存在"。
"""
from __future__ import annotations

from pathlib import Path


def test_check_path_blocks_managed_files():
    from workers.notebook_guard import check_path

    for name in (
        "OWNER-NOTEBOOK.md",    # 画像（当前口径）
        "BRO-NOTEBOOK.md",      # 画像（旧名·兼容）
        "SELF-EVOLUTION.md",
        "OPUS-MEMORIES.md",
    ):
        assert check_path(Path(f"soul/{name}"), "hi") is not None, name
    # 非受管放行
    assert check_path(Path("soul/OTHER.md"), "hi") is None
    assert check_path(Path("data/x.md"), "hi") is None


def test_read_passes_write_blocked():
    from workers.notebook_guard import check_script

    # 读放行（两种姿势）
    assert check_script(
        "print(open('soul/OWNER-NOTEBOOK.md', encoding='utf-8').read())"
    ) is None
    assert check_script("head -5 soul/SELF-EVOLUTION.md") is None
    # 写拦（多姿势）
    assert check_script("Path('soul/SELF-EVOLUTION.md').write_text('hi')")
    assert check_script("shutil.copy('soul/OPUS-MEMORIES.md', 'out.md')")
    assert check_script("echo hi >> soul/OWNER-NOTEBOOK.md")
    assert check_script("os.rename('soul/BRO-NOTEBOOK.md', 'soul/x.md')")


def test_cwd_relative_in_soul():
    from workers.notebook_guard import check_script

    # cwd 在 soul/ 下 → 相对路径写也要拦
    assert check_script("echo hi > OWNER-NOTEBOOK.md", cwd="soul")
    assert check_script("Set-Content OWNER-NOTEBOOK.md hi", cwd="soul")
    # 读放行
    assert check_script(
        "print(open('OWNER-NOTEBOOK.md', encoding='utf-8').read())", cwd="soul"
    ) is None
    # cwd 不在 soul/ 下 → 普通相对文件不拦
    assert check_script("echo hi > foo.md", cwd=".") is None


def test_check_path_fails_closed(monkeypatch):
    from agent_tools.write_file import _run as write_run
    from workers.notebook_guard import check_path

    def boom(*_a, **_k):
        raise RuntimeError("gate down")

    monkeypatch.setattr("workers.notebook_guard.refuse_path", boom)
    # 内部炸了 → 返回错误（含"闸"），而不是放行
    assert "闸" in (check_path(Path("x.txt"), "hi") or "")

    # 真链路：闸坏时 write_file 必须拒绝（fail-closed），且文件不能出现
    scratch = Path("data/runtime/scratch")
    scratch.mkdir(parents=True, exist_ok=True)
    target = scratch / "nb_guard_failclosed.txt"
    if target.exists():
        target.unlink()
    out = write_run({"path": str(target), "content": "hi"})
    assert not out.ok
    assert "闸" in (out.error or "")
    assert not target.exists()
