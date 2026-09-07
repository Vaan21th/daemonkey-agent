from pathlib import Path

from workers.mod_health import inspect_and_save, load_saved
from workers.overlay_board import inventory


def _mod(root: Path, mid: str, tool: str, enabled: bool = True, author: str = "") -> None:
    folder = root / "data" / "mods" / mid
    (folder / "tools").mkdir(parents=True)
    (folder / "mod.json").write_text(
        f'{{"id":"{mid}","name":"{mid}","author":"{author}","version":"1.0.0","enabled":{str(enabled).lower()}}}\n',
        encoding="utf-8",
    )
    (folder / "tools" / "look_at.py").write_text(tool, encoding="utf-8")


def test_inventory_refresh_flags_and_persists(tmp_path: Path):
    _mod(tmp_path, "ok_mod", "x = 1\n", author="我自己")
    _mod(tmp_path, "bad_mod", "def broken(\n", author="邻座")
    skin = tmp_path / "static" / "user" / "skins" / "paper"
    skin.mkdir(parents=True)
    (skin / "skin.json").write_text('{"name":"纸色","version":"1.0.0"}', encoding="utf-8")
    ud = tmp_path / "agent_tools_user"
    ud.mkdir()
    (ud / "mine.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "static" / "user").mkdir(parents=True, exist_ok=True)
    (tmp_path / "static" / "user" / "user.js").write_text("/* x */\n", encoding="utf-8")

    board = inventory(refresh=True, root=tmp_path)
    by_id = {m["id"]: m for m in board["mods"]}
    assert by_id["ok_mod"]["ok"] is True
    assert by_id["ok_mod"]["author"] == "我自己"
    assert by_id["bad_mod"]["ok"] is False
    assert by_id["bad_mod"]["author"] == "邻座"
    assert by_id["bad_mod"]["enabled"] is True
    assert board["health"]["alert"] == 1
    assert board["skins"][0]["id"] == "paper"
    assert board["user_tools"][0]["file"].endswith("mine.py")
    assert board["decorate"]["user_js"] is True
    saved = load_saved(tmp_path)
    assert saved["alert"] == 1
    again = inventory(refresh=False, root=tmp_path)
    assert again["health"]["alert"] == 1


def test_saved_health_without_refresh(tmp_path: Path):
    _mod(tmp_path, "hud", "x = 1\n")
    inspect_and_save(tmp_path)
    board = inventory(refresh=False, root=tmp_path)
    assert board["mods"][0]["id"] == "hud"
    assert board["health"]["checked_at"]


def test_market_js_has_overlay_tab():
    text = Path(__file__).resolve().parent.parent.joinpath(
        "static", "market.js").read_text(encoding="utf-8")
    assert 'data-hub="overlays"' in text
    assert "我的改装" in text
    assert 'mod: "MOD"' in text
    assert "/api/overlays?refresh=1" in text
    assert "paintPluginAlert" in text
    assert "作者 " in text
