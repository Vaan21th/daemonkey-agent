"""装修区：缺了才补空默认，有字不覆盖。"""
from pathlib import Path

from workers.user_skin import DEFAULT_CSS, DEFAULT_JS, ensure_user_skin_defaults


def test_creates_missing_files(tmp_path: Path):
    created = ensure_user_skin_defaults(tmp_path)
    assert set(created) == {"user.js", "user.css"}
    js = (tmp_path / "static" / "user" / "user.js").read_text(encoding="utf-8")
    css = (tmp_path / "static" / "user" / "user.css").read_text(encoding="utf-8")
    assert js == DEFAULT_JS
    assert css == DEFAULT_CSS
    assert "addDomain" not in js


def test_does_not_overwrite_existing(tmp_path: Path):
    d = tmp_path / "static" / "user"
    d.mkdir(parents=True)
    (d / "user.js").write_text("/* mine */\n", encoding="utf-8")
    (d / "user.css").write_text("body{color:red}\n", encoding="utf-8")
    created = ensure_user_skin_defaults(tmp_path)
    assert created == []
    assert (d / "user.js").read_text(encoding="utf-8") == "/* mine */\n"
    assert (d / "user.css").read_text(encoding="utf-8") == "body{color:red}\n"


def test_fills_only_the_missing_one(tmp_path: Path):
    d = tmp_path / "static" / "user"
    d.mkdir(parents=True)
    (d / "user.js").write_text("/* keep */\n", encoding="utf-8")
    created = ensure_user_skin_defaults(tmp_path)
    assert created == ["user.css"]
    assert (d / "user.js").read_text(encoding="utf-8") == "/* keep */\n"
    assert (d / "user.css").exists()
