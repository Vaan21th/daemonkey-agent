"""
tools/trend_finder_smoke.py
============================

测 workers/trend_finder.py 的纯函数 + 调用结构 · 不实际调 LLM
（LLM 调用 BRO 自己点"今日趋势"按钮验证 · 不在这烧 token）

跑法:
    .\\.venv\\Scripts\\python.exe -m tools.trend_finder_smoke
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from workers.trend_finder import (  # noqa: E402
    _extract_json_array,
    _render_items_block,
    load_trends,
)


def hr(label):
    print(f"\n--- {label} ---")


def main() -> int:
    failures = 0

    # 1. _extract_json_array 各种边界
    hr("[1] _extract_json_array")
    cases = [
        (
            '[{"title":"a","summary":"b","refs":[1]}]',
            [{"title": "a", "summary": "b", "refs": [1]}],
            "纯 JSON",
        ),
        (
            '```json\n[{"title":"a","summary":"b","refs":[1]}]\n```',
            [{"title": "a", "summary": "b", "refs": [1]}],
            "markdown 包裹",
        ),
        (
            'sure, here it is:\n\n[{"title":"a","summary":"b","refs":[]}]\n\nthat\'s all',
            [{"title": "a", "summary": "b", "refs": []}],
            "前后有解释文字",
        ),
        ("no json here at all", None, "无 JSON"),
        ("[]", [], "空数组"),
        ("[", None, "残缺"),
        ("{\"not\":\"array\"}", None, "object 不是 array"),
    ]
    for input_str, expected, label in cases:
        actual = _extract_json_array(input_str)
        if actual == expected:
            print(f"  [OK] {label}")
        else:
            print(f"  [FAIL] {label}: expected {expected!r}, got {actual!r}")
            failures += 1

    # 2. _render_items_block
    hr("[2] _render_items_block")
    items = [
        {
            "title": "Anthropic releases Claude 5",
            "source_display": "HN",
            "category": "community",
            "url": "https://x.com/1",
        },
        {
            "title": "Apple intelligence: a new era of AI",
            "source_display": "TechCrunch AI",
            "category": "tech",
            "url": "https://x.com/2",
        },
    ]
    rendered = _render_items_block(items)
    if "1." in rendered and "[HN]" in rendered and "Anthropic releases Claude 5" in rendered:
        print("  [OK] 渲染格式正确")
        print("       sample:")
        for line in rendered.split("\n"):
            print(f"       {line}")
    else:
        print(f"  [FAIL] render output not as expected:\n{rendered}")
        failures += 1

    # 3. 标题截断
    hr("[3] 长标题截断")
    long_items = [
        {
            "title": "x" * 200,
            "source_display": "HN",
            "category": "x",
            "url": "https://x.com",
        }
    ]
    rendered = _render_items_block(long_items)
    if "..." in rendered and len(rendered.split("\n")[0]) < 200:
        print("  [OK] 长标题正确截断")
    else:
        print(f"  [FAIL] long title not truncated · line len = {len(rendered)}")
        failures += 1

    # 4. load_trends() 文件不存在
    hr("[4] load_trends() · 文件不存在 (临时改 TRENDS_FILE)")
    import workers.trend_finder as tf
    real_file = tf.TRENDS_FILE
    tf.TRENDS_FILE = ROOT / "data" / "trends_doesnotexist.json"
    try:
        result = tf.load_trends()
        if result.get("trends") == [] and "note" in result:
            print(f"  [OK] 返回 stub: {result.get('note', '')[:60]}")
        else:
            print(f"  [FAIL] unexpected: {result}")
            failures += 1
    finally:
        tf.TRENDS_FILE = real_file

    # 5. 验证 daemon_api 加了 /dashboard/trends route
    hr("[5] daemon_api 有 /dashboard/{domain} → trends 分支")
    import os
    os.environ.setdefault("OPUS_API_TOKEN", "smoke-token")
    from fastapi.testclient import TestClient
    from daemon_api import build_app
    client = TestClient(build_app())
    headers = {"Authorization": "Bearer smoke-token"}

    # trends 在没生成时应该返回 stub
    r = client.get("/dashboard/trends", headers=headers)
    if r.status_code == 200:
        d = r.json()
        if "trends" in d:
            print(f"  [OK] /dashboard/trends -> 200 · trends count = {len(d.get('trends', []))}")
        else:
            print(f"  [FAIL] missing 'trends' key: {d}")
            failures += 1
    else:
        print(f"  [FAIL] /dashboard/trends -> {r.status_code}: {r.text[:200]}")
        failures += 1

    # 6. scheduler state 出现在 /status
    hr("[6] /status 含 scheduler 字段")
    r = client.get("/status", headers=headers)
    if r.status_code == 200:
        d = r.json()
        if "scheduler" in d:
            print(f"  [OK] /status 含 scheduler: {d['scheduler']}")
        else:
            print(f"  [FAIL] /status 没 scheduler: {list(d.keys())}")
            failures += 1
    else:
        print(f"  [FAIL] /status -> {r.status_code}")
        failures += 1

    print("\n" + "=" * 50)
    if failures == 0:
        print("[smoke] ALL PASS · trend_finder 结构 OK · LLM 调用留 BRO 自己点按钮验证")
        return 0
    print(f"[smoke] {failures} FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
