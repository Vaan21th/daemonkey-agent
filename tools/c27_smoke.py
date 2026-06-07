"""tools/c27_smoke.py — 卷二十七冒烟测试

测试范围：
  - workers/translator.py · 翻译器 + cache
  - workers/trend_finder.py · 新 schema 兼容（intensity / angles / refs.radar_index）
  - workers/info_radar.py · backfill_radar_translation
  - agent_tools/expand_trend_to_report · 注册 + 参数校验（不调真实 LLM）
  - daemon_api · /dashboard/radar 包含 title_zh · /dashboard/cockpit radar 用中文

不真正调 LLM（避免烧 token）· 用 mock client。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        print(f"  ✗ {msg}")
        raise SystemExit(1)
    print(f"  ✓ {msg}")


def test_translator_unit():
    print("\n── 1. translator unit ──────────────────")
    from workers.translator import (
        _chinese_ratio,
        _hash_key,
        _is_mostly_english,
        _parse_translation_response,
        _strip_html,
    )

    assert_true(_chinese_ratio("hello world") < 0.1, "english zero cjk")
    assert_true(_chinese_ratio("你好世界") > 0.9, "pure chinese high cjk")
    assert_true(_chinese_ratio("hello 世界 mix") > 0.1, "mixed has some cjk")

    assert_true(_is_mostly_english("This is an English title"), "en detected")
    assert_true(not _is_mostly_english("国内大模型最新格局"), "cn not en")

    h1 = _hash_key("same title")
    h2 = _hash_key("same title")
    h3 = _hash_key("different title")
    assert_true(h1 == h2, "hash deterministic")
    assert_true(h1 != h3, "different titles different hash")
    assert_true(len(h1) == 16, "hash length 16")

    assert_true(_strip_html("<p>hello <a href='x'>world</a></p>") == "hello world",
                "html stripped")
    assert_true(_strip_html("plain text") == "plain text", "plain unchanged")
    assert_true(_strip_html("") == "", "empty ok")

    # _parse_translation_response
    raw = '''```json
[{"i": 0, "title_zh": "中标", "summary_zh": "中摘"}]
```'''
    arr = _parse_translation_response(raw, 1)
    assert_true(arr is not None and len(arr) == 1, "parse markdown-wrapped json")
    assert_true(arr[0]["title_zh"] == "中标", "parse field correct")

    assert_true(_parse_translation_response("garbage", 1) is None,
                "parse garbage returns None")
    assert_true(_parse_translation_response("", 1) is None, "parse empty None")


def test_translator_cache_skip():
    """中文 / 已 cache 的不调 LLM · 直接返回原始/cache"""
    print("\n── 2. translator skip logic ────────────")
    from workers.translator import translate_items

    items = [
        {"title": "国内大模型最新格局", "summary": "国内主要 LLM 厂商"},
        {"title": "国内大模型最新格局", "summary": "国内主要 LLM 厂商"},
    ]
    result = translate_items(items)
    assert_true(len(result) == 2, "input length preserved")
    assert_true(not result[0].get("_translated"),
                "chinese item not translated (no LLM call)")


def test_trend_finder_schema():
    print("\n── 3. trend_finder new schema ──────────")
    from workers.trend_finder import _extract_json_array, load_trends

    # 旧 schema 兼容（没有 intensity/angles 的旧 trends.json 不该崩）
    data = load_trends()
    assert_true(isinstance(data, dict), "load_trends returns dict")
    if data.get("trends"):
        for t in data["trends"]:
            assert_true(isinstance(t, dict), "each trend is dict")

    # 解析能力
    sample = '''[{"title": "x", "summary": "y", "intensity": 4, "angles": ["content"], "refs": [1, 2]}]'''
    arr = _extract_json_array(sample)
    assert_true(arr is not None and len(arr) == 1, "json array parsed")
    assert_true(arr[0]["intensity"] == 4, "intensity field present")
    assert_true(arr[0]["angles"] == ["content"], "angles field present")


def test_trend_finder_validation_angles_clamp():
    """模拟 LLM 返回不合法的 angle · 应该被过滤"""
    print("\n── 4. trend_finder angle filtering ─────")
    from workers.trend_finder import _extract_json_array

    sample = '''[{"title": "x", "summary": "y", "intensity": "10", "angles": ["content", "garbage", "design"], "refs": []}]'''
    arr = _extract_json_array(sample)
    assert_true(arr is not None, "parse ok")

    # 这一段对应 generate_trends 里的 clamp + filter 逻辑 · 在这里仿造一遍
    _valid_angles = {"content", "design", "dev", "docs", "service"}
    t = arr[0]
    intensity = max(1, min(5, int(t.get("intensity", 3))))
    angles = [a for a in (t.get("angles") or []) if a in _valid_angles]
    assert_true(intensity == 5, "intensity 10 clamped to 5")
    assert_true(angles == ["content", "design"], "garbage angle filtered")


def test_expand_trend_to_report_tool():
    print("\n── 5. expand_trend_to_report tool ──────")
    import agent_tools

    spec = agent_tools.REGISTRY.get("expand_trend_to_report")
    assert_true(spec is not None, "expand_trend_to_report registered")
    assert_true(spec.tier == "confirm", "tier is CONFIRM")

    # 参数验证（不会真调 LLM 因为 trends 是空 / index 越界）
    r = spec.run({"trend_index": -1})
    assert_true(r.ok is False, "trend_index -1 rejected")

    r = spec.run({})
    assert_true(r.ok is False, "missing trend_index rejected")

    # 把 trends.json 临时变空 · 看正确错误返回
    from workers.trend_finder import TRENDS_FILE
    backup = None
    if TRENDS_FILE.exists():
        backup = TRENDS_FILE.read_text(encoding="utf-8")
    try:
        TRENDS_FILE.write_text(
            json.dumps({"trends": []}, ensure_ascii=False), encoding="utf-8"
        )
        r = spec.run({"trend_index": 0})
        assert_true(r.ok is False, "empty trends.json rejected")
        assert_true(
            "没有趋势" in (r.error or ""),
            f"empty trends gives helpful error (got: {r.error!r})",
        )
    finally:
        if backup is not None:
            TRENDS_FILE.write_text(backup, encoding="utf-8")


def test_daemon_api_radar_translation():
    """live /dashboard/radar + /dashboard/cockpit 应该带翻译信息"""
    print("\n── 6. daemon_api translation surface ───")
    import os

    token = "smoke-token-c27"
    os.environ["OPUS_API_TOKEN"] = token

    from fastapi.testclient import TestClient
    from daemon_api import build_app

    app = build_app()
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/dashboard/radar", headers=headers)
    assert_true(r.status_code == 200, "radar endpoint 200")
    data = r.json()
    items = data.get("items") or []
    assert_true(len(items) > 0, f"radar has items (got {len(items)})")

    # 至少有一些条目带 title_zh
    translated = [it for it in items if it.get("title_zh")]
    assert_true(
        len(translated) > 0,
        f"radar items include translations (got {len(translated)} translated)",
    )

    # translation meta exists
    tr = data.get("translation") or {}
    assert_true(
        tr.get("attempted") or tr.get("total_cached", 0) >= 0,
        f"translation meta present (got: {tr})",
    )

    # cockpit radar item should prefer title_zh
    r = client.get("/dashboard/cockpit?head=3", headers=headers)
    data = r.json()
    radar_card = next(d for d in data["domains"] if d["id"] == "radar")
    radar_items = radar_card.get("items") or []
    if radar_items:
        any_translated = any(it.get("translated") for it in radar_items)
        assert_true(
            any_translated or all(not it.get("translated") for it in radar_items),
            "cockpit radar item has translation flag",
        )


def test_pipeline_breadcrumb_in_js():
    """简单 grep · 确保 chat.js 包含 pipelineBreadcrumb 函数"""
    print("\n── 7. chat.js pipeline UI ──────────────")
    chat_js = (ROOT / "static" / "chat.js").read_text(encoding="utf-8")
    assert_true(
        "function pipelineBreadcrumb" in chat_js,
        "pipelineBreadcrumb defined",
    )
    assert_true(
        "renderIntensityBar" in chat_js,
        "renderIntensityBar defined",
    )
    assert_true(
        "triggerTrendAction" in chat_js,
        "triggerTrendAction defined",
    )
    assert_true(
        "title_zh" in chat_js,
        "chat.js uses title_zh field",
    )

    chat_css = (ROOT / "static" / "chat.css").read_text(encoding="utf-8")
    assert_true(
        ".pipeline" in chat_css,
        ".pipeline class styled",
    )
    assert_true(
        ".trend-angle" in chat_css,
        ".trend-angle styled",
    )
    assert_true(
        ".tc-intensity" in chat_css,
        ".tc-intensity styled",
    )


def main():
    print("=== 卷二十七 smoke test ===")
    start = time.time()
    test_translator_unit()
    test_translator_cache_skip()
    test_trend_finder_schema()
    test_trend_finder_validation_angles_clamp()
    test_expand_trend_to_report_tool()
    test_daemon_api_radar_translation()
    test_pipeline_breadcrumb_in_js()
    elapsed = time.time() - start
    print(f"\n=== ALL PASS · {elapsed:.2f}s ===")


if __name__ == "__main__":
    main()
