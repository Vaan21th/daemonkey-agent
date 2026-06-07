"""
workers/info_value.py
=====================

卷五十六 · 2026-06-03 · 信息价值层

为什么有这玩意 (BRO 卷五十六定调):
    BI 热力图 / 信号流以前全是"计数"——抓了多少条。BRO 要的是"价值":
    高价值信息 → 色块变深 → 点进去看当天高分原文。 计数 → 价值·这是地基。

价值分 = 规则版合成 (0 LLM · 即时 · 主体是纯函数):
    BASE
    + 源权重     (硬源高: arxiv/MIT TR/HN · 聚合杂源低)
    + 新鲜度     (越新越高·14 天指数衰减)
    + 反馈加成   (⭐ +40 / 👍 +20 / 👎 -100 / 🗑 -100 · BRO 的人工价值信号最重)
    - 软文惩罚   (medium -8 / high -22 · 复用 workers.softness_score)
    → clamp 到 [0, 100]

去重 (卷五十六信源审计发现): 跨源会抓到同一条 (实测 Cyera/Uber x2)。
    聚合价值密度时按标题归一去重·不让转载把热力刷虚高。

红线:
    - 纯计算·只读 radar.json + radar_feedback + softness_score·不写盘·不调 LLM
    - 单条算分失败不抛·返回 BASE 兜底·绝不炸调用方 (热力图/信号流)
"""
from __future__ import annotations

import logging
import math
import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger("opus.info_value")

BASE = 10

# 源权重 · 没列到的走 DEFAULT_SOURCE_WEIGHT
# 原则: 研究/权威长文 > 主流科技媒体 > 社区/聚合 > newsletter 转载
SOURCE_WEIGHT: dict[str, int] = {
    "arxiv-ai": 22, "arxiv-cl": 22,
    "mit-tr-ai": 20, "huggingface-blog": 18,
    "gh-anthropic-sdk": 18, "gh-openhands": 16, "gh-autogen": 14,
    "hn": 14, "decoder": 14,
    "tc-ai": 12, "venturebeat-ai": 12, "infoq-cn": 12,
    "ih": 12, "gh-trending-python": 12, "gh-trending-ts": 10,
    "sspai": 10, "ph": 8, "ben-s-bites": 6,
}
DEFAULT_SOURCE_WEIGHT = 10

# 反馈加成 · BRO 的人工信号·权重最高 (一条 👎 能把价值打到地板)
FEEDBACK_DELTA: dict[str, int] = {
    "starred": 40,
    "thumbs_up": 20,
    "thumbs_down": -100,
    "hidden": -100,
}

# 软文惩罚 · 复用 softness_score 的 level
SOFTNESS_PENALTY: dict[str, int] = {"low": 0, "medium": 8, "high": 22}

_WS_RE = re.compile(r"\s+")


def _parse_dt(s: str) -> Optional[datetime]:
    """容错解析任意时间串 → aware datetime (UTC)。 RFC822 + ISO 都吃。"""
    if not s:
        return None
    s = s.strip()
    # RFC822 (RSS pubDate: 'Tue, 19 May 2026 13:01:25 GMT')
    try:
        dt = parsedate_to_datetime(s)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    # ISO8601 (fetched_at / Atom updated)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def item_date(item: dict, *, seen_map: Optional[dict] = None) -> Optional[date]:
    """一条 item 归到哪一天 · 首见(first_seen)优先 → fetched → published。

    卷五十八续 X 修正 · 走 radar_counts.item_day 同一台账。
    纯 fetched 会让所有条目归到本轮抓取那天 (fetched 每轮全重标)·
    价值热力图就全堆今天 (BRO 实测 regression)。 首见台账让它按真实出现日展开。
    批量调用 (build_value_calendar) 请把 seen_map 传进来·避免每条读盘。
    """
    try:
        from workers.radar_counts import item_day
        d = item_day(item, seen_map=seen_map)
        if d:
            return d
    except Exception:
        pass
    for key in ("fetched_at", "published_at"):
        dt = _parse_dt(item.get(key) or "")
        if dt:
            return dt.astimezone(timezone.utc).date()
    return None


def _freshness(item: dict, now: Optional[datetime] = None) -> int:
    """越新越高 · 14 天半衰期指数衰减 · 上限 ~20"""
    dt = _parse_dt(item.get("published_at") or "") or _parse_dt(item.get("fetched_at") or "")
    if not dt:
        return 0
    now = now or datetime.now(timezone.utc)
    days = max(0.0, (now - dt).total_seconds() / 86400.0)
    return int(round(20 * math.exp(-days / 14.0)))


def _source_weight(item: dict) -> int:
    return SOURCE_WEIGHT.get(item.get("source") or "", DEFAULT_SOURCE_WEIGHT)


