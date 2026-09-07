"""初见进工作台不能现场翻插件说明 · 否则卡住 event loop。"""
from workers import plugins_index as pi


def test_translate_cache_only_does_not_call_llm(monkeypatch):
    def boom():
        raise AssertionError("request path must not start translator")

    monkeypatch.setattr(pi, "_get_translator", boom)
    monkeypatch.setattr(pi, "_load_translation_cache", lambda: {"version": 1, "entries": {}})
    out = pi._translate_descriptions([("web_search", "Search the web.")], live=False)
    assert out == {}


def test_load_plugins_returns_without_live_translate():
    data = pi.load_plugins()
    assert isinstance(data, dict)
    assert data.get("total", 0) >= 1
    assert isinstance(data.get("items"), list)
