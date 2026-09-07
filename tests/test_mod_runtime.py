import json
import zipfile
from pathlib import Path

from workers.mod_pack_io import export_zip, import_zip, safe_members
from workers.mod_runtime import ensure_overlay_dirs, list_mods, sanitize_id

_ROOT = Path(__file__).resolve().parent.parent


def test_run_api_only_loads_tool_overlays():
    text = (_ROOT / "tools" / "run_api_only.py").read_text(encoding="utf-8")
    i_app = text.index("app = build_app()")
    i_load = text.index("load_tool_overlays()")
    assert i_app < i_load
    assert text.index("try_auto_revert") < i_load
    assert "叠层工具跳过" in text


def test_sanitize_and_ensure(tmp_path: Path):
    assert sanitize_id("Token HUD!") == "Token_HUD"
    created = ensure_overlay_dirs(tmp_path)
    assert any(p.endswith("data/mods/README.md") for p in created)
    assert (tmp_path / "agent_tools_user" / "README.md").is_file()
    again = ensure_overlay_dirs(tmp_path)
    assert again == []


def test_export_import_roundtrip(tmp_path: Path):
    mid = "token_hud"
    folder = tmp_path / "data" / "mods" / mid
    (folder / "ui").mkdir(parents=True)
    (folder / "mod.json").write_text(json.dumps({
        "id": mid, "name": "用量条", "version": "1.0.0", "enabled": True,
    }), encoding="utf-8")
    (folder / "ui" / "mod.js").write_text("console.log('hud');\n", encoding="utf-8")
    dest, err = export_zip(mid, root=tmp_path)
    assert err == "" and dest is not None and dest.exists()
    dest.rename(tmp_path / "pkg.dkpkg")
    # 再装到另一棵树
    other = tmp_path / "other"
    ok, msg = import_zip(tmp_path / "pkg.dkpkg", root=other)
    assert ok, msg
    assert (other / "data" / "mods" / mid / "ui" / "mod.js").is_file()
    rows = list_mods(other)
    assert rows and rows[0]["id"] == mid
    assert rows[0]["js"].endswith("/mod.js")


def test_safe_members_rejects_exe(tmp_path: Path):
    zpath = tmp_path / "bad.dkpkg"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("manifest.json", '{"kind":"mod","name":"x"}')
        z.writestr("tools/evil.exe", b"mz")
    with zipfile.ZipFile(zpath) as z:
        try:
            safe_members(z)
            assert False, "should reject exe"
        except ValueError as e:
            assert "可执行" in str(e)
