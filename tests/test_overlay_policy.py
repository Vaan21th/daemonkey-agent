from pathlib import Path

from product_constitution import build_constitution_block
from workers.overlay_policy import (
    constitution_extra,
    is_mother,
    publish_block,
    write_notice,
)


def test_mother_mark_matches_gate_script():
    from workers.mod_runtime import ROOT
    assert is_mother() is (ROOT / "tools" / "check_dk_release.ps1").is_file()


def test_write_notice_skips_mother_and_overlay(tmp_path: Path):
    assert write_notice("agent_tools/write_file.py", mother=True) == ""
    assert write_notice("data/mods/hud/tools/a.py", mother=False, root=tmp_path) == ""
    assert write_notice("agent_tools/write_file.py", mother=False).startswith("这一层是官方文件")


def test_constitution_only_on_clean(tmp_path: Path):
    assert constitution_extra(mother=True) == ""
    extra = constitution_extra(mother=False)
    assert "优先叠层" in extra
    (tmp_path / "CONSTITUTION.md").write_text("", encoding="utf-8")
    block = build_constitution_block(tmp_path)
    if is_mother():
        assert "改装纪律" not in block
    else:
        assert "优先叠层" in block


def test_publish_block_two_ends():
    assert publish_block(mother=True, plan={"lift": [{"file": "agent_tools/x.py"}]}) == ""
    assert publish_block(mother=False, plan={"lift": [], "draft": []}) == ""
    lift = publish_block(mother=False, plan={"lift": [{"file": "agent_tools/x.py"}], "draft": []})
    assert "把工具魔改收成 MOD" in lift
    assert "agent_tools/x.py" in lift
    draft = publish_block(
        mother=False,
        plan={"lift": [], "draft": [{"file": "static/clients.js"}]},
    )
    assert "上架" in draft
    assert "clients.js" in draft