def _feedback_delta(item: dict, fb_map: Optional[dict] = None) -> int:
    """BRO 在这条上打过的标 → 加/减分。 fb_map 传进来批量算时省去重复读盘。"""
    url = item.get("url") or ""
    if not url:
        return 0
    try:
        from workers.radar_feedback import item_id_for_url
        iid = item_id_for_url(url)
    except Exception:
        return 0
    entry = None
    if fb_map is not None:
        entry = fb_map.get(iid)
    else:
        try:
            from workers.radar_feedback import get_feedback
            entry = get_feedback(iid)
        except Exception:
            entry = None
    if not entry:
        return 0
    return FEEDBACK_DELTA.get(entry.get("feedback") or "", 0)


def _softness_penalty(item: dict) -> int:
    try:
        from workers.softness_score import softness_score
        level = softness_score(item).get("level", "low")
    except Exception:
        level = "low"
    return SOFTNESS_PENALTY.get(level, 0)


def item_value(
    item: dict,
    *,
    now: Optional[datetime] = None,
    fb_map: Optional[dict] = None,
) -> int:
    """一条 radar item 的价值分 [0,100]。 失败兜底返回 BASE·绝不抛。"""
    try:
        v = (
            BASE
            + _source_weight(item)
            + _freshness(item, now)
            + _feedback_delta(item, fb_map)
            - _softness_penalty(item)
        )
        return max(0, min(100, int(round(v))))
    except Exception as e:  # noqa: BLE001
        logger.debug("item_value failed: %s", e)
        return BASE


def _norm_title(item: dict) -> str:
    """标题归一 · 跨源去重用 (转载常常标题一字不差)"""
    t = (item.get("title") or item.get("title_zh") or "").strip().lower()
    return _WS_RE.sub(" ", t)


def _load_radar_items() -> list[dict]:
    try:
        from workers.info_radar import load_radar
        return load_radar().get("items") or []
    except Exception as e:  # noqa: BLE001
        logger.debug("load radar items failed: %s", e)
        return []


def _fb_map() -> dict:
    try:
        from workers.radar_feedback import feedback_map
        return feedback_map()
    except Exception:
        return {}


