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
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

from api_routes._deps import check_auth

logger = logging.getLogger("opus.daemon.playbooks")

router = APIRouter()

_ROOT = Path(__file__).resolve().parent.parent
_DAEMON_RULES = _ROOT / "data" / "cognition" / "daemon_rules.md"
_IRON_HEAD = re.compile(r"^## 铁律 (\d+)\s+·\s+(.+)$", re.MULTILINE)
_IRON_DOMAIN = re.compile(r"<!--\s*domain:\s*(\w+)\s*-->")


def _iron_rules() -> list[dict]:
    """技能库铁律读 daemon_rules.md，不再从日记抽。"""
    try:
        if not _DAEMON_RULES.exists():
            return []
        text = _DAEMON_RULES.read_text(encoding="utf-8")
        matches = list(_IRON_HEAD.finditer(text))
        rules = []
        for idx, m in enumerate(matches):
            body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            body = text[m.end():body_end].strip()
            domain_m = _IRON_DOMAIN.search(body)
            rules.append({
                "date": "",
                "title": f"铁律 {m.group(1)} · {m.group(2).strip()}",
                "domain": (domain_m.group(1).strip().lower() if domain_m else "global"),
                "body": body[:800],
            })
        rules.sort(key=lambda r: r["title"], reverse=True)
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
        return {
            "items": items,
            "iron_rules": iron,
            "stats": {"total": len(items), "used": used, "iron": len(iron)},
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
