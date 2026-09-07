from workers.fork_depth import D0, D2, D3, classify_file, is_overlay_path, measure_text


def test_overlay_paths():
    assert is_overlay_path("data/mods/token-hud/tools/a.py")
    assert is_overlay_path("agent_tools_user/foo.py")
    assert is_overlay_path("static/user/user.js")
    assert not is_overlay_path("static/user/EXAMPLES.js")
    assert not is_overlay_path("static/chat.js")


def test_shallow_is_d2():
    official = "\n".join(f"line{i}" for i in range(20))
    user = official.replace("line3", "line3-mod")
    item = classify_file("static/depot.js", official_text=official, user_text=user)
    assert item["depth"] == D2
    assert item["changed"] >= 1


def test_deep_is_d3():
    official = "\n".join(f"line{i}" for i in range(100))
    user = "\n".join(f"new{i}" for i in range(100))
    item = classify_file("static/chat.js", official_text=official, user_text=user)
    assert item["depth"] == D3


def test_takeover_is_d3():
    item = classify_file("static/chat.js", takeover=True)
    assert item["depth"] == D3


def test_mod_dir_is_d0():
    item = classify_file("data/mods/hud/ui/mod.js")
    assert item["depth"] == D0


def test_measure_hunks():
    changed, hunks = measure_text("a\nb\nc\n", "a\nB\nc\n")
    assert changed == 1
    assert hunks == 1
