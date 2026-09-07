from pathlib import Path

from workers.mod_health import disable, format_report, inspect
from workers.mod_runtime import list_mods


def _mod(root: Path, mid: str, *, tool: str, enabled: bool = True) -> None:
    folder = root / "data" / "mods" / mid
    (folder / "tools").mkdir(parents=True)
    (folder / "mod.json").write_text(
        f'{{"id":"{mid}","name":"{mid}","version":"1.0.0","enabled":{str(enabled).lower()}}}\n',
        encoding="utf-8",
    )
    (folder / "tools" / "look_at.py").write_text(tool, encoding="utf-8")


def test_inspect_flags_bad_syntax(tmp_path: Path):
    _mod(tmp_path, "ok_mod", tool="x = 1\n")
    _mod(tmp_path, "bad_mod", tool="def broken(\n")
    rep = inspect(tmp_path)
    by_id = {m["id"]: m for m in rep["mods"]}
    assert by_id["ok_mod"]["ok"] is True
    assert by_id["bad_mod"]["ok"] is False
    assert any("SyntaxError" in p for p in by_id["bad_mod"]["problems"])
    text = format_report(rep)
    assert "停用 MOD bad_mod" in text
    assert "ok_mod" in text


def test_disable_stops_loading(tmp_path: Path):
    _mod(tmp_path, "hud", tool="x = 1\n")
    ok, msg = disable("hud", root=tmp_path)
    assert ok, msg
    rows = list_mods(tmp_path)
    assert rows[0]["enabled"] is False
    assert rows[0]["id"] == "hud"


def test_user_tool_syntax(tmp_path: Path):
    ud = tmp_path / "agent_tools_user"
    ud.mkdir(parents=True)
    (ud / "boom.py").write_text("def (\n", encoding="utf-8")
    (ud / "README.md").write_text("x", encoding="utf-8")
    rep = inspect(tmp_path)
    assert rep["user_tools"]
    assert "boom.py" in rep["user_tools"][0]["file"]
    assert "官方同名工具会露出来" in format_report(rep)


def test_quiet_when_empty(tmp_path: Path):
    assert format_report(inspect(tmp_path)) == ""


def test_inspect_and_save_persists_alert(tmp_path: Path):
    from workers.mod_health import inspect_and_save, load_saved
    _mod(tmp_path, "bad_mod", tool="def broken(\n")
    inspect_and_save(tmp_path)
    saved = load_saved(tmp_path)
    assert saved["alert"] == 1
    assert saved["checked_at"]
    assert saved["mods"][0]["id"] == "bad_mod"
