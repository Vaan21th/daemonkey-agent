"""
api_routes/sinks_pulse_digest.py · 沉淀位 / 脉搏 / 今日动态 (wish-413999da · phase 1)
====================================================================================

6 路由 · 三组用 (共享一个文件 · 都属于 "BI/系统总览" 性质):

  GET  /sinks                    · 列所有沉淀位 (wish-149eab3f phase A)
  GET  /sinks/preview/{slug}     · markdown 在线预览
  POST /sinks/reveal/{slug}      · 本机外部应用打开

  GET  /api/pulse/stream         · 桌宠脉搏 SSE (wish-7330d23f)
  GET  /api/pulse/latest         · 最近 N 条 pulse 事件 (JSON)

  GET  /digest                   · BI 看板"今日动态" · 7 维度 24h 新增 (卷四十六续 10)
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from agent_tools._subprocess_helper import no_window_kwargs

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from api_routes._deps import check_auth


ROOT = Path(__file__).resolve().parent.parent


router = APIRouter()


# ────────────────────────────────────────────────────────────────
# 沉淀位地图 (wish-149eab3f · 16 文件沉淀位 + 1 虚拟「记忆库」)
# virtual=True 的位不是单文件·而是 FTS5 索引聚合 (卷五十八续 · 接通血管收尾)
# ────────────────────────────────────────────────────────────────
SINKS: dict[str, dict] = {
    "roadmap":           {"layer": "route",     "label": "ROADMAP",          "path": "ROADMAP.md",                       "role": "路线决策"},
    "captains-log":      {"layer": "history",   "label": "CAPTAINS-LOG",     "path": ".cursor/CAPTAINS-LOG.md",          "role": "工程史"},
    "sink-map":          {"layer": "meta",      "label": "SINK-MAP",         "path": ".cursor/SINK-MAP.md",              "role": "沉淀位地图"},
    "decisions":         {"layer": "meta",      "label": "DECISIONS",        "path": ".cursor/DECISIONS.md",             "role": "BRO 拍板归档"},
    "next-moves":        {"layer": "meta",      "label": "NEXT-MOVES",       "path": ".cursor/NEXT-MOVES.md",            "role": "短期看板 (半 archive)"},
    "self-evolution":    {"layer": "soul",      "label": "SELF-EVOLUTION",   "path": "soul/SELF-EVOLUTION.md",           "role": "OPUS 演化档案"},
    "bro-notebook":      {"layer": "soul",      "label": "BRO-NOTEBOOK",     "path": "soul/BRO-NOTEBOOK.md",             "role": "BRO 6 维画像"},
    "opus-memories":     {"layer": "soul",      "label": "OPUS-MEMORIES",    "path": "soul/OPUS-MEMORIES.md",            "role": "OPUS 自传"},
    "skill":             {"layer": "soul",      "label": "SKILL",            "path": "soul/SKILL.md",                    "role": "OPUS 角色入口"},
    "memory":            {"layer": "memory",    "label": "记忆库",            "path": "<live:fts5>",                      "role": "FTS5 跨会话记忆 · 对话摘要", "virtual": True},
    "product-design":    {"layer": "docs",      "label": "PRODUCT-DESIGN",   "path": "docs/PRODUCT-DESIGN.md",           "role": "产品宪法"},
    "architecture":      {"layer": "docs",      "label": "ARCHITECTURE",     "path": "docs/ARCHITECTURE.md",             "role": "工程架构"},
    "memory-architecture": {"layer": "docs",    "label": "MEMORY-ARCHITECTURE", "path": "docs/MEMORY-ARCHITECTURE.md",   "role": "记忆架构"},
    "daemon-guide":      {"layer": "docs",      "label": "DAEMON-GUIDE",     "path": "docs/DAEMON-GUIDE.md",             "role": "daemon 用户指南"},
    "quickstart":        {"layer": "docs",      "label": "QUICKSTART",       "path": "docs/QUICKSTART.md",               "role": "故障排查"},
    "agents":            {"layer": "entry",     "label": "AGENTS",           "path": "AGENTS.md",                        "role": "下根毛入口"},
    "readme":            {"layer": "entry",     "label": "README",           "path": "README.md",                        "role": "公开门面"},
}


def _resolve_sink(slug: str) -> "tuple[dict, Path]":
    if slug not in SINKS:
        raise HTTPException(404, f"unknown sink slug: {slug}")
    meta = SINKS[slug]
    path = (ROOT / meta["path"]).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        raise HTTPException(403, "path escapes project root")
    return meta, path


# ── 虚拟「记忆库」沉淀位 (卷五十八续 · 让 recall_memory 的库在面板里看得见) ──
_MEM_SOURCE_LABELS = {
    "BRO-NOTEBOOK": "📖 BRO 画像", "SELF-EVOLUTION": "📝 OPUS 演化档案",
    "OPUS-MEMORIES": "🧬 OPUS 自传", "SKILL": "⚙️ 灵魂入口",
    "session": "💬 对话记录", "session_summary": "🧠 对话摘要",
    "skill": "🛠️ playbook",
}


def _memory_stats() -> dict:
    """读 FTS5 索引统计 + db 文件元信息 (全只读·和在跑的 daemon 共享 db·WAL 安全)。"""
    try:
        from workers.memory_index import get_stats, DB_PATH
        st = get_stats()
        db = Path(str(DB_PATH))
        size = db.stat().st_size if db.exists() else 0
        mtime = int(db.stat().st_mtime) if db.exists() else 0
        return {"stats": st, "size": size, "mtime": mtime}
    except Exception as e:
        return {"stats": {"error": str(e), "total_chunks": 0, "by_source": []}, "size": 0, "mtime": 0}


def _virtual_sink_item(slug: str, meta: dict) -> dict:
    """给虚拟沉淀位拼 /sinks 列表项 (字段对齐文件位·前端通用渲染不用区分)。"""
    base = {
        "slug": slug, "label": meta["label"], "role": meta["role"],
        "layer": meta["layer"], "path": meta["path"],
        "exists": False, "size_bytes": 0, "mtime": 0, "lines": 0,
    }
    if slug == "memory":
        m = _memory_stats()
        st = m["stats"]
        total = st.get("total_chunks", 0)
        by = {r["source"]: r["chunks"] for r in st.get("by_source", [])}
        summ = by.get("session_summary", 0)
        role = f"{meta['role']} · {total} 片段"
        if summ:
            role += f" · {summ} 摘要"
        base.update({"role": role, "exists": total > 0, "size_bytes": m["size"], "mtime": m["mtime"]})
    return base


def _render_memory_markdown(max_summaries: int = 12) -> str:
    """合成「记忆库」预览 markdown: 各来源分布表 + 最近 N 条对话蒸馏摘要。"""
    from workers.memory_index import get_stats
    st = get_stats()
    total = st.get("total_chunks", 0)
    lines = ["# 记忆库 · FTS5 跨会话记忆", ""]
    if st.get("error"):
        lines.append(f"> <i class='ri-error-warning-fill'></i> {st['error']}")
        lines.append("")
    lines += [
        f"_OPUS 用 `recall_memory` 工具能搜到的长期记忆 · 索引片段总数 **{total}**_",
        "",
        "## 各来源分布",
        "",
        "| 来源 | 片段数 | tokens |",
        "|---|---|---|",
    ]
    for r in st.get("by_source", []):
        lab = _MEM_SOURCE_LABELS.get(r["source"], r["source"])
        lines.append(f"| {lab} | {r['chunks']} | {r.get('tokens', 0)} |")
    lines += ["", "## 最近的对话摘要 (蒸馏)", ""]

    sess_dir = ROOT / "sessions"
    files = []
    if sess_dir.exists():
        files = sorted(
            sess_dir.glob("*.summary.json"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )[:max_summaries]
    if not files:
        lines.append("_(还没有对话摘要 · 对话累积到一定长度后 auto_compress 会自动蒸馏)_")
    for sf in files:
        try:
            entries = json.loads(sf.read_text(encoding="utf-8")) or []
        except Exception:
            continue
        if not entries:
            continue
        last = entries[-1]
        sid = sf.name[: -len(".summary.json")]
        when = last.get("compressed_at", "")
        summ = (last.get("summary") or "").strip()
        lines.append(f"### 💬 {sid}")
        if when:
            lines.append(f"_{when}_")
        lines.append("")
        lines.append(summ[:500] + ("..." if len(summ) > 500 else ""))
        kf = last.get("key_facts") or []
        if isinstance(kf, list) and kf:
            lines.append("")
            lines.append("**关键事实**: " + " · ".join(str(f) for f in kf[:6]))
        lines.append("")
    lines += [
        "---", "",
        "> 灵魂文档 (BRO 画像 / 日记 / 自传) 各自也是独立沉淀位卡 · 这里聚合整个 FTS5 索引 + 对话蒸馏摘要 · "
        "「本机打开」会弹出 `sessions/` 原始文件夹。",
    ]
    return "\n".join(lines)


@router.get("/sinks")
async def list_sinks(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = None,
):
    """列所有沉淀位 · 带 size + mtime + exists · 给 WebUI 卡片群用。"""
    if token and not authorization:
        authorization = f"Bearer {token}"
    check_auth(authorization)
    items: list[dict] = []
    for slug, meta in SINKS.items():
        if meta.get("virtual"):
            items.append(_virtual_sink_item(slug, meta))
            continue
        path = (ROOT / meta["path"])
        exists = path.exists() and path.is_file()
        stat = path.stat() if exists else None
        items.append({
            "slug": slug,
            "label": meta["label"],
            "role": meta["role"],
            "layer": meta["layer"],
            "path": meta["path"],
            "exists": exists,
            "size_bytes": stat.st_size if stat else 0,
            "mtime": int(stat.st_mtime) if stat else 0,
            "lines": (sum(1 for _ in path.open(encoding="utf-8", errors="replace")) if exists else 0),
        })
    layers = sorted({m["layer"] for m in SINKS.values()})
    return {"ok": True, "count": len(items), "items": items, "layers": layers}


@router.get("/sinks/preview/{slug}")
async def preview_sink(
    slug: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = None,
    max_bytes: int = 200_000,
):
    """沉淀位 markdown 在线预览 · 给 webui mdRender。 超 max_bytes 截断 + 提示。"""
    if token and not authorization:
        authorization = f"Bearer {token}"
    check_auth(authorization)

    # 虚拟「记忆库」: 不读文件·实时合成 markdown
    if SINKS.get(slug, {}).get("virtual"):
        meta = SINKS[slug]
        md = _render_memory_markdown() if slug == "memory" else "(虚拟沉淀位 · 暂无预览)"
        return {
            "ok": True, "slug": slug, "label": meta["label"], "layer": meta["layer"],
            "role": meta["role"], "path": meta["path"], "markdown": md,
            "size_bytes": len(md.encode("utf-8")), "mtime": int(time.time()), "truncated": False,
        }

    meta, path = _resolve_sink(slug)
    if not path.exists():
        raise HTTPException(404, f"sink file not found: {meta['path']}")
    raw = path.read_text(encoding="utf-8", errors="replace")
    truncated = False
    if len(raw.encode("utf-8")) > max_bytes:
        raw = raw.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
        raw += f"\n\n---\n\n> <i class='ri-error-warning-fill'></i> 文件超过 {max_bytes // 1000}KB · 仅预览前段 · 完整内容用『本地打开』。"
        truncated = True
    return {
        "ok": True,
        "slug": slug,
        "label": meta["label"],
        "layer": meta["layer"],
        "role": meta["role"],
        "path": meta["path"],
        "markdown": raw,
        "size_bytes": path.stat().st_size,
        "mtime": int(path.stat().st_mtime),
        "truncated": truncated,
    }


@router.post("/sinks/reveal/{slug}")
async def reveal_sink(
    slug: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = None,
):
    """本机外部应用打开 · 仅 daemon 跟 BRO 在同一台机器时有意义。"""
    if token and not authorization:
        authorization = f"Bearer {token}"
    check_auth(authorization)

    # 虚拟「记忆库」: 没有单文件·弹出 sessions/ 原始文件夹
    if SINKS.get(slug, {}).get("virtual"):
        meta = SINKS[slug]
        target = ROOT / "sessions"
        try:
            if os.name == "nt":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)], **no_window_kwargs())
            else:
                subprocess.Popen(["xdg-open", str(target)], **no_window_kwargs())
            return {"ok": True, "slug": slug, "path": "sessions/", "method": os.name}
        except Exception as e:
            return {"ok": False, "slug": slug, "path": "sessions/", "error": f"{type(e).__name__}: {e}"}

    meta, path = _resolve_sink(slug)
    if not path.exists():
        raise HTTPException(404, f"sink file not found: {meta['path']}")
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)], **no_window_kwargs())
        else:
            subprocess.Popen(["xdg-open", str(path)], **no_window_kwargs())
        return {"ok": True, "slug": slug, "path": meta["path"], "method": os.name}
    except Exception as e:
        return {
            "ok": False,
            "slug": slug,
            "path": meta["path"],
            "error": f"{type(e).__name__}: {e}",
            "fallback_hint": "前端可改用预览或下载 (未实) · 浏览器走默认应用",
        }


# ────────────────────────────────────────────────────────────────
# OPUS 脉搏 (wish-7330d23f) · 桌宠 / WebUI 副屏读 daemon 工作活动
# ────────────────────────────────────────────────────────────────
@router.get("/api/pulse/stream")
async def pulse_stream(
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    probe: Optional[str] = Query(None),
):
    """SSE endpoint: real-time daemon pulse events for secondary screen."""
    if token and not authorization:
        authorization = f"Bearer {token}"
    check_auth(authorization)

    # 内部诊断 probe · 仅 verify_daemon_endpoints smoke test 用
    # 返回即时 JSON · 不进 SSE 循环。正常副屏连接不应传此参数。
    if probe == "1":
        try:
            from desktop_pet.activities import read_last_events as _re
            _events = _re(5)
        except Exception:
            # desktop_pet 未装（Daemonkey 开源版没有桌宠外设）→ 空事件
            _events = []
        return {
            "status": "ok",
            "endpoint": "/api/pulse/stream",
            "events_count": len(_events),
            "note": "internal health-check probe — not a public API parameter",
        }

    async def event_generator():
        # 立即发连接帧——让 SSE 客户端和 smoke test 不用等 (wish-4b16633d SSE 盲点修)
        yield f"data: {json.dumps({'type': 'connected'})}\n\n"

        # desktop_pet 未装（Daemonkey 开源版没有桌宠外设）→ 退化成空事件流·别让 SSE 整个崩掉
        try:
            from desktop_pet.activities import read_last_events
        except Exception:
            def read_last_events(_n: int = 5):
                return []
        last_ts = 0.0
        try:
            events = read_last_events(5)
            if events:
                last_ts = events[-1].get("ts", 0)
                yield f"data: {json.dumps({'events': events}, ensure_ascii=False)}\n\n"
        except Exception:
            pass

        while True:
            try:
                await asyncio.sleep(1.5)
                events = read_last_events(5)
                if events:
                    latest_ts = events[-1].get("ts", 0)
                    if latest_ts > last_ts:
                        last_ts = latest_ts
                        new_events = [e for e in events if e.get("ts", 0) > last_ts - 10]
                        yield f"data: {json.dumps({'events': new_events}, ensure_ascii=False)}\n\n"
            except Exception:
                await asyncio.sleep(5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/pulse/latest")
async def pulse_latest(
    n: int = Query(20, ge=1, le=100),
    authorization: Optional[str] = Header(None),
):
    """Return last N pulse events as JSON (for initial page load)."""
    check_auth(authorization)
    from desktop_pet.activities import read_last_events
    events = read_last_events(n)
    return {"ok": True, "events": events, "count": len(events)}


# ────────────────────────────────────────────────────────────────
# BI 看板"今日动态" (卷四十六续 10) · 过去 24h 7 维度新增
# ────────────────────────────────────────────────────────────────
@router.get("/digest")
async def dashboard_digest(
    hours: int = 24,
    authorization: Optional[str] = Header(None),
):
    """过去 N 小时 (默认 24) 各 dashboard 新增 · BI 看板"今日动态"卡用"""
    check_auth(authorization)
    hours = max(1, min(int(hours or 24), 168))
    now = time.time()
    threshold = now - hours * 3600

    def _parse_iso(s: str) -> float:
        if not s:
            return 0
        try:
            t = s.replace("T", " ").split(".")[0].split("+")[0].strip()
            if len(t) >= 19:
                return time.mktime(time.strptime(t[:19], "%Y-%m-%d %H:%M:%S"))
            if len(t) == 10:
                return time.mktime(time.strptime(t, "%Y-%m-%d"))
        except Exception:
            pass
        return 0

    items: list[dict] = []

    try:
        from workers.info_radar import load_radar
        radar = load_radar()
        r_items = radar.get("items") or []
        new_radar = [it for it in r_items if _parse_iso(it.get("fetched_at", "")) >= threshold]
        by_domain: dict = {}
        for it in new_radar:
            d = it.get("domain") or "?"
            by_domain[d] = by_domain.get(d, 0) + 1
        top = sorted(by_domain.items(), key=lambda x: -x[1])[:2]
        highlight = " · ".join(f"{d} +{n}" for d, n in top) if top else ""
        items.append({
            "domain": "radar", "label": "信息雷达", "icon": "<i class='ri-radar-fill'></i>",
            "new_count": len(new_radar),
            "total": len(r_items),
            "highlight": highlight,
        })
    except Exception as e:
        items.append({"domain": "radar", "label": "信息雷达", "icon": "<i class='ri-radar-fill'></i>",
                      "new_count": 0, "total": 0, "error": str(e)})

    try:
        from workers.trend_finder import load_trends
        trends = load_trends()
        gen_at = trends.get("generated_at") or ""
        t_items = trends.get("trends") or []
        is_fresh = _parse_iso(gen_at) >= threshold
        top_trend = ""
        if t_items:
            strongest = max(t_items, key=lambda t: int(t.get("intensity") or 0))
            top_trend = f"《{(strongest.get('title') or '?')[:30]}》强度 {strongest.get('intensity', '?')}/5"
        items.append({
            "domain": "trends", "label": "今日趋势", "icon": "<i class='ri-line-chart-fill'></i>",
            "new_count": len(t_items) if is_fresh else 0,
            "total": len(t_items),
            "highlight": top_trend if is_fresh else "无更新",
        })
    except Exception as e:
        items.append({"domain": "trends", "label": "今日趋势", "icon": "<i class='ri-line-chart-fill'></i>",
                      "new_count": 0, "total": 0, "error": str(e)})

    try:
        reports_dir = ROOT / "data" / "reports"
        new_reports = []
        total_reports = 0
        if reports_dir.exists():
            for p in reports_dir.glob("*.docx"):
                if p.name.startswith("~$"):
                    continue
                total_reports += 1
                if p.stat().st_mtime >= threshold:
                    new_reports.append(p.name)
        highlight = new_reports[0][:40] if new_reports else ""
        items.append({
            "domain": "reports", "label": "报告库", "icon": "<i class='ri-article-fill'></i>",
            "new_count": len(new_reports),
            "total": total_reports,
            "highlight": highlight,
        })
    except Exception as e:
        items.append({"domain": "reports", "label": "报告库", "icon": "<i class='ri-article-fill'></i>",
                      "new_count": 0, "total": 0, "error": str(e)})

    try:
        opps_file = ROOT / "data" / "opportunities.json"
        total_opps = 0
        new_opps = 0
        top_opp = ""
        if opps_file.exists():
            opps_data = json.loads(opps_file.read_text(encoding="utf-8"))
            opps = opps_data.get("opportunities") or []
            total_opps = len(opps)
            gen_at = opps_data.get("generated_at") or ""
            if _parse_iso(gen_at) >= threshold:
                new_opps = len(opps)
                if opps:
                    best = max(opps, key=lambda o: int(o.get("recommend") or 0))
                    star_icon = '<i class=\'ri-star-fill\'></i>'
                    top_opp = f"{star_icon * (best.get('recommend') or 3)} {(best.get('title') or '?')[:30]}"
        items.append({
            "domain": "opportunities", "label": "掘金机会", "icon": "<i class='ri-diamond-fill'></i>",
            "new_count": new_opps,
            "total": total_opps,
            "highlight": top_opp,
        })
    except Exception as e:
        items.append({"domain": "opportunities", "label": "掘金机会", "icon": "<i class='ri-diamond-fill'></i>",
                      "new_count": 0, "total": 0, "error": str(e)})

    try:
        feas_dir = ROOT / "data" / "feasibility"
        new_feas = []
        total_feas = 0
        if feas_dir.exists():
            for p in feas_dir.glob("*.json"):
                total_feas += 1
                if p.stat().st_mtime >= threshold:
                    new_feas.append(p.stem)
        items.append({
            "domain": "feasibility", "label": "可行性分析", "icon": "<i class='ri-bar-chart-fill'></i>",
            "new_count": len(new_feas),
            "total": total_feas,
            "highlight": new_feas[0][:40] if new_feas else "",
        })
    except Exception as e:
        items.append({"domain": "feasibility", "label": "可行性分析", "icon": "<i class='ri-bar-chart-fill'></i>",
                      "new_count": 0, "total": 0, "error": str(e)})

    try:
        wishes_file = ROOT / "data" / "opus_wishlist.json"
        new_wishes = []
        total_wishes = 0
        if wishes_file.exists():
            wd = json.loads(wishes_file.read_text(encoding="utf-8"))
            ws = wd.get("wishes") or []
            total_wishes = len(ws)
            for w in ws:
                if _parse_iso(w.get("created_at", "")) >= threshold:
                    new_wishes.append(w.get("title", "?")[:40])
        items.append({
            "domain": "wishlist", "label": "OPUS 心愿单", "icon": "<i class='ri-lightbulb-fill'></i>",
            "new_count": len(new_wishes),
            "total": total_wishes,
            "highlight": new_wishes[0] if new_wishes else "",
        })
    except Exception as e:
        items.append({"domain": "wishlist", "label": "OPUS 心愿单", "icon": "<i class='ri-lightbulb-fill'></i>",
                      "new_count": 0, "total": 0, "error": str(e)})

    try:
        wk_total = 0
        wk_new: list[str] = []
        for sub in ["content", "design", "dev", "docs"]:
            d = ROOT / "data" / sub
            if not d.exists():
                continue
            for p in d.glob("*.md"):
                wk_total += 1
                if p.stat().st_mtime >= threshold:
                    wk_new.append(f"{sub}/{p.stem[:30]}")
        items.append({
            "domain": "workshop", "label": "出品工坊", "icon": "<i class='ri-magic-fill'></i>",
            "new_count": len(wk_new),
            "total": wk_total,
            "highlight": wk_new[0] if wk_new else "",
        })
    except Exception as e:
        items.append({"domain": "workshop", "label": "出品工坊", "icon": "<i class='ri-magic-fill'></i>",
                      "new_count": 0, "total": 0, "error": str(e)})

    total_new = sum(it["new_count"] for it in items)
    return {
        "ok": True,
        "since_hours": hours,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "items": items,
        "totals": {
            "new_items": total_new,
            "domains_with_new": sum(1 for it in items if it["new_count"] > 0),
        },
    }
