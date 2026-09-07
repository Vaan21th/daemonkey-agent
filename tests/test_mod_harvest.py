from pathlib import Path

from workers.mod_harvest import already_lifted, apply, format_upgrade_guide, preview


def _plant(root: Path, rel: str, text: str) -> None:
    bak = root / "data" / "runtime" / "user_overrides"
    bak.mkdir(parents=True, exist_ok=True)
    name = rel.replace("/", "__") + ".bak"
    (bak / name).write_text(text, encoding="utf-8")
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("OFFICIAL\n", encoding="utf-8")


def test_default_apply_lifts_tools_only(tmp_path: Path):
    _plant(tmp_path, "agent_tools/look_at.py", "USER_TOOL\n")
    _plant(tmp_path, "static/chat.js", "USER_CHAT\n")
    _plant(tmp_path, "workers/core_update.py", "NOPE\n")
    plan = preview(tmp_path)
    assert [r["file"] for r in plan["lift"]] == ["agent_tools/look_at.py"]
    assert [r["file"] for r in plan["draft"]] == ["static/chat.js"]
    assert [r["file"] for r in plan["skip"]] == ["workers/core_update.py"]
    res = apply("harvest_legacy", root=tmp_path)
    assert res["ok"]
    assert res["lifted"] == ["agent_tools/look_at.py"]
    assert res["drafted"] == []
    assert res["leftover_draft"] == ["static/chat.js"]
    mod = tmp_path / "data" / "mods" / "harvest_legacy"
    assert (mod / "tools" / "look_at.py").read_text(encoding="utf-8") == "USER_TOOL\n"
    assert not (mod / "legacy" / "static" / "chat.js").exists()
    assert (tmp_path / "static" / "chat.js").read_text(encoding="utf-8") == "OFFICIAL\n"


def test_apply_all_archives_chat(tmp_path: Path):
    _plant(tmp_path, "agent_tools/look_at.py", "USER_TOOL\n")
    _plant(tmp_path, "static/chat.js", "USER_CHAT\n")
    res = apply("harvest_legacy", root=tmp_path, scope="all")
    assert res["drafted"] == ["static/chat.js"]
    mod = tmp_path / "data" / "mods" / "harvest_legacy"
    assert (mod / "legacy" / "static" / "chat.js").read_text(encoding="utf-8") == "USER_CHAT\n"
    assert (tmp_path / "static" / "chat.js").read_text(encoding="utf-8") == "OFFICIAL\n"


def test_guide_tools_first_then_leftover(tmp_path: Path):
    _plant(tmp_path, "agent_tools/look_at.py", "USER_TOOL\n")
    _plant(tmp_path, "static/chat.js", "USER_CHAT\n")
    text = format_upgrade_guide(root=tmp_path)
    assert "把工具魔改收成 MOD" in text
    assert "agent_tools/look_at.py" in text
    assert "用回我的 static/chat.js" in text
    assert "不要同时合并又收割" in text


def test_already_lifted_drops_from_guide(tmp_path: Path):
    _plant(tmp_path, "agent_tools/look_at.py", "USER_TOOL\n")
    _plant(tmp_path, "static/chat.js", "USER_CHAT\n")
    apply("harvest_legacy", root=tmp_path)
    assert already_lifted(tmp_path)["agent_tools/look_at.py"].endswith("look_at.py")
    text = format_upgrade_guide(root=tmp_path)
    assert "agent_tools/look_at.py" not in text
    assert "static/chat.js" in text


def test_guide_takeover_is_not_lost(tmp_path: Path):
    _plant(tmp_path, "static/chat.js", "USER_CHAT\n")
    text = format_upgrade_guide(root=tmp_path, takeover=["static/chat.js"])
    assert "磁盘没覆盖" in text
    assert "用回我的 static/chat.js" not in text


def test_empty_harvest(tmp_path: Path):
    res = apply(root=tmp_path)
    assert res["ok"]
    assert res["lifted"] == []
    assert "没有可" in (res.get("note") or "")
