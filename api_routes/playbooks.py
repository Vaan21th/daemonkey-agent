"""api_routes/playbooks.py · 技能库(playbook 沉淀)查看器 API

3 路由:
  GET  /dashboard/playbooks        · 列所有沉淀的 playbook + stats
  GET  /dashboard/playbooks/doc    · 单份 playbook 正文(前端点卡片弹窗预览)
  POST /dashboard/playbooks/delete · 删一份(误沉淀清理)

注册铁律: 必须在 dashboard.router(/dashboard/{domain} catch-all)**之前** include ·
否则 /dashboard/playbooks 会被 catch-all 吞掉走成 domain='playbooks'。

playbook 的主入口仍是 NLP(extract_playbook 沉淀 / 召回时自动取用)· 本路由只给一个
**只读看板**让 BRO 看得见团队攒了哪些技能(闭环范式:AI 的判断/沉淀要让 BRO 看得见)。
整体纳入内核白名单 · 随 update_core 下发。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

from api_routes._deps import check_auth

logger = logging.getLogger("opus.daemon.playbooks")

router = APIRouter()

_ROOT = Path(__file__).resolve().parent.parent
_DAEMON_RULES = _ROOT / "data" / "cognition" / "daemon_rules.md"
# 注：解析铁律不在这里做 —— 统一走 agent_tools/list_iron_rules.parse_rules（单一真相源）。


def _iron_rules() -> list[dict]:
    """技能库铁律读 daemon_rules.md（不再从日记抽）。

    wish-631ff85b · 判据归一 + 可看见重量：
    原来这里**手抄了一份正则**（只认 `## 铁律 N`），跟 agent_tools/list_iron_rules.parse_rules
    是两份判据 —— 那边改了边界规则这边不会跟。而且 hot path / 场景索引表本来就不属于「铁律」，
    所以「铁律一共多重、每条多重」这种数根本算不准。现在直接用权威那份，并给每条带上 tokens。
    """
    try:
        if not _DAEMON_RULES.exists():
            return []
        from agent_tools.list_iron_rules import count_tokens, parse_rules, read_rules_text
        text = read_rules_text(_DAEMON_RULES)
        rules = []
        for r in parse_rules(text):
            seg = text[r["block_start"]:r["end"]]
            rules.append({
                "date": "",
                "title": f"铁律 {r['n']} · {r['title']}",
                "domain": r["domain"],
                "body": r["body"][:800],
                "tokens": count_tokens(seg),
            })
        rules.sort(key=lambda x: x["title"], reverse=True)
        return rules
    except Exception as e:
        logger.warning("iron_rules load failed: %s", e)
        return []


@router.get("/dashboard/playbooks")
def dashboard_playbooks(authorization: Optional[str] = Header(None)):
    """技能库看板 · 列所有沉淀的 playbook(标题/标签/task_type/用过几次/创建时间) + 工艺铁律。"""
    check_auth(authorization)
    try:
        from workers import playbooks as pb
        items = pb.list_playbooks()
        used = sum(1 for it in items if it.get("used_count"))
        iron = _iron_rules()
        stats = {"total": len(items), "used": used, "iron": len(iron)}
        # wish-631ff85b · 重量可见：铁律加起来多重 / 预算多少 / 整个文件多重
        # 文件比铁律之和重得多 —— hot path + 场景索引表也在里面，它们才是大头。
        try:
            from agent_tools.list_iron_rules import BUDGET_TOK, count_tokens, read_rules_text
            stats["iron_tokens"] = sum(r.get("tokens") or 0 for r in iron)
            stats["iron_budget"] = int(BUDGET_TOK)
            # ⚠ 必须 read_rules_text（newline=""）· 裸 read_text 会在 Windows 上把 CRLF 隐式转成 LF，
            #   数字比原文件少一截（实测差 14 tok）—— 那就跟每条铁律用的原文偏移不是一把尺子了。
            stats["iron_file_tokens"] = count_tokens(read_rules_text(_DAEMON_RULES))
        except Exception:
            pass
        return {
            "items": items,
            "iron_rules": iron,
            "stats": stats,
        }
    except Exception as e:
        logger.warning("playbooks endpoint failed: %s", e)
        raise HTTPException(500, f"playbooks failed: {e}")


@router.get("/dashboard/playbooks/doc")
def dashboard_playbooks_doc(id: str, authorization: Optional[str] = Header(None)):
    """取单份 playbook 元数据 + 正文 · 前端点卡片弹窗预览用。"""
    check_auth(authorization)
    from workers import playbooks as pb
    pid = (id or "").strip()
    data = pb.load_playbook(playbook_id=pid)
    if not data.get("id") or data.get("error"):
        raise HTTPException(404, data.get("error") or f"playbook not found: {pid}")
    return {
        "ok": True,
        "id": data["id"],
        "title": data["title"],
        "content": data["content"],
        "meta": data.get("meta", {}),
    }


@router.post("/dashboard/playbooks/delete")
async def dashboard_playbooks_delete(
    request: Request, authorization: Optional[str] = Header(None),
):
    """删一份 playbook · body: {id} · 文件 + 索引一起清(误沉淀清理用)。"""
    check_auth(authorization)
    body = await request.json()
    pid = (body.get("id") or "").strip()
    from workers import playbooks as pb
    if not pb.delete_playbook(pid):
        raise HTTPException(404, f"playbook not found: {pid}")
    return {"ok": True, "deleted": pid}
