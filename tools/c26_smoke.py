"""tools/c26_smoke.py — 卷二十六冒烟测试

测试范围：
  - workers/cognition_loader.py · BRO 画像 + OPUS 日记解析
  - workers/studio_workshop.py · content/design/dev/docs loader + 创建器
  - agent_tools/draft_studio.py · NLP 创建工坊产出
  - agent_tools/read_dashboard.py · 跨维度只读访问
  - agent_tools/propose_next_move.py · 基于画像 + 看板给建议
  - daemon_api · /dashboard/cognition · /dashboard/{content,design,dev,docs}
  - daemon_api · /dashboard/cockpit · 9 个维度（含 cognition + 4 工坊）

跑法:
  .\.venv\Scripts\python.exe tools\c26_smoke.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 测试期间用临时 data dir · 不污染真实数据
TESTDIR = ROOT / "data" / "_c26_smoke"


def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        print(f"  ✗ {msg}")
        raise SystemExit(1)
    print(f"  ✓ {msg}")


def test_cognition_loader():
    print("\n── 1. cognition_loader ──────────────────────────")
    from workers.cognition_loader import load_cognition

    d = load_cognition()
    assert_true(isinstance(d, dict), "load_cognition returns dict")
    assert_true("bro_profile" in d, "has bro_profile")
    assert_true("opus_diary" in d, "has opus_diary")
    assert_true("open_questions" in d, "has open_questions")

    bro = d["bro_profile"]
    assert_true(bro.get("exists") is True, "BRO-NOTEBOOK exists")
    sections = bro.get("sections") or []
    assert_true(len(sections) >= 5, f"BRO sections >= 5 (got {len(sections)})")

    diary = d["opus_diary"]
    assert_true(diary.get("exists") is True, "OPUS diary exists")
    entries = diary.get("entries") or []
    assert_true(len(entries) >= 1, f"diary entries >= 1 (got {len(entries)})")


def test_studio_workshop():
    print("\n── 2. studio_workshop ───────────────────────────")
    from workers.studio_workshop import (
        WORKSHOP_META,
        create_workshop_item,
        load_workshop,
        workshop_meta,
    )

    assert_true(len(WORKSHOP_META) == 4, "4 workshop domains")
    for d in ("content", "design", "dev", "docs"):
        m = workshop_meta(d)
        assert_true(m.get("label") and m.get("icon"), f"{d} has label+icon")

    # 创建测试文件 (会真写到 data/content · 之后清理)
    r = create_workshop_item(
        "content",
        "smoke 测试 · 卷二十六",
        "## 测试 body\n\n- 行 1\n- 行 2\n",
        kind="测试",
    )
    assert_true(r.get("ok") is True, "create_workshop_item ok")
    created_path = ROOT / r["path"]
    assert_true(created_path.exists(), f"file created at {r['path']}")

    w = load_workshop("content")
    assert_true(w.get("label") == "内容制作", "load_workshop content label")
    titles = [it["title"] for it in w.get("items") or []]
    assert_true(
        "smoke 测试 · 卷二十六" in titles,
        "load_workshop sees just-created item",
    )

    try:
        create_workshop_item("not_a_domain", "x", "y")
        assert_true(False, "create with bad domain should raise")
    except ValueError:
        assert_true(True, "create with bad domain raises ValueError")

    try:
        create_workshop_item("content", "", "y")
        assert_true(False, "create with empty title should raise")
    except ValueError:
        assert_true(True, "create with empty title raises ValueError")

    created_path.unlink()
    print(f"  · cleaned up {r['path']}")


def test_draft_studio_tool():
    print("\n── 3. draft_studio tool ─────────────────────────")
    import agent_tools

    spec = agent_tools.REGISTRY.get("draft_studio")
    assert_true(spec is not None, "draft_studio registered")
    assert_true(spec.tier == "confirm", "draft_studio is CONFIRM tier")

    r = spec.run({
        "domain": "design",
        "title": "smoke 卷二十六 spec 测试",
        "body": "## A\n- 设计要点 1\n## B\n- 设计要点 2\n",
        "kind": "spec",
    })
    assert_true(r.ok is True, f"draft_studio run ok (err={r.error})")

    # 找出刚创建的文件 · 验证 + 清理
    d = ROOT / "data" / "design"
    found = list(d.glob("*smoke*spec*.md"))
    assert_true(len(found) >= 1, "design file created")
    for f in found:
        f.unlink()

    # 参数验证
    r = spec.run({"domain": "wrong", "title": "x", "body": "y"})
    assert_true(r.ok is False, "bad domain rejected")

    r = spec.run({"domain": "content", "body": "y"})
    assert_true(r.ok is False, "missing title rejected")

    r = spec.run({"domain": "content", "title": "x"})
    assert_true(r.ok is False, "missing body rejected")


def test_read_dashboard_tool():
    print("\n── 4. read_dashboard tool ───────────────────────")
    import agent_tools

    spec = agent_tools.REGISTRY.get("read_dashboard")
    assert_true(spec is not None, "read_dashboard registered")
    assert_true(spec.tier == "auto", "read_dashboard is AUTO tier")

    for domain in ["radar", "trends", "reports", "cognition",
                   "content", "design", "dev", "docs", "all"]:
        r = spec.run({"domain": domain, "head": 3})
        assert_true(r.ok is True, f"read_dashboard {domain} ok (err={r.error})")
        assert_true(len(r.output) > 0, f"read_dashboard {domain} returns output")

    r = spec.run({"domain": "nope", "head": 3})
    assert_true(r.ok is False, "bad domain rejected")


def test_propose_next_move_tool():
    print("\n── 5. propose_next_move tool ────────────────────")
    import agent_tools

    spec = agent_tools.REGISTRY.get("propose_next_move")
    assert_true(spec is not None, "propose_next_move registered")
    assert_true(spec.tier == "auto", "propose_next_move is AUTO tier")

    r = spec.run({})
    assert_true(r.ok is True, f"propose_next_move runs ok (err={r.error})")
    assert_true(len(r.output) > 100, "propose_next_move returns substantial output")
    assert_true(
        "OPUS" in r.output,
        "output mentions OPUS",
    )


def test_daemon_api_endpoints():
    print("\n── 6. daemon_api endpoints ──────────────────────")
    import os

    token = "smoke-token-c26"
    os.environ["OPUS_API_TOKEN"] = token
    # 旁路灵魂加载 + LLM client · 我们只测 endpoint 本身
    os.environ.setdefault("OPUS_API_DEFAULT_CONFIRM", "confirm")

    from fastapi.testclient import TestClient
    from daemon_api import build_app

    app = build_app()
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}

    # cognition endpoint
    r = client.get("/dashboard/cognition", headers=headers)
    assert_true(r.status_code == 200, f"GET /dashboard/cognition status (got {r.status_code})")
    d = r.json()
    assert_true("bro_profile" in d, "cognition response has bro_profile")
    assert_true("opus_diary" in d, "cognition response has opus_diary")
    assert_true("open_questions" in d, "cognition response has open_questions")

    # 4 个 workshop endpoint
    for domain in ("content", "design", "dev", "docs"):
        r = client.get(f"/dashboard/{domain}", headers=headers)
        assert_true(r.status_code == 200,
                    f"GET /dashboard/{domain} status (got {r.status_code})")
        d = r.json()
        assert_true(d.get("domain") == domain, f"{domain} response.domain matches")
        assert_true(isinstance(d.get("items"), list), f"{domain} has items list")
        assert_true(isinstance(d.get("kinds"), list), f"{domain} has kinds list")

    # service stub
    r = client.get("/dashboard/service", headers=headers)
    assert_true(r.status_code == 200, "service still returns 200")
    d = r.json()
    assert_true(d.get("status") == "stub", "service is stub")

    # cockpit · 卷二十九 现在应该有 12 个维度
    r = client.get("/dashboard/cockpit", headers=headers)
    assert_true(r.status_code == 200, "cockpit endpoint 200")
    d = r.json()
    domain_ids = [x["id"] for x in d.get("domains") or []]
    expected = ["radar", "trends", "reports", "cognition",
                "content", "design", "dev", "docs", "service",
                "opportunities", "feasibility", "plugins"]
    for eid in expected:
        assert_true(eid in domain_ids, f"cockpit has {eid}")
    # 卷二十九：opportunities + feasibility + plugins · 12 维
    assert_true(len(domain_ids) == 12, f"cockpit has 12 domains (got {len(domain_ids)})")

    # cognition 在 cockpit 里要有正确数据 (至少 1 个日记 entry)
    cog_card = next(x for x in d["domains"] if x["id"] == "cognition")
    assert_true(cog_card["stub"] is False, "cognition not stub in cockpit")
    assert_true(cog_card.get("total", 0) >= 1, "cockpit cognition has >=1 diary entry")

    # service 在 cockpit 里要是 stub
    svc_card = next(x for x in d["domains"] if x["id"] == "service")
    assert_true(svc_card["stub"] is True, "service IS stub in cockpit")

    # static 仍然带 no-cache 头（卷二十五 fix 不能丢）
    r = client.get("/static/chat.js")
    assert_true(r.status_code == 200, "static chat.js loadable")
    cc = r.headers.get("cache-control", "")
    assert_true(
        "no-cache" in cc.lower(),
        f"chat.js has no-cache header (got: {cc})",
    )


def main():
    print("=== 卷二十六 smoke test ===")
    start = time.time()
    test_cognition_loader()
    test_studio_workshop()
    test_draft_studio_tool()
    test_read_dashboard_tool()
    test_propose_next_move_tool()
    test_daemon_api_endpoints()
    elapsed = time.time() - start
    print(f"\n=== ALL PASS · {elapsed:.2f}s ===")


if __name__ == "__main__":
    main()
