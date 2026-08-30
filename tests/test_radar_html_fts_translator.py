"""翻译通道跟主模型、html 雷达源、FTS5 方括号。"""

from __future__ import annotations

from workers.info_radar import SOURCE_HANDLERS, _parse_html
from workers.memory_index import _tokenize_for_query
from workers.translator import _translator_endpoint


def test_translator_follows_active_provider(monkeypatch):
    monkeypatch.delenv("OPUS_TRANSLATOR_MODEL", raising=False)
    monkeypatch.setenv("OPUS_BASE_URL", "https://old.example/v1")
    monkeypatch.setenv("OPUS_API_KEY", "old-key")

    def _cfg(include_key=True):
        return {
            "base_url": "https://api.example/v1",
            "api_key": "sk-x",
            "model": "deepseek-ai/DeepSeek-V4-Flash",
        }

    monkeypatch.setattr(
        "workers.provider_configs.get_active_config", _cfg
    )
    url, key, model = _translator_endpoint()
    assert model == "deepseek-ai/DeepSeek-V4-Flash"
    assert url == "https://api.example/v1"
    assert key == "sk-x"


def test_translator_env_model_wins(monkeypatch):
    monkeypatch.setenv("OPUS_TRANSLATOR_MODEL", "qwen-turbo")
    monkeypatch.setenv("OPUS_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("OPUS_API_KEY", "env-key")
    url, key, model = _translator_endpoint()
    assert model == "qwen-turbo"
    assert url == "https://env.example/v1"


def test_html_source_is_registered():
    assert "html" in SOURCE_HANDLERS


def test_parse_html_extracts_links():
    html = """<html><body>
    <a href="https://example.com/post-one">A decent article title</a>
    <a href="https://example.com/post-two">Another readable headline</a>
    <a href="/short">x</a>
    </body></html>"""
    items = _parse_html(html, {
        "id": "demo",
        "display": "Demo",
        "url": "https://example.com/",
        "max_items": 10,
        "category": "tech",
        "domain": "ai",
    })
    assert len(items) == 2
    assert items[0].url.endswith("/post-one")
    assert "decent" in items[0].title.lower()


def test_fts_brackets_do_not_reach_match():
    q = _tokenize_for_query("[ERROR] translator failed near [opus]")
    assert "[" not in q
    assert "]" not in q
    assert q.strip()
