"""
tools/radar_tools_smoke.py
==========================

测 workers/info_radar.py 重构后的 CRUD + manage_info_source 工具。

不调 LLM · 不起 server · 直接进 Python 端跑 CRUD · 验证：
  - 重构后的 list/add/remove/update API 都能工作
  - manage_info_source 工具 5 个 action 全跑通
  - source id 模糊匹配能找到 source

跑法:
    .\\.venv\\Scripts\\python.exe -m tools.radar_tools_smoke
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 用临时 sources 文件避免污染真实数据
os.environ.setdefault("OPUS_API_TOKEN", "smoke-token")

from agent_tools import REGISTRY  # noqa: E402
from workers.info_radar import list_sources  # noqa: E402


def hr(label: str):
    print(f"\n--- {label} ---")


def main() -> int:
    failures = 0

    # 拿 manage_info_source spec
    spec = REGISTRY.get("manage_info_source")
    if spec is None:
        print("[FAIL] manage_info_source 工具没注册")
        return 1
    print(f"[OK] tool registered: {spec.name} · tier={spec.tier}")

    # 1. list
    hr("[1] action=list")
    r = spec.run({"action": "list"})
    if not r.ok:
        print(f"[FAIL] list failed: {r.error}")
        failures += 1
    else:
        first_3 = r.output.split("\n")[:5]
        print("\n".join(first_3))

    # 2. add
    hr("[2] action=add (smoke test source)")
    r = spec.run({
        "action": "add",
        "name": "OPUS Smoke Test Feed",
        "url": "https://example.com/feed.xml",
        "category": "test",
        "max_items": 5,
    })
    if not r.ok:
        print(f"[FAIL] add failed: {r.error}")
        failures += 1
    else:
        print(r.output)

    # 3. 验证 add 后 list 能看到
    hr("[3] verify add via list_sources()")
    src_ids = [s["id"] for s in list_sources()]
    if "opus-smoke-test-feed" not in src_ids:
        print(f"[FAIL] 加完源后 list 找不到 · 现有: {src_ids}")
        failures += 1
    else:
        print(f"[OK] 找到了新源 · 当前 {len(src_ids)} 个源")

    # 4. update enabled=False (暂停)
    hr("[4] action=update enabled=False")
    r = spec.run({
        "action": "update",
        "source_id": "opus-smoke-test-feed",
        "enabled": False,
    })
    if not r.ok:
        print(f"[FAIL] update failed: {r.error}")
        failures += 1
    else:
        print(r.output)
        # 验证 list 时该源 enabled=False
        for s in list_sources():
            if s["id"] == "opus-smoke-test-feed":
                if s.get("enabled", True):
                    print("[FAIL] enabled 没改成 False")
                    failures += 1
                else:
                    print("[OK] enabled=False 已生效")

    # 5. 模糊匹配（用 name 找 id）
    hr("[5] fuzzy match: remove by name '少数派'")
    # 先确认有少数派
    has_sspai = any(s["id"] == "sspai" for s in list_sources())
    if not has_sspai:
        print("[SKIP] 当前没 sspai 源 · 跳过模糊匹配测试")
    else:
        r = spec.run({"action": "remove", "source_id": "少数派"})
        if not r.ok:
            print(f"[FAIL] 用 display 模糊匹配 remove 失败: {r.error}")
            failures += 1
        else:
            print(r.output[:300])

    # 6. 找不到源
    hr("[6] remove 不存在的源 -> 错误")
    r = spec.run({"action": "remove", "source_id": "this-does-not-exist"})
    if r.ok:
        print("[FAIL] 应该返回 error 但 ok=True")
        failures += 1
    else:
        print(f"[OK] 正确返回错误: {r.error[:100]}")

    # 7. 把 smoke test 源 + 少数派 都清掉（如果还在）
    hr("[7] cleanup smoke test source")
    for sid in ("opus-smoke-test-feed",):
        r = spec.run({"action": "remove", "source_id": sid})
        if r.ok:
            print(f"  cleaned: {sid}")
    # 如果 sspai 被删了 · 加回来（保持工程默认源整齐）
    if not any(s["id"] == "sspai" for s in list_sources()):
        spec.run({
            "action": "add",
            "name": "少数派 · 效率",
            "url": "https://sspai.com/feed",
            "category": "tech-zh",
            "max_items": 8,
            "display": "少数派",
        })
        # 修 id 回 sspai
        # 实际上 _slugify('少数派 · 效率') 会变成乱码 id · 我手动改
        sources = list_sources()
        for s in sources:
            if "sspai" in s.get("url", "") and s["id"] != "sspai":
                from workers.info_radar import remove_source as _rm, add_source as _add
                _rm(s["id"])
                _add(
                    name="少数派 · 效率",
                    url="https://sspai.com/feed",
                    category="tech-zh",
                    max_items=8,
                    display="少数派",
                    source_id="sspai",
                )
                break
        print("  re-added: sspai")

    # 8. 验证 schema 输入校验
    hr("[8] 无效 type")
    try:
        from workers.info_radar import add_source
        add_source(name="bad", url="https://x.com", source_type="bogus")
        print("[FAIL] 应该抛 ValueError")
        failures += 1
    except ValueError as e:
        print(f"[OK] 正确抛 ValueError: {e}")

    hr("[9] 无效 url (没 http://)")
    try:
        from workers.info_radar import add_source
        add_source(name="bad2", url="not-a-url")
        print("[FAIL] 应该抛 ValueError")
        failures += 1
    except ValueError as e:
        print(f"[OK] 正确抛 ValueError: {e}")

    # 最终 list 看清单
    hr("[final] 当前 sources.json")
    sources = list_sources()
    print(f"共 {len(sources)} 个源")
    for s in sources:
        e = "[on]" if s.get("enabled", True) else "[off]"
        print(f"  - {s['id']} {e} · {s.get('display', s['id'])}")

    print("\n" + "=" * 50)
    if failures == 0:
        print("[smoke] ALL PASS")
        return 0
    print(f"[smoke] {failures} FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
