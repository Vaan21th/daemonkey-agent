"""api_routes/dashboard.py · /dashboard/cockpit + /dashboard/{domain}

wish-413999da phase 1-K · 2 路由 · cockpit 聚合 + 各维度数据源

依赖:
  daemon_api 的 ROOT (lazy import)
  _check_auth → api_routes._deps.check_auth
  asyncio / time / Optional (本地)
  logger → module-level logging.getLogger("opus.daemon.dashboard")
          (原 daemon_api.py 7 处 logger 引用未定义 · phase 1 一并补)

helper 复制 (而非 import 自 daemon_api 内 closure):
  _list_reports / _build_calendar_day · 跟 intelligence.py 相同复制策略
  phase 2 下沉到 services/dashboard.py 时统一去重
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

from api_routes._deps import check_auth
from daemon_api import ROOT

# 兜底领域是【实例配置】(母体 ai / 开源版 self-evolve)·不是代码常量。
try:
    from identity import default_domain as _default_domain
except Exception:
    def _default_domain():
        return "ai"

logger = logging.getLogger("opus.daemon.dashboard")

router = APIRouter()

_REPORTS_DIR = ROOT / "data" / "reports"


def _list_reports() -> dict:
    """扫描 data/reports/ 下所有 docx · 返回 list 给 WebUI 渲染

    卷三十三补丁 · 每项附加 preview_url + has_md_source
      - 新报告生成时同步落 .md 源 · has_md_source=True
      - 旧报告没 .md · 预览时用 python-docx 兜底抽取
    """
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for p in sorted(_REPORTS_DIR.glob("*.docx"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.name.startswith("~$"):
            continue  # Word 临时文件
        try:
            stat = p.stat()
            md_sibling = p.with_suffix(".md")
            items.append({
                "name": p.name,
                "size_kb": round(stat.st_size / 1024, 1),
                "created_at": time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)
                ),
                "download_url": f"/reports/{p.name}",
                "preview_url": f"/reports/preview/{p.name}",  # 卷三十三补丁
                "has_md_source": md_sibling.exists(),
            })
        except OSError:
            continue
    return {
        "domain": "reports",
        "count": len(items),
        "items": items,
        "directory": str(_REPORTS_DIR.relative_to(ROOT) if ROOT in _REPORTS_DIR.parents else _REPORTS_DIR),
    }


def _build_calendar_day(day: str) -> dict:
    """卷三十三补丁 · 单日聚合视图

    从 radar / trends / reports / outcomes 各自的数据源里·捞出 `day`
    这一天发生的所有事件 · 返给 UI 一次性渲染。
    """
    from datetime import date as _date
    try:
        _date.fromisoformat(day)
    except Exception:
        raise HTTPException(400, f"day 必须是 YYYY-MM-DD · 收到 {day!r}")

    out: dict = {"day": day, "items": {}}

    # ─── radar · 按 fetched_at 或 published_at 命中 ───
    try:
        from workers.info_radar import load_radar
        from workers.radar_counts import visible_items
        radar = load_radar()
        r_items_all = visible_items(radar.get("items") or [])  # 卷五十八续 X · 扣 hidden
        from email.utils import parsedate_to_datetime as _ptd

        def _day_of(it: dict) -> str:
            fa = (it.get("fetched_at") or "")[:10]
            if fa == day:
                return fa
            pa = it.get("published_at") or ""
            if not pa:
                return ""
            try:
                return _ptd(pa).strftime("%Y-%m-%d")
            except Exception:
                return pa[:10] if len(pa) >= 10 else ""

        r_items = [it for it in r_items_all if _day_of(it) == day]
        out["items"]["radar"] = {
            "count": len(r_items),
            "items": [
                {
                    "title": it.get("title_zh") or it.get("title"),
                    "title_en": it.get("title") if it.get("title_zh") else None,
                    "source": it.get("source_display") or it.get("source"),
                    "url": it.get("url"),
                    "published_at": it.get("published_at"),
                    "fetched_at": it.get("fetched_at"),
                    "domain": it.get("domain", _default_domain()),
                }
                for it in r_items[:50]
            ],
        }
    except Exception as e:
        logger.warning("calendar day · radar load failed: %s", e)
        out["items"]["radar"] = {"count": 0, "items": [], "error": str(e)}

    # ─── trends · 走 archive ───
    try:
        from workers.trend_finder import load_trends_for_day
        td = load_trends_for_day(day)
        out["items"]["trends"] = {
            "count": len(td.get("trends") or []),
            "items": td.get("trends") or [],
            "source": td.get("_source"),
            "note": td.get("note"),
        }
    except Exception as e:
        logger.warning("calendar day · trends load failed: %s", e)
        out["items"]["trends"] = {"count": 0, "items": [], "error": str(e)}

    # ─── reports · 按 mtime ───
    try:
        rep_data = _list_reports()
        day_reports = []
        for it in (rep_data.get("items") or []):
            ts = it.get("created_at") or ""
            if ts[:10] == day:
                day_reports.append(it)
        out["items"]["reports"] = {
            "count": len(day_reports),
            "items": day_reports,
        }
    except Exception as e:
        logger.warning("calendar day · reports load failed: %s", e)
        out["items"]["reports"] = {"count": 0, "items": [], "error": str(e)}

    # ─── outcomes / 执行反馈 · 按 update.at 命中 ───
    try:
        from workers.outcomes import list_outcomes
        outc = list_outcomes(max_items=300)
        o_items_all = outc.get("items") or []
        day_outcomes = []
        for it in o_items_all:
            updates = it.get("updates") or []
            # 找当天发生的更新
            hit_updates = [
                u for u in updates
                if (u.get("at") or "")[:10] == day
            ]
            if hit_updates or (it.get("created_at") or "")[:10] == day:
                day_outcomes.append({
                    "opp_id": it.get("opp_id"),
                    "opp_title": it.get("opp_title"),
                    "opp_domain": it.get("opp_domain"),
                    "status": it.get("status"),
                    "decision_reason": (it.get("decision_reason") or "")[:200],
                    "hit_updates": hit_updates,
                })
        out["items"]["outcomes"] = {
            "count": len(day_outcomes),
            "items": day_outcomes,
        }
    except Exception as e:
        logger.warning("calendar day · outcomes load failed: %s", e)
        out["items"]["outcomes"] = {"count": 0, "items": [], "error": str(e)}

    total = sum(it.get("count", 0) for it in out["items"].values())
    out["total"] = total
    # 卷五十八续 X · 当天对话数单独字段 · 不进"共 N 件事"(BRO 拍板 separate-mark)
    try:
        from workers.calendar_view import count_sessions_on
        out["sessions_count"] = count_sessions_on(day)
    except Exception:
        out["sessions_count"] = 0
    return out

# _serve_report_file 在 api_routes/intelligence.py 复制版里 · 这里不重复


@router.get("/dashboard/cockpit")
def dashboard_cockpit(
    head: int = 3,
    authorization: Optional[str] = Header(None),
):
    """工作室操作台聚合视图 · 一次返 6+1 维 head N 条

    每个维度返回:
      - id / label / icon  · UI 渲染用
      - items (head 条)    · 卡片显示的简略列表
      - total              · 该维度共多少条
      - stub               · 是否还是 stub 维度
      - last_updated       · 该维度的数据时间戳 (尽力而为)
      - empty_hint         · 为空时给 BRO 的提示文案

    query:
      head=N · 每个卡片返回前 N 条 · 默认 3 · 上限 10
    """
    check_auth(authorization)
    # head 默认 3 · 但 head=0 显式传也要 clamp 到 1（"or" 会把 0 当 falsy）
    if head is None:
        head = 3
    head = max(1, min(int(head), 10))

    out_domains: list[dict] = []

    # 今日新增计数 · 日期字段是今天的条目数 (BRO 2026-06-03 · 徽章不要总数)
    _today = time.strftime("%Y-%m-%d")

    def _count_today(rows, *keys):
        from email.utils import parsedate_to_datetime
        n = 0
        for it in rows or []:
            for k in keys:
                s = str(it.get(k) or "")
                if not s:
                    continue
                hit = s[:10] == _today
                if not hit:
                    try:
                        hit = parsedate_to_datetime(s).strftime("%Y-%m-%d") == _today
                    except Exception:
                        hit = False
                if hit:
                    n += 1
                    break
        return n

    # <i class='ri-radar-fill'></i> 信息雷达
    try:
        from workers.info_radar import load_radar
        from workers.radar_counts import radar_stats, visible_items
        radar = load_radar()
        items_raw = radar.get("items", [])
        # 卷五十八续 X · 唯一真相源: total=可见(扣hidden) · today_new=今天fetched · items=可见前 head
        _vis = visible_items(items_raw)
        _stats = radar_stats(items_raw)
        items = [
            {
                # 卷二十七：title_zh 优先 · 原文 fallback
                "title": it.get("title_zh") or it.get("title", "(无标题)"),
                "title_en": it.get("title") if it.get("title_zh") else None,
                "source": it.get("source_display") or it.get("source", ""),
                "url": it.get("url", ""),
                "published_at": it.get("published_at", ""),
                "translated": bool(it.get("title_zh")),
            }
            for it in _vis[:head]
        ]
        out_domains.append({
            "id": "radar",
            "label": "信息雷达",
            "icon": "<i class='ri-radar-fill'></i>",
            "items": items,
            "total": _stats["total"],
            "today_new": _stats["new_today"],
            "last_updated": radar.get("generated_at"),
            "stub": False,
            "empty_hint": (
                radar.get("note") or "还没抓过 · 在底栏跟 OPUS 说「抓一下雷达」"
            ),
        })
    except Exception as e:
        out_domains.append({
            "id": "radar", "label": "信息雷达", "icon": "<i class='ri-radar-fill'></i>",
            "items": [], "total": 0, "stub": False,
            "error": str(e),
        })

    # <i class='ri-line-chart-fill'></i> 今日趋势
    try:
        from workers.trend_finder import load_trends
        trends = load_trends()
        t_items = trends.get("trends", [])
        items = [
            {
                "title": t.get("title", ""),
                "summary": (t.get("summary", "") or "")[:120],
            }
            for t in t_items[:head]
        ]
        out_domains.append({
            "id": "trends",
            "label": "今日趋势",
            "icon": "<i class='ri-line-chart-fill'></i>",
            "items": items,
            "total": len(t_items),
            "last_updated": trends.get("generated_at"),
            "stub": False,
            "empty_hint": (
                trends.get("note") or "还没总结 · 在底栏跟 OPUS 说「今日趋势」"
            ),
        })
    except Exception as e:
        out_domains.append({
            "id": "trends", "label": "今日趋势", "icon": "<i class='ri-line-chart-fill'></i>",
            "items": [], "total": 0, "stub": False,
            "error": str(e),
        })

    # <i class='ri-article-fill'></i> 报告库
    try:
        reports = _list_reports()
        r_items = reports.get("items", [])[:head]
        out_domains.append({
            "id": "reports",
            "label": "报告库",
            "icon": "<i class='ri-article-fill'></i>",
            "items": [
                {
                    "name": it.get("name"),
                    "size_kb": it.get("size_kb"),
                    "created_at": it.get("created_at"),
                    "download_url": it.get("download_url"),
                }
                for it in r_items
            ],
            "total": reports.get("count", 0),
            "today_new": _count_today(reports.get("items"), "created_at"),
            "last_updated": (r_items[0]["created_at"] if r_items else None),
            "stub": False,
            "empty_hint": "还没生成过 · 在底栏跟 OPUS 说「做一份测试报告」",
        })
    except Exception as e:
        out_domains.append({
            "id": "reports", "label": "报告库", "icon": "<i class='ri-article-fill'></i>",
            "items": [], "total": 0, "stub": False,
            "error": str(e),
        })

    # <i class='ri-diamond-fill'></i> 掘金机会（卷二十八加）· 这是 BI 看板的"主角"
    try:
        from workers.opportunity_miner import load_opportunities
        opps = load_opportunities()
        opp_items = opps.get("opportunities") or []
        items = [
            {
                "title": o.get("title", ""),
                "domain": o.get("domain", _default_domain()),
                "fit": o.get("fit", "maybe"),
                "recommend": o.get("recommend", 3),
                "cost_effort": o.get("cost_effort", "?"),
                "upside": o.get("upside", "?"),
                "summary": (o.get("summary", "") or "")[:120],
            }
            for o in opp_items[:head]
        ]
        out_domains.append({
            "id": "opportunities",
            "label": "掘金机会",
            "icon": "<i class='ri-diamond-fill'></i>",
            "items": items,
            "total": len(opp_items),
            "last_updated": opps.get("generated_at"),
            "stub": False,
            "empty_hint": (
                opps.get("note")
                or "还没挖过 · 跟 OPUS 说「挖一下机会」"
            ),
        })
    except Exception as e:
        out_domains.append({
            "id": "opportunities", "label": "掘金机会", "icon": "<i class='ri-diamond-fill'></i>",
            "items": [], "total": 0, "stub": False,
            "error": str(e),
        })

    # <i class='ri-brain-fill'></i> OPUS 日记 / 认知（卷二十六加）
    try:
        from workers.cognition_loader import load_cognition
        cog = load_cognition(section_excerpt_chars=120, diary_max_entries=head)
        diary_entries = cog["opus_diary"].get("entries", [])
        items = [
            {
                "title": e.get("title", ""),
                "date": e.get("date", ""),
                "summary": (e.get("body", "") or "")[:120],
            }
            for e in diary_entries[:head]
        ]
        out_domains.append({
            "id": "cognition",
            "label": "OPUS 日记",
            "icon": "<i class='ri-brain-fill'></i>",
            "items": items,
            "total": cog["opus_diary"].get("total", len(diary_entries)),
            "last_updated": cog["opus_diary"].get("last_updated"),
            "stub": False,
            "empty_hint": "OPUS 还没写过笔记 · 跟 OPUS 说「记一笔今天的观察」",
        })
    except Exception as e:
        out_domains.append({
            "id": "cognition", "label": "OPUS 日记", "icon": "<i class='ri-brain-fill'></i>",
            "items": [], "total": 0, "stub": False,
            "error": str(e),
        })

    # <i class='ri-film-fill'></i> 内容制作 · <i class='ri-palette-fill'></i> 产品设计 · <i class='ri-terminal-box-fill'></i> 产品开发 · <i class='ri-file-text-fill'></i> 文档撰写
    # 卷二十六：从 stub 升级到"骨架可用版"——data 目录 + loader + 工具
    for sid, label, icon in [
        ("content", "内容制作", "<i class='ri-film-fill'></i>"),
        ("design",  "产品设计", "<i class='ri-palette-fill'></i>"),
        ("dev",     "产品开发", "<i class='ri-terminal-box-fill'></i>"),
        ("docs",    "文档撰写", "<i class='ri-file-text-fill'></i>"),
    ]:
        try:
            from workers.studio_workshop import load_workshop
            ws = load_workshop(sid)
            items = [
                {
                    "title": it.get("title", it.get("name", "")),
                    "kind": it.get("kind", ""),
                    "created_at": it.get("created_at", ""),
                }
                for it in (ws.get("items") or [])[:head]
            ]
            out_domains.append({
                "id": sid,
                "label": label,
                "icon": icon,
                "items": items,
                "total": len(ws.get("items") or []),
                "today_new": _count_today(ws.get("items"), "created_at"),
                "last_updated": (
                    items[0]["created_at"] if items else None
                ),
                "stub": False,
                "empty_hint": ws.get("empty_hint", ""),
            })
        except Exception as e:
            out_domains.append({
                "id": sid, "label": label, "icon": icon,
                "items": [], "total": 0, "stub": False,
                "error": str(e),
            })

    # <i class='ri-bar-chart-fill'></i> 可行性分析（卷二十九加）· 能力对照分组
    try:
        from workers.feasibility_analyzer import list_feasibility
        feas = list_feasibility(max_items=head)
        items = [
            {
                "opp_id": it.get("opp_id"),
                "title": it.get("opp_title"),
                "domain": it.get("opp_domain"),
                "score": it.get("feasibility_score"),
                "verdict": it.get("verdict"),
                "verdict_reason": it.get("verdict_reason"),
            }
            for it in (feas.get("items") or [])[:head]
        ]
        out_domains.append({
            "id": "feasibility",
            "label": "可行性分析",
            "icon": "<i class='ri-bar-chart-fill'></i>",
            "items": items,
            "total": feas.get("total", 0),
            "last_updated": (items[0].get("title") if items else None),
            "stub": False,
            "empty_hint": (
                "还没分析过 · 在 <i class='ri-diamond-fill'></i> 掘金机会卡上点「💰 估算成本」 "
                "或跟 OPUS 说「分析第 N 个机会的可行性」"
            ),
        })
    except Exception as e:
        out_domains.append({
            "id": "feasibility", "label": "可行性分析", "icon": "<i class='ri-bar-chart-fill'></i>",
            "items": [], "total": 0, "stub": False,
            "error": str(e),
        })

    # <i class='ri-refresh-fill'></i> 执行反馈（卷三十三加）· 跟 outcomes 共享数据 · 视图按状态聚合
    try:
        from workers.outcomes import _STATUS_LABEL, list_outcomes
        outc = list_outcomes(max_items=200)
        o_items = outc.get("items") or []
        items = [
            {
                "opp_id": it.get("opp_id"),
                "title": it.get("opp_title") or "?",
                "status": it.get("status") or "not_started",
                "status_label": _STATUS_LABEL.get(
                    it.get("status") or "not_started", "?"
                ),
                "domain": it.get("opp_domain") or "",
                "updated_at": it.get("updated_at"),
            }
            for it in o_items[:head]
        ]
        out_domains.append({
            "id": "execution",
            "label": "执行反馈",
            "icon": "<i class='ri-refresh-fill'></i>",
            "items": items,
            "total": outc.get("total", len(o_items)),
            "today_new": _count_today(o_items, "updated_at"),
            "by_status": outc.get("by_status") or {},
            "last_updated": outc.get("updated_at"),
            "stub": False,
            "empty_hint": (
                "还没有项目在执行 · 在可行性分析里点「开干 / 不做了」就会出现在这里"
            ),
        })
    except Exception as e:
        out_domains.append({
            "id": "execution", "label": "执行反馈", "icon": "<i class='ri-refresh-fill'></i>",
            "items": [], "total": 0, "stub": False,
            "error": str(e),
        })

    # <i class='ri-team-fill'></i> 用户运营 · 暂保持 stub（BRO 原话：等先有产品再做）· 卷二十九改名 服务→运营
    out_domains.append({
        "id": "service", "label": "用户运营", "icon": "<i class='ri-team-fill'></i>",
        "items": [], "total": 0, "stub": True,
        "last_updated": None,
        "empty_hint": "等先有产品 · 这一维度等用户接入再开",
    })

    # <i class='ri-puzzle-fill'></i> 插件库（卷二十九加）· 能力扩展层
    try:
        from workers.plugins_index import load_plugins
        plugins = load_plugins()
        items = [
            {
                "name": it.get("name"),
                "tier": it.get("tier"),
                "category": it.get("category"),
                "description": it.get("description"),
            }
            for it in (plugins.get("items") or [])[:head]
        ]
        out_domains.append({
            "id": "plugins",
            "label": "插件库",
            "icon": "<i class='ri-puzzle-fill'></i>",
            "items": items,
            "total": plugins.get("total", 0),
            "last_updated": plugins.get("generated_at"),
            "stub": False,
            "empty_hint": "插件库自动列出所有 OPUS 已装载的工具",
        })
    except Exception as e:
        out_domains.append({
            "id": "plugins", "label": "插件库", "icon": "<i class='ri-puzzle-fill'></i>",
            "items": [], "total": 0, "stub": False,
            "error": str(e),
        })

    # 卷二十八 · 给 BI 看板用的"领域热力图"数据 · 不影响旧 UI
    domains_overview: list[dict] = []
    try:
        from workers.info_radar import list_domains as _list_domains
        domains_overview = _list_domains()
    except Exception:
        pass

    # 卷三十五 · 心愿单维度 · 跟着 cockpit 一起返
    try:
        from workers.wishlist import list_wishes, wishlist_summary
        wishes_head = list_wishes(sort_by="status")[:head]
        wishlist_card = {
            "id": "wishlist",
            "label": "OPUS 心愿单",
            "icon": "<i class='ri-lightbulb-fill'></i>",
            "items": [
                {
                    "id": w["id"],
                    "title": w["title"],
                    "status": w["status"],
                    "priority": w["priority"],
                    "integration_path": w["integration_path"],
                    "source_ref": (w.get("source") or {}).get("ref"),
                }
                for w in wishes_head
            ],
            "total": wishlist_summary().get("total", 0),
            "summary": wishlist_summary(),
            "stub": False,
            "empty_hint": "OPUS 还没说想装啥·让它去 self-evolve 域瞄一眼吧",
        }
        out_domains.append(wishlist_card)
    except Exception as e:
        out_domains.append({
            "id": "wishlist", "label": "OPUS 心愿单", "icon": "<i class='ri-lightbulb-fill'></i>",
            "items": [], "total": 0, "stub": False,
            "error": str(e),
        })

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "head": head,
        "domains": out_domains,
        "domains_overview": domains_overview,
    }


@router.get("/dashboard/capability_snapshot")
def dashboard_capability_snapshot(
    authorization: Optional[str] = Header(None),
):
    """A·「OPUS 眼里的你」· 市场能力镜像快照 (只读·不调 LLM)。

    数据源 data/bro_capability_snapshot.md (workers/capability_mirror 写)。
    让"照完即孤岛"的快照在 BI 看得见 —— 认知对齐 (宪法⑤)。
    必须注册在 /dashboard/{domain} catch-all 之前·否则被吞。
    """
    check_auth(authorization)
    try:
        from workers.capability_mirror import SNAPSHOT_PATH, load_snapshot
        snap = load_snapshot()
        generated_at = None
        p = Path(str(SNAPSHOT_PATH))
        if p.exists():
            generated_at = time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))
        return {
            "snapshot": snap.get("snapshot", ""),
            "generated_at": generated_at,
            "note": snap.get("note", ""),
            "draft_prompt": "帮我照一次市场能力镜像 (mirror_capability action=generate)",
        }
    except Exception as e:
        logger.warning("capability_snapshot endpoint failed: %s", e)
        raise HTTPException(500, f"capability_snapshot failed: {e}")


@router.get("/dashboard/closure")
def dashboard_closure(
    authorization: Optional[str] = Header(None),
):
    """B·闭环温度计 · 哪些 OPUS 输出还在等用户的反应。

    纯只读聚合·单个 gauge 出错不影响其他。
    必须注册在 /dashboard/{domain} catch-all 之前。
    """
    check_auth(authorization)
    gauges: list[dict] = []

    # 1. 掘金机会 → 产出反馈
    try:
        import json as _json
        from workers.outcomes import list_outcomes
        opp_total = 0
        opp_file = ROOT / "data" / "opportunities.json"
        if opp_file.exists():
            raw = _json.loads(opp_file.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                opp_total = len(raw)
            elif isinstance(raw, dict):
                opp_total = len(raw.get("opportunities") or raw.get("items") or [])
        oc_total = list_outcomes(max_items=1).get("total", 0)
        pending = max(0, opp_total - oc_total)
        gauges.append({
            "id": "opp", "label": "掘金机会 → 产出",
            "total": opp_total, "closed": min(oc_total, opp_total), "pending": pending,
            "hint": f"{pending} 个机会还没记录产出/拍板" if pending else "都有产出反馈了",
        })
    except Exception as e:
        logger.debug("closure opp gauge failed: %s", e)

    # 2. OPUS 心愿 → 你的决策
    try:
        from workers.wishlist import wishlist_summary
        ws = wishlist_summary()
        waiting = (ws.get("pending", 0) or 0) + (ws.get("review", 0) or 0)
        total = ws.get("total", 0) or 0
        gauges.append({
            "id": "wish", "label": "OPUS 心愿 → 决策",
            "total": total, "closed": max(0, total - waiting), "pending": waiting,
            "hint": f"{waiting} 条等你拍板/验收" if waiting else "没有待决心愿",
        })
    except Exception as e:
        logger.debug("closure wish gauge failed: %s", e)

    # 3. 月度复盘 (节律层)
    try:
        from workers.rituals import get_rituals
        mr = next((r for r in get_rituals() if r.get("id") == "monthly_review"), None)
        if mr:
            done = bool(mr.get("drafted_for_next"))
            dl = mr.get("days_left")
            if done:
                hint = "本期已起草"
            elif isinstance(dl, int) and dl >= 0:
                hint = f"还有 {dl} 天到期·未起草"
            else:
                hint = "已过期·未起草"
            gauges.append({
                "id": "review", "label": "月度复盘 → 起草",
                "total": 1, "closed": 1 if done else 0, "pending": 0 if done else 1,
                "hint": hint,
            })
    except Exception as e:
        logger.debug("closure review gauge failed: %s", e)

    # 4. 复盘批注 → 画像回流 (对账闭环硬提醒 · final 批注进没进 BRO-NOTEBOOK)
    try:
        from workers.review_generator import pending_reflows, list_reviews
        final_total = sum(1 for r in list_reviews() if r.get("status") == "final")
        if final_total:
            pend_n = len(pending_reflows())
            gauges.append({
                "id": "reflow", "label": "复盘批注 → 画像回流",
                "total": final_total, "closed": max(0, final_total - pend_n), "pending": pend_n,
                "hint": (f"{pend_n} 份 final 批注还没进 BRO-NOTEBOOK" if pend_n
                         else "所有批注都已回流画像"),
            })
    except Exception as e:
        logger.debug("closure reflow gauge failed: %s", e)

    total_closed = sum(g["closed"] for g in gauges)
    total_all = sum(g["total"] for g in gauges)
    rate = round(100 * total_closed / total_all) if total_all else 100
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "gauges": gauges,
        "closure_rate": rate,
    }


@router.get("/dashboard/{domain}")
async def dashboard(
    request: Request,
    domain: str,
    refresh: bool = False,
    domain_filter: Optional[str] = None,
    show_hidden: bool = False,
    date: Optional[str] = None,  # 卷三十三补丁 · YYYY-MM-DD · 雷达/趋势按日筛
    vdomain: Optional[str] = None,  # 卷五十六 · 价值热力图的领域筛选 (calendar_valued / day_signals 用)
    authorization: Optional[str] = Header(None),
):
    """工作室操作台 · 各维度数据源（卷二十一加）

    domain:
      - radar         · 信息雷达 · 多源资讯（workers/info_radar.py）
      - trends        · 每日趋势 · LLM 总结（workers/trend_finder.py）
      - reports       · 文档库 · generate_report 落 data/reports/（卷二十四）
      - opportunities · 掘金机会 · LLM 综合输出（卷二十八）
      - cognition     · OPUS 日记 + BRO 画像（卷二十六）
      - content / design / dev / docs · 工坊出品（卷二十六）

    query:
      refresh=true        · 强制 worker 重跑（同步等待，可能 20-30s）
      domain_filter=ai    · 卷二十八 · radar 按 domain 过滤
    """
    check_auth(authorization)

    if domain == "radar":
        from workers.info_radar import (
            DOMAIN_META,
            list_domains,
            load_radar,
            refresh_radar,
        )
        if refresh:
            try:
                # 卷四十六续 5 · refresh_radar 跑多源 RSS / web 抓取 (sync I/O · 20-30s)
                # 直接调会阻塞 asyncio event loop · 卡死 /chat/stream 等并发请求
                # 丢线程池跑 · LLM 流式不再被打断
                await asyncio.to_thread(refresh_radar)
            except Exception as e:
                raise HTTPException(500, f"radar refresh failed: {e}")
        data = load_radar()
        data["domains_overview"] = list_domains()
        data["domains_meta"] = DOMAIN_META
        # 卷五十八续 X · 顶栏"今日新增 X · 共 Y"·唯一真相源·基于全量 (不受 domain/date 临时过滤影响)
        try:
            from workers.radar_counts import radar_stats
            data["stats"] = radar_stats(data.get("items") or [])
        except Exception as e:
            logger.debug("radar stats failed: %s", e)

        # 卷三十二 · 注入 feedback + softness · 并按打标/软文 sort
        try:
            from workers.radar_feedback import feedback_map, item_id_for_url
            from workers.softness_score import (
                annotate_items as _ann_soft,
                sort_items as _sort_smart,
            )
            from workers.info_value import item_value  # 卷五十六 · 给每条注入价值分→前端星级
            fb = feedback_map()
            items = data.get("items") or []
            # 给每条 item 注入 item_id 和 feedback 状态
            augmented: list[dict] = []
            for it in items:
                iid = item_id_for_url(it.get("url") or "")
                entry = fb.get(iid) or {}
                aug = dict(it)
                aug["item_id"] = iid
                if entry.get("feedback"):
                    aug["feedback"] = entry["feedback"]
                    if entry.get("note"):
                        aug["feedback_note"] = entry["note"]
                # 卷五十六 · 价值分 (0-100)·前端按它显星级·跟 BI 看板/下钻抽屉同一套口径
                aug["value"] = item_value(it, fb_map=fb)
                augmented.append(aug)
            # 算 softness
            augmented = _ann_soft(augmented)
            # 隐藏的去掉（除非显式要看）
            if not show_hidden:
                augmented = [
                    it for it in augmented
                    if it.get("feedback") != "hidden"
                ]
            # 按 starred → thumbs_up → low → medium → high softness sort
            augmented = _sort_smart(augmented)
            data["items"] = augmented
            # 统计软文 / 反馈分布
            soft_counts = {"low": 0, "medium": 0, "high": 0}
            for it in augmented:
                lvl = (it.get("softness") or {}).get("level") or "low"
                soft_counts[lvl] = soft_counts.get(lvl, 0) + 1
            data["softness_counts"] = soft_counts
            fb_counts: dict = {}
            for it in augmented:
                f = it.get("feedback")
                if f:
                    fb_counts[f] = fb_counts.get(f, 0) + 1
            data["feedback_counts"] = fb_counts
        except Exception as e:
            logger.warning("radar augment with feedback/softness failed: %s", e)

        if domain_filter:
            if domain_filter not in DOMAIN_META:
                raise HTTPException(
                    400,
                    f"unknown domain filter: {domain_filter!r} · "
                    f"可选: {list(DOMAIN_META.keys())}",
                )
            filtered = [
                it for it in (data.get("items") or [])
                if it.get("domain", _default_domain()) == domain_filter
            ]
            data["items"] = filtered
            data["filtered_by_domain"] = domain_filter
            data["filtered_count"] = len(filtered)

        # 卷三十三补丁 · 按日期过滤（fetched_at 取前 10 字符 = YYYY-MM-DD）
        if date and len(date) == 10:
            day_filtered = []
            for it in (data.get("items") or []):
                fa = (it.get("fetched_at") or "")[:10]
                pa = (it.get("published_at") or "")
                # published_at 可能是 RFC 822 格式 · 试 parse 出日期
                pa_iso = ""
                if pa:
                    try:
                        from email.utils import parsedate_to_datetime as _ptd
                        pa_iso = _ptd(pa).strftime("%Y-%m-%d")
                    except Exception:
                        pa_iso = pa[:10] if len(pa) >= 10 else ""
                if fa == date or pa_iso == date:
                    day_filtered.append(it)
            data["items"] = day_filtered
            data["filtered_by_date"] = date
            data["filtered_date_count"] = len(day_filtered)
        return data

    if domain == "trends":
        from workers.trend_finder import (
            generate_trends,
            load_trends,
            load_trends_for_day,
        )
        if refresh:
            try:
                # 卷四十六续 5 · generate_trends 调 LLM (sync · 10-30s) · 同样阻塞 event loop · 丢线程池
                return await asyncio.to_thread(generate_trends)
            except Exception as e:
                raise HTTPException(500, f"trend_finder failed: {e}")
        # 卷三十三补丁 · 按日期过滤 · domain_filter 复用为 day key (YYYY-MM-DD)
        if domain_filter and len(domain_filter) == 10 and domain_filter[4] == "-":
            return load_trends_for_day(domain_filter)
        return load_trends()

    if domain == "reports":
        return _list_reports()

    if domain == "cognition":
        from workers.cognition_loader import load_cognition
        return load_cognition()

    if domain == "opportunities":
        # 卷二十八 · 掘金机会维度
        from workers.opportunity_miner import (
            load_opportunities,
            mine_opportunities,
        )
        if refresh:
            try:
                # 卷四十六续 5 · mine_opportunities 调 LLM + 读多文件 (sync · 长) · 丢线程池
                return await asyncio.to_thread(mine_opportunities)
            except Exception as e:
                raise HTTPException(500, f"mine_opportunities failed: {e}")
        return load_opportunities()

    if domain in ("content", "design", "dev", "docs"):
        from workers.studio_workshop import load_workshop
        return load_workshop(domain)

    if domain == "service":
        return {
            "domain": "service",
            "status": "stub",
            "note": (
                "用户运营等先有产品再开 · BRO 原话「现在没产品没必要」· "
                "做出第一个用户能下载/订阅的东西后这一维度自然就活了"
            ),
        }

    if domain == "feasibility":
        from workers.feasibility_analyzer import (
            analyze_feasibility,
            list_feasibility,
            load_feasibility,
        )
        opp_id = domain_filter
        if opp_id and refresh:
            try:
                # 卷四十六续 5 · analyze_feasibility 调 LLM (sync · 长) · 丢线程池
                result = await asyncio.to_thread(analyze_feasibility, opp_id)
                if not result.get("ok"):
                    raise HTTPException(500, result.get("error") or "分析失败")
                return result
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(500, f"feasibility analyze failed: {e}")
        if opp_id:
            data = load_feasibility(opp_id)
            if not data:
                raise HTTPException(
                    404,
                    f"opp={opp_id} 还没分析过 · 加 refresh=true 跑一次",
                )
            return data
        return list_feasibility()

    if domain == "plugins":
        from workers.plugins_index import CATEGORY_META, load_plugins
        data = load_plugins()
        data["category_meta"] = CATEGORY_META
        return data

    if domain == "outcomes":
        from workers.outcomes import list_outcomes, load_outcome
        opp_id = domain_filter
        if opp_id:
            outcome = load_outcome(opp_id)
            if not outcome:
                raise HTTPException(404, f"opp={opp_id} 还没 outcome 记录")
            return outcome
        return list_outcomes()

    if domain == "execution":
        # 卷三十三 · 执行反馈独立维度
        #
        # 跟 outcomes 共享数据底层 · 但视图按"项目视角"组织：
        #   - 状态分组：not_started / in_progress / completed / abandoned
        #   - 每项含 source_opp 元数据（回链到掘金机会）
        from workers.outcomes import (
            _STATUS_LABEL,
            list_outcomes,
            load_outcome,
        )
        opp_id = domain_filter
        if opp_id:
            # 单项详情 · 跟 outcomes 同·让 UI 不必两套请求
            d = load_outcome(opp_id)
            if not d:
                raise HTTPException(404, f"opp={opp_id} 还没执行记录")
            # 补一份"它对应的掘金机会快照"·让 UI 一并展示
            try:
                from workers.opportunity_miner import load_opportunities
                opps = load_opportunities().get("opportunities") or []
                for o in opps:
                    if o.get("id") == opp_id:
                        d["opp_snapshot"] = {
                            "id": o.get("id"),
                            "title": o.get("title"),
                            "domain": o.get("domain"),
                            "summary": o.get("summary"),
                            "fit": o.get("fit"),
                            "recommend": o.get("recommend"),
                        }
                        break
            except Exception as e:
                logger.debug("attach opp_snapshot failed: %s", e)
            return d

        # 列表 · 按状态分组
        raw = list_outcomes(max_items=200)
        items = raw.get("items") or []
        grouped: dict[str, list[dict]] = {
            "not_started": [],
            "in_progress": [],
            "completed": [],
            "abandoned": [],
        }
        for it in items:
            st = it.get("status") or "not_started"
            grouped.setdefault(st, []).append(it)
        status_meta = {
            "not_started": {
                "label": _STATUS_LABEL.get("not_started", "未启动"),
                "icon": "<i class='ri-add-circle-fill'></i>",
                "color": "#7c869c",
            },
            "in_progress": {
                "label": _STATUS_LABEL.get("in_progress", "进行中"),
                "icon": "<i class='ri-play-fill'></i>",
                "color": "#7aa2ff",
            },
            "completed": {
                "label": _STATUS_LABEL.get("completed", "已完成"),
                "icon": "<i class='ri-check-fill'></i>",
                "color": "#5bd1a2",
            },
            "abandoned": {
                "label": _STATUS_LABEL.get("abandoned", "已放弃"),
                "icon": "<i class='ri-close-fill'></i>",
                "color": "#d97a7a",
            },
        }
        return {
            "total": raw.get("total", len(items)),
            "by_status": raw.get("by_status") or {},
            "status_meta": status_meta,
            "grouped": grouped,
            "items": items,  # 平铺·供 UI 切换视图
            "updated_at": raw.get("updated_at"),
        }

    if domain == "favorites":
        # 卷三十三 · 统一收藏夹
        from workers.favorites import list_favorites
        kind = domain_filter  # 复用 domain_filter · 不影响 radar 那边的 domain
        data = list_favorites(kind=kind if kind in ("opportunity", "feasibility") else None)
        # 附加快照（标题 / domain 已在 entry 里）
        return data

    if domain == "wishlist":
        # 卷三十五 · OPUS 自我演化心愿单 (卷五十三 · 四态精简 + 测谎仪)
        # wish-83fe7c7b 补丁 · sort_by + 分页
        from workers.wishlist import list_wishes, wishlist_summary
        status = (domain_filter or "").strip() or None
        valid = {"pending", "active", "review", "live", "rejected"}
        sort_by = (request.query_params.get("sort_by") or "auto").strip()
        wishes = list_wishes(
            status_filter=status if status in valid else None,
            sort_by=sort_by if sort_by in ("auto", "priority", "created_at", "updated", "status") else "auto",
        )
        # 分页参数 (前端懒加载 · 先解析以便 git 审计判断)
        try:
            page = max(1, int(request.query_params.get("page") or "1"))
        except (ValueError, TypeError):
            page = 1
        try:
            page_size = max(5, min(50, int(request.query_params.get("page_size") or "15")))
        except (ValueError, TypeError):
            page_size = 15

        # 卷五十二/五十三 · git 测谎仪 · 只在初始全量加载时跑 (无过滤+首页)
        #   过滤/分页请求跳过 —— 审计要对每条 wish 跑 git 命令，O(n) 很慢
        git_unmerged_count = None
        git_lie_count = None
        run_audit = (not status and page == 1)  # 只在初始全量加载时审计
        if run_audit:
            try:
                from workers.git_ops import audit_wishes_merge_state
                audit = audit_wishes_merge_state(wishes)
                git_unmerged_count = 0
                git_lie_count = 0
                for w in wishes:
                    st = audit.get(w.get("id"), {})
                    state = st.get("state", "none")
                    w["git_merge_state"] = state
                    w["git_unmerged_commits"] = st.get("ahead", 0)
                    lie = (w.get("status") == "live" and state == "unmerged")
                    w["git_lie"] = lie
                    if lie:
                        git_lie_count += 1
                    elif state == "unmerged":
                        git_unmerged_count += 1
            except Exception as e:
                logger.warning("wishlist git merge audit failed: %s", e)
        total = len(wishes)
        has_more = page * page_size < total
        # 累加分页: page=2 返回前 20 条, 前端直接替换全列表
        page_wishes = wishes[:(page * page_size)]

        return {
            "wishes": page_wishes,
            "summary": wishlist_summary(),
            "filter": status,
            "sort_by": sort_by if sort_by in ("auto", "priority", "created_at", "updated", "status") else "auto",
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": has_more,
            "git_unmerged_count": git_unmerged_count,
            "git_lie_count": git_lie_count,
        }

    if domain == "calendar":
        # 卷三十三 · 信息日历视图
        # 卷三十三补丁 · domain_filter 支持两种：
        #   - "YYYY-MM"    → 月视图（默认当月）
        #   - "YYYY-MM-DD" → 单日聚合视图（雷达 + 趋势 + 报告 + outcomes 全部那一天）
        from datetime import datetime as _dt
        from workers.calendar_view import build_calendar
        mm = (domain_filter or "").strip()

        # 单日视图
        if len(mm) == 10 and mm[4] == "-" and mm[7] == "-":
            return _build_calendar_day(mm)

        # 月视图
        if mm:
            try:
                y, m = mm.split("-")
                year = int(y)
                month = int(m)
            except Exception:
                raise HTTPException(400, f"calendar domain_filter 期望 YYYY-MM · 收到 {mm!r}")
        else:
            now = _dt.now()
            year, month = now.year, now.month
        try:
            return build_calendar(year, month)
        except ValueError as e:
            raise HTTPException(400, str(e))

    if domain == "calendar_valued":
        # 卷五十六 · 价值加权月历 · BI 热力图按"价值密度"深浅着色 (不是计数)
        # domain_filter=YYYY-MM (默认当月) · vdomain=ai/创投/... (默认全部领域)
        from datetime import datetime as _dt
        from workers.info_value import build_value_calendar
        mm = (domain_filter or "").strip()
        if mm:
            try:
                parts = mm.split("-")
                year, month = int(parts[0]), int(parts[1])
            except Exception:
                raise HTTPException(400, f"calendar_valued domain_filter 期望 YYYY-MM · 收到 {mm!r}")
        else:
            now = _dt.now()
            year, month = now.year, now.month
        vd = (vdomain or "").strip() or None
        if vd in ("all", "全部"):
            vd = None
        try:
            return build_value_calendar(year, month, vd)
        except ValueError as e:
            raise HTTPException(400, str(e))

    if domain == "day_signals":
        # 卷五十六 · 某天高价值原文下钻 · 点热力图格子拿当天 top 信号 (可追溯·宪法第5条)
        from workers.info_value import day_signals
        d = (date or "").strip()
        if not (len(d) == 10 and d[4] == "-" and d[7] == "-"):
            raise HTTPException(400, f"day_signals 需要 date=YYYY-MM-DD · 收到 {d!r}")
        vd = (vdomain or "").strip() or None
        if vd in ("all", "全部"):
            vd = None
        return day_signals(d, vd, limit=30)

    if domain == "trend_brief":
        # 卷五十六 P2 · 按月+领域的趋势研判 (绑 BRO 画像·带执行方案·可追溯)
        # refresh=true → 烧 token 现研判 (to_thread 别阻塞 event loop) · 否则读缓存
        from datetime import datetime as _dt
        from workers.trend_brief import generate_brief, load_brief
        mm = (domain_filter or "").strip()
        if mm:
            try:
                parts = mm.split("-")
                year, month = int(parts[0]), int(parts[1])
            except Exception:
                raise HTTPException(400, f"trend_brief domain_filter 期望 YYYY-MM · 收到 {mm!r}")
        else:
            now = _dt.now()
            year, month = now.year, now.month
        vd = (vdomain or "").strip() or None
        if vd in ("all", "全部"):
            vd = None
        if refresh:
            return await asyncio.to_thread(generate_brief, year, month, vd)
        cached = load_brief(year, month, vd)
        if cached:
            return cached
        return {"year": year, "month": month, "domain": vd or "all",
                "trends": [], "note": "还没研判 · 点「研判本月趋势」让 OPUS 看一遍"}

    raise HTTPException(404, f"unknown domain: {domain}")

# ──────────────────────────────────────────────────────────
# 卷四十四 K stage 2c · 出品工坊资产 endpoint · apps + flows
# ──────────────────────────────────────────────────────────

