"""
tools/dashboard_smoke.py
========================

卷二十一 Day 1 · /dashboard/{domain} 端到端 smoke

不起 server · 用 starlette TestClient 直接调 FastAPI · 验证：
  - /dashboard/radar 能读到现有 data/radar.json 数据
  - /dashboard/content 等 stub 返回正确结构
  - 未知 domain 返 404
  - 无 token 返 401

跑法:
    .\\.venv\\Scripts\\python.exe -m tools.dashboard_smoke
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


# 确保 import 路径
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 让 build_app 通过 _check_auth 的"未设 token"检查
os.environ.setdefault("OPUS_API_TOKEN", "smoke-token-bypass")

from fastapi.testclient import TestClient  # noqa: E402

from daemon_api import build_app  # noqa: E402


def assert_eq(actual, expected, msg):
    if actual != expected:
        print(f"  [FAIL] {msg}: expected {expected!r}, got {actual!r}")
        return False
    print(f"  [OK]   {msg}")
    return True


def main() -> int:
    client = TestClient(build_app())
    headers = {"Authorization": "Bearer smoke-token-bypass"}
    failures = 0

    print("\n[1] GET /dashboard/radar (with token)")
    r = client.get("/dashboard/radar", headers=headers)
    if not assert_eq(r.status_code, 200, "status 200"):
        failures += 1
        print(f"       body: {r.text[:200]}")
    else:
        data = r.json()
        items = data.get("items", [])
        meta = data.get("sources_meta", [])
        print(f"       total_items: {data.get('total_items', 0)}")
        print(f"       sources_meta: {len(meta)} entries")
        if items:
            print(f"       first item: {items[0]['title'][:60]}")
            print(f"           source: {items[0]['source_display']} ({items[0]['category']})")
        else:
            print("       (no items - this is OK if radar hasn't run yet)")

    print("\n[2] GET /dashboard/content (workshop · 卷二十六升级)")
    r = client.get("/dashboard/content", headers=headers)
    if not assert_eq(r.status_code, 200, "status 200"):
        failures += 1
    else:
        d = r.json()
        if not assert_eq(d.get("domain"), "content", "domain field = 'content'"):
            failures += 1
        # 卷二十六：从 stub 升级到 workshop · 现在应该有 items 字段
        if not isinstance(d.get("items"), list):
            print(f"  [FAIL] items should be a list, got {type(d.get('items')).__name__}")
            failures += 1
        else:
            print(f"  [OK]   workshop items list (got {len(d['items'])} items)")

    print("\n[3] GET /dashboard/unknown (404)")
    r = client.get("/dashboard/unknown", headers=headers)
    if not assert_eq(r.status_code, 404, "status 404"):
        failures += 1

    print("\n[4] GET /dashboard/radar (no token)")
    r = client.get("/dashboard/radar")
    if not assert_eq(r.status_code, 401, "status 401"):
        failures += 1

    print("\n[5] GET /dashboard/radar (bad token)")
    r = client.get(
        "/dashboard/radar",
        headers={"Authorization": "Bearer wrong-token"},
    )
    if not assert_eq(r.status_code, 401, "status 401"):
        failures += 1

    # 验证 stub / 工坊 维度
    # 卷二十六: design/dev/docs 从 stub 升级到 workshop ; service 仍是 stub
    print("\n[6] stub vs workshop 维度")
    for d in ["design", "dev", "docs"]:
        r = client.get(f"/dashboard/{d}", headers=headers)
        ok = assert_eq(r.status_code, 200, f"GET /dashboard/{d} -> 200")
        if not ok:
            failures += 1
            continue
        if not isinstance(r.json().get("items"), list):
            print(f"  [FAIL] {d} (workshop) should have items list")
            failures += 1
        else:
            print(f"  [OK]   {d} workshop has items list")
    # service 仍是 stub
    r = client.get("/dashboard/service", headers=headers)
    if not assert_eq(r.status_code, 200, "GET /dashboard/service -> 200"):
        failures += 1
    elif r.json().get("status") != "stub":
        print(f"  [FAIL] service should still be 'stub' (got status={r.json().get('status')!r})")
        failures += 1
    else:
        print("  [OK]   service still is stub (等先有产品)")

    print("\n[7] 静态资源 · /static/chat.css")
    r = client.get("/static/chat.css")
    if not assert_eq(r.status_code, 200, "status 200"):
        failures += 1
    elif "text/css" not in r.headers.get("content-type", ""):
        print(f"  [FAIL] content-type: {r.headers.get('content-type')}")
        failures += 1
    elif "--opus:" not in r.text:
        print(f"  [FAIL] css 内容看起来不对 · 前 200 字: {r.text[:200]}")
        failures += 1
    else:
        print(f"  [OK]   chat.css {len(r.text)} bytes · content-type text/css")

    print("\n[8] 静态资源 · /static/chat.js")
    r = client.get("/static/chat.js")
    if not assert_eq(r.status_code, 200, "status 200"):
        failures += 1
    elif "javascript" not in r.headers.get("content-type", ""):
        print(f"  [FAIL] content-type: {r.headers.get('content-type')}")
        failures += 1
    elif "STORAGE" not in r.text:
        print(f"  [FAIL] js 内容看起来不对 · 前 200 字: {r.text[:200]}")
        failures += 1
    else:
        print(f"  [OK]   chat.js {len(r.text)} bytes")

    print("\n[9] 静态资源 · 白名单外的请求 (拒绝)")
    r = client.get("/static/.env")
    if not assert_eq(r.status_code, 404, "GET /static/.env -> 404"):
        failures += 1
    r = client.get("/static/secret.txt")
    if not assert_eq(r.status_code, 404, "GET /static/secret.txt -> 404"):
        failures += 1

    print("\n[10] /ui 仍然能拿到 chat.html")
    r = client.get("/ui")
    if not assert_eq(r.status_code, 200, "status 200"):
        failures += 1
    elif '<link rel="stylesheet" href="/static/chat.css">' not in r.text:
        print("  [FAIL] chat.html 没引用 /static/chat.css")
        failures += 1
    elif '<script src="/static/chat.js"></script>' not in r.text:
        print("  [FAIL] chat.html 没引用 /static/chat.js")
        failures += 1
    else:
        print(f"  [OK]   /ui 引用 chat.css + chat.js 正确")

    print("\n" + "=" * 50)
    if failures == 0:
        print("[smoke] ALL PASS · Day 1 /dashboard endpoint healthy")
        return 0
    print(f"[smoke] {failures} FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
