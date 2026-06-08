"""
workers/radar_counts.py
=======================

卷五十八续 X · 信息雷达计数的【唯一真相源】

背景 (BRO 2026-06-06):
  工程里曾有 4 套并行计数口径——日历格子 / 日详情 / 边栏角标 / 雷达页 tab·
  各算各的·到处对不上 (251 vs 10·139 vs 133·+13)。 这个模块把
  "一条雷达 item 算哪天、算不算可见、今天新增几条" 收敛成单一实现·
  所有 UI 都引用它·不再各算各的。

口径 (BRO 2026-06-06 拍板 · 续 X 升级为首见台账):
  - 可见 visible : radar.json 全量 − feedback==hidden (BRO 主动藏的不算)
  - 归日 item_day: 首次见到 (radar_seen 台账) 优先 · fetched · published 兜底
  - 今日新增     : 首次见到落在【UTC 今天】(= 今天才冒出来的·非本轮抓取全部)
                  fetched_at 每轮刷新全重标·靠它会让"今日新增=刷新日全部"失真·
                  故改用 radar_seen 首见台账 (只给新 url 记当天)。
                  用 UTC 跟月历前端 toISOString().slice(0,10) 的"今天"对齐。
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

# 兜底领域是【实例配置】(母体 ai / 开源版 self-evolve)·不是代码常量。
try:
    from identity import default_domain as _default_domain
except Exception:
    def _default_domain():
        return "ai"

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RADAR_FILE = DATA_DIR / "radar.json"

logger = logging.getLogger("opus.radar_counts")


def _parse_day(s: str) -> Optional[date]:
    """容错把任意时间串解析成 date · 支持 ISO8601 (fetched_at) + RFC822 (published_at)。"""
    if not s:
        return None
    s = s.strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        pass
    try:
        return parsedate_to_datetime(s).date()
    except Exception:
        pass
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def _first_seen_map() -> dict:
    try:
        from workers.radar_seen import first_seen_map
        return first_seen_map()
    except Exception as e:
        logger.debug("first_seen_map unavailable: %s", e)
        return {}


def _item_id(item: dict) -> str:
    try:
        from workers.radar_feedback import item_id_for_url
        return item_id_for_url(item.get("url") or "")
    except Exception:
        return ""


def item_day(item: dict, *, seen_map: Optional[dict] = None) -> Optional[date]:
    """一条雷达 item 归到哪一天 · 首次见到(first_seen) 优先 · fetched · published 兜底。

    卷五十八续 X · 全工程统一调这个 (历史上 calendar_view 用 fetched、info_value 用
    published·又都没"首次见到"·埋了 251/139/+13 那堆坑)。
    seen_map 不传则自己加载 (单条调用方便·批量请传入避免每条都读盘)。
    """
    if seen_map is None:
        seen_map = _first_seen_map()
    if seen_map:
        fs = seen_map.get(_item_id(item))
        if fs:
            d = _parse_day(fs)
            if d:
                return d
    for key in ("fetched_at", "published_at"):
        d = _parse_day(item.get(key) or "")
        if d:
            return d
    return None


def visible_days(items: Optional[list[dict]] = None) -> list[date]:
    """所有可见条目的归日列表 (首次见到优先) · 给信息日历按天聚合用 · 只读一次 seen_map。"""
    seen_map = _first_seen_map()
    out: list[date] = []
    for it in visible_items(items):
        d = item_day(it, seen_map=seen_map)
        if d:
            out.append(d)
    return out


def _raw_items() -> list[dict]:
    if not RADAR_FILE.exists():
        return []
    try:
        return json.loads(RADAR_FILE.read_text(encoding="utf-8")).get("items") or []
    except Exception as e:
        logger.debug("load radar.json failed: %s", e)
        return []


def _hidden_ids() -> set[str]:
    try:
        from workers.radar_feedback import feedback_map
        return {iid for iid, e in feedback_map().items() if e.get("feedback") == "hidden"}
    except Exception as e:
        logger.debug("load hidden ids failed: %s", e)
        return set()


def visible_items(items: Optional[list[dict]] = None) -> list[dict]:
    """radar.json 全量 − feedback==hidden · 所有"总量/可见"口径的唯一来源。

    items 传了就基于它过滤 (省一次磁盘读)·不传就自己读 radar.json。
    """
    rows = items if items is not None else _raw_items()
    if not rows:
        return []
    hidden = _hidden_ids()
    if not hidden:
        return list(rows)
    try:
        from workers.radar_feedback import item_id_for_url
    except Exception:
        return list(rows)
    return [it for it in rows if item_id_for_url(it.get("url") or "") not in hidden]


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def radar_stats(items: Optional[list[dict]] = None, *, today: Optional[str] = None) -> dict:
    """一次性算全 · 给 cockpit 边栏 / 雷达页顶栏一次拿全 (单次遍历可见集合)。

    返回:
      - total               : 可见条数 (扣 hidden)
      - new_today           : 今天首次见到的可见条数 (全领域总和)
      - by_domain           : {domain: 可见条数} · 给雷达页分类 tab (修 139≠133)
      - new_today_by_domain : {domain: 今天首见条数} · 让"今日新增"能跟 tab 走
                              (BRO 2026-06-06: 切领域时今日新增也该是该领域的·别全领域总和混一格)
    """
    vis = visible_items(items)
    seen_map = _first_seen_map()
    target = _parse_day(today) if today else _today_utc()
    by_domain: dict[str, int] = {}
    new_today_by_domain: dict[str, int] = {}
    new_today = 0
    for it in vis:
        d = it.get("domain") or _default_domain()
        by_domain[d] = by_domain.get(d, 0) + 1
        if target and item_day(it, seen_map=seen_map) == target:
            new_today += 1
            new_today_by_domain[d] = new_today_by_domain.get(d, 0) + 1
    return {
        "total": len(vis),
        "new_today": new_today,
        "by_domain": by_domain,
        "new_today_by_domain": new_today_by_domain,
    }


def count_by_domain(items: Optional[list[dict]] = None) -> dict[str, int]:
    """按 domain 统计可见条数 · 给 info_radar.list_domains 用 (扣 hidden)。"""
    return radar_stats(items)["by_domain"]


def count_new_today(items: Optional[list[dict]] = None, *, today: Optional[str] = None) -> int:
    """今天 fetched 的可见条数。"""
    return radar_stats(items, today=today)["new_today"]
