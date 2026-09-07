import io
import json
import zipfile

from workers.market_review import review_index_patch, review_pkg


def _pkg(kind, name, body=None, files=None, desc="hello"):
    buf = io.BytesIO()
    manifest = {
        "dkpkg_version": 1, "kind": kind, "name": name,
        "version": "1.0.0", "description": desc, "author": "t",
    }
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        if kind == "skin":
            z.writestr("skin.json", json.dumps({"name": name}))
            z.writestr("style.css", "body{}\n")
            for arc, data in (files or []):
                z.writestr(arc, data)
        else:
            src = "app.json" if kind == "app" else "flow.json"
            z.writestr(src, json.dumps(body or {"id": name}))
    return buf.getvalue()


def test_empty_tools_is_red():
    raw = _pkg("app", "app-x", {"id": "app-x", "tools": []})
    got = review_pkg(raw, author="alice", known_authors=["bob"])
    assert got["verdict"] == "reject"
    assert any("空名单" in x or "工具名单" in x for x in got["red"])


def test_shell_tool_is_red():
    raw = _pkg("app", "app-x", {"id": "app-x", "tools": ["shell_exec", "list_apps"]})
    got = review_pkg(raw)
    assert got["verdict"] == "reject"
    assert any("shell_exec" in x for x in got["red"])


def test_safe_app_first_author_is_yellow():
    raw = _pkg("app", "app-x", {"id": "app-x", "tools": ["list_apps"]})
    got = review_pkg(raw, author="alice", known_authors=["bob"])
    assert got["verdict"] == "review"
    assert any("第一次" in x for x in got["yellow"])


def test_mod_with_js_is_reviewable():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps({
            "dkpkg_version": 1, "kind": "mod", "name": "hud",
            "id": "hud", "version": "1.0.0", "description": "用量",
        }))
        z.writestr("mod.json", json.dumps({"id": "hud", "name": "用量"}))
        z.writestr("ui/mod.js", "console.log(1)\n")
    got = review_pkg(buf.getvalue(), author="bob", known_authors=["bob"])
    assert got["verdict"] in ("pass", "review")
    assert got["meta"]["kind"] == "mod"


def test_safe_skin_known_author_is_green():
    raw = _pkg("skin", "nice-skin", desc="干净皮肤")
    got = review_pkg(raw, author="bob", known_authors=["bob"])
    assert got["verdict"] == "pass"


def test_skin_js_is_red():
    raw = _pkg("skin", "evil", files=[("hook.js", "alert(1)")], desc="x")
    got = review_pkg(raw, author="bob", known_authors=["bob"])
    assert got["verdict"] == "reject"


def test_scripted_localhost_is_red():
    raw = _pkg("app", "app-x", {
        "id": "app-x", "tools": ["list_apps"], "exec_kind": "scripted",
        "exec_template": {"routes": [{"url": "http://127.0.0.1/secret"}]},
    })
    got = review_pkg(raw, author="bob", known_authors=["bob"])
    assert got["verdict"] == "reject"


def test_index_must_add_exactly_one():
    old = [{"id": "a", "file": "https://gitee.com/o/r/raw/master/packages/a.dkpkg"}]
    new = old + [
        {"id": "b", "file": "https://gitee.com/o/r/raw/master/packages/b.dkpkg"},
        {"id": "c", "file": "https://gitee.com/o/r/raw/master/packages/c.dkpkg"},
    ]
    assert review_index_patch(old, new)["red"]
    good = old + [{"id": "b", "file": "https://gitee.com/o/r/raw/master/packages/b.dkpkg"}]
    assert not review_index_patch(old, good)["red"]
    hijack = [{"id": "a", "file": "https://evil.example/x.dkpkg"}]
    assert review_index_patch(old, hijack)["red"]
