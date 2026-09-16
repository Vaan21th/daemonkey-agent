"""同题产物：只留最新、旧的进历史、页脚不带产品名。"""
from __future__ import annotations

from pathlib import Path

from slides_engine.styles import STYLES
from workers.output_versions import (
    archive_family,
    family_key,
    is_hidden_output,
    publish,
    staged_path,
)


def test_family_key_strips_clock():
    assert family_key("提案__20260901-045323.pptx") == "提案"
    assert family_key("提案__20260901-045323-2.pptx") == "提案"
    assert family_key("提案.pptx") == "提案"
    assert family_key("_hist_提案_v2_20260901-0408.pptx") == "提案"


def test_hidden_output_names():
    assert is_hidden_output("_hist_提案_v1_x.pptx")
    assert is_hidden_output(".__wip__提案.pptx")
    assert is_hidden_output("~$lock.pptx")
    assert not is_hidden_output("提案.pptx")


def test_publish_archives_previous(tmp_path: Path):
    folder = tmp_path / "decks"
    folder.mkdir()
    cur = folder / "提案.pptx"
    cur.write_text("old", encoding="utf-8")
    (folder / "提案.md").write_text("old-md", encoding="utf-8")
    older = folder / "提案__20260901-0408.pptx"
    older.write_text("older", encoding="utf-8")
    wip = staged_path(folder, "提案", ".pptx")
    wip.write_text("new", encoding="utf-8")
    dest, ver = publish(wip, folder, "提案", ".pptx")
    assert dest.name == "提案.pptx"
    assert dest.read_text(encoding="utf-8") == "new"
    assert not older.exists()
    assert ver >= 2
    hists = list(folder.glob("_hist_提案_v*"))
    assert len(hists) >= 2


def test_archive_keeps_source_until_publish(tmp_path: Path):
    folder = tmp_path / "decks"
    folder.mkdir()
    src = folder / "提案__20260901-045323.pptx"
    src.write_text("src", encoding="utf-8")
    wip = staged_path(folder, "提案", ".pptx")
    wip.write_text("patched", encoding="utf-8")
    dest, ver = publish(wip, folder, "提案", ".pptx", keep=src)
    assert dest.read_text(encoding="utf-8") == "patched"
    assert not src.exists()
    assert ver >= 2
    assert any(p.name.startswith("_hist_提案") for p in folder.iterdir())


def test_style_footer_has_no_product_name():
    for s in STYLES.values():
        assert "Daemonkey" not in (s.footer or "")
        assert "OPUS" not in (s.footer or "")
        assert "工作室" not in (s.footer or "")