def build_value_calendar(year: int, month: int, domain: Optional[str] = None) -> dict:
    """按价值聚合的月历 · 给 BI 热力图按价值深浅着色用。

    每天: value(当天去重后 item 价值之和) / count / peak(最高分那条的标题)。
    domain 不传 = 全部领域; 传了只算该领域 item。
    days 数组从周一对齐·前后补 out_of_month 空格·UI 直接画 7 列。
    """
    if not (1 <= month <= 12) or not (2000 <= year <= 2100):
        raise ValueError(f"年月越界: {year}-{month}")

    items_all = _load_radar_items()
    fb = _fb_map()
    now = datetime.now(timezone.utc)
    # 卷五十八续 X 修正 · 首见台账只读一次·传给每条 item_date·热力图按真实出现日展开
    try:
        from workers.radar_seen import first_seen_map
        seen_map = first_seen_map()
    except Exception:
        seen_map = {}

    # 本月所有 item (按选中领域过滤之前 · 用来生成领域 tab)
    month_items = [it for it in items_all
                   if (lambda dd: dd and dd.year == year and dd.month == month)(item_date(it, seen_map=seen_map))]

    try:
        from workers.info_radar import DOMAIN_META
    except Exception:  # noqa: BLE001
        DOMAIN_META = {}
    dom_counts: dict[str, int] = {}
    for it in month_items:
        dkey = it.get("domain") or "self-evolve"
        dom_counts[dkey] = dom_counts.get(dkey, 0) + 1
    domains = [{"id": "all", "label": "全部", "icon": "🌐", "color": "#9f7aea",
                "count": len(month_items)}]
    for did, cnt in sorted(dom_counts.items(), key=lambda kv: -kv[1]):
        meta = DOMAIN_META.get(did, {})
        domains.append({"id": did, "label": meta.get("label", did),
                        "icon": meta.get("icon", "🔖"),
                        "color": meta.get("color", "#888"), "count": cnt})

    items = month_items if not domain else [
        it for it in month_items if (it.get("domain") or "self-evolve") == domain]

    # date -> {seen_titles, value, count, peak_value, peak_title}
    buckets: dict[str, dict] = {}
    for it in items:
        d = item_date(it, seen_map=seen_map)
        if not d:
            continue
        key = d.isoformat()
        b = buckets.setdefault(key, {"titles": set(), "value": 0, "count": 0,
                                     "peak_value": -1, "peak_title": ""})
        nt = _norm_title(it)
        if len(nt) >= 20 and nt in b["titles"]:
            continue  # 跨源转载·同一天同标题只算一次
        if len(nt) >= 20:
            b["titles"].add(nt)
        v = item_value(it, now=now, fb_map=fb)
        b["value"] += v
        b["count"] += 1
        if v > b["peak_value"]:
            b["peak_value"] = v
            b["peak_title"] = it.get("title_zh") or it.get("title") or ""

    import calendar as _cal
    last_day = _cal.monthrange(year, month)[1]
    days: list[dict] = []
    max_value = 0
    total_value = 0
    total_count = 0
    peak_day = None
    peak_day_value = -1

    first_dow = date(year, month, 1).weekday()  # 0=Mon
    for _ in range(first_dow):
        days.append({"date": "", "out_of_month": True, "value": 0, "count": 0})

    for day in range(1, last_day + 1):
        d = date(year, month, day)
        key = d.isoformat()
        b = buckets.get(key)
        val = b["value"] if b else 0
        cnt = b["count"] if b else 0
        days.append({
            "date": key,
            "weekday": d.weekday(),
            "out_of_month": False,
            "value": val,
            "count": cnt,
            "peak_value": (b["peak_value"] if (b and b["peak_value"] > 0) else 0),
            "peak_title": (b["peak_title"][:60] if b else ""),
        })
        max_value = max(max_value, val)
        total_value += val
        total_count += cnt
        if val > peak_day_value:
            peak_day_value = val
            peak_day = key

    while len(days) % 7 != 0:
        days.append({"date": "", "out_of_month": True, "value": 0, "count": 0})

    active_days = sum(1 for d in days if not d.get("out_of_month") and d.get("count"))

    # 卷五十八续 VII · 节律 overlay (Layer2 周期仪式到期日) · 失败不影响热力图主体
    rituals_summary: list[dict] = []
    try:
        from workers.rituals import get_rituals, rituals_for_month
        rituals_summary = get_rituals()
        month_marks = {r["date"]: r for r in rituals_for_month(year, month)}
        if month_marks:
            for d in days:
                if d.get("out_of_month"):
                    continue
                mark = month_marks.get(d.get("date"))
                if mark:
                    d["ritual"] = mark["id"]
                    d["ritual_label"] = mark["label"]
    except Exception:
        pass

    return {
        "year": year,
        "month": month,
        "domain": domain or "all",
        "domains": domains,
        "days": days,
        "max_value": max_value,
        "total_value": total_value,
        "total_count": total_count,
        "active_days": active_days,
        "peak_day": peak_day if peak_day_value > 0 else None,
        "rituals": rituals_summary,
    }


def day_signals(date_str: str, domain: Optional[str] = None, limit: int = 20) -> dict:
    """某一天的高价值原文 · 给热力图点击下钻用 (可追溯·宪法第5条)。

    返回当天 item 按价值降序 · 带 url/源/价值/反馈 · BRO 顺着看原文 + 当场打标。
    """
    target = None
    try:
        target = date.fromisoformat(date_str[:10])
    except Exception:
        return {"date": date_str, "items": [], "error": "日期格式错"}

    items = _load_radar_items()
    if domain:
        items = [it for it in items if (it.get("domain") or "self-evolve") == domain]
    fb = _fb_map()
    now = datetime.now(timezone.utc)
    try:
        from workers.radar_seen import first_seen_map
        seen_map = first_seen_map()
    except Exception:
        seen_map = {}

    try:
        from workers.radar_feedback import item_id_for_url
    except Exception:
        item_id_for_url = None  # type: ignore

    rows: list[dict] = []
    seen: set[str] = set()
    for it in items:
        if item_date(it, seen_map=seen_map) != target:
            continue
        nt = _norm_title(it)
        if len(nt) >= 20 and nt in seen:
            continue
        if len(nt) >= 20:
            seen.add(nt)
        url = it.get("url") or ""
        iid = item_id_for_url(url) if (item_id_for_url and url) else ""
        entry = fb.get(iid) if iid else None
        rows.append({
            "item_id": iid,
            "title": it.get("title_zh") or it.get("title") or "(无标题)",
            "title_en": it.get("title") or "",
            "url": url,
            "source": it.get("source_display") or it.get("source") or "",
            "domain": it.get("domain") or "self-evolve",
            "value": item_value(it, now=now, fb_map=fb),
            "summary": (it.get("summary_zh") or it.get("summary") or "")[:200],
            "feedback": (entry.get("feedback") if entry else None),
        })

    rows.sort(key=lambda r: r["value"], reverse=True)
    return {"date": target.isoformat(), "domain": domain or "all",
            "total": len(rows), "items": rows[:limit]}
