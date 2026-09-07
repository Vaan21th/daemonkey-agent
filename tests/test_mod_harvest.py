from pathlib import Path

from workers.mod_harvest import apply, preview


def _plant(root: Path, rel: str, text: str) -> None:
    bak = root / "data" / "runtime" / "user_overrides"
    bak.mkdir(parents=True, exist_ok=True)
    name = rel.replace("/", "__") + ".bak"
    (bak / name).write_text(text, encoding="utf-8")
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("OFFICIAL\n", encoding="utf-8")


def test_lifts_tool_and_drafts_chat(tmp_path: Path):
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
    assert res["drafted"] == ["static/chat.js"]
    mod = tmp_path / "data" / "mods" / "harvest_legacy"
    assert (mod / "tools" / "look_at.py").read_text(encoding="utf-8") == "USER_TOOL\n"
    assert (mod / "legacy" / "static" / "chat.js").read_text(encoding="utf-8") == "USER_CHAT\n"
    assert (mod / "mod.json").is_file()
    assert (tmp_path / "static" / "chat.js").read_text(encoding="utf-8") == "OFFICIAL\n"


def test_empty_harvest(tmp_path: Path):
    res = apply(root=tmp_path)
    assert res["ok"]
    assert res["lifted"] == []
    assert "没有可收" in (res.get("note") or "")
