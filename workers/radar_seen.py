"""
workers/radar_seen.py
=====================

卷五十八续 X · 雷达条目的【首次见到台账】

为什么需要 (BRO 2026-06-06 拍板):
  refresh_radar 每轮把所有抓到的条目标同一个 fetched_at (本轮抓取时间)·
  所以 fetched_at 是"最近一次抓到"而非"第一次见到"。 没有"第一次见到"·
  "今日新增"在刷新当天 = 全部条目·失真。

  这个模块用 data/radar_seen.json 持久化每个条目 (item_id=md5(url)) 的
  首次见到时刻·refresh 后增量更新: 新 url 记当天·老 url 一律不动。
  从此"今日新增"= first_seen 落在今天的可见条数 = 真·今天才冒出来的。

一次性基线 (BRO 知情):
  第一次建库时现有条目都没记录 → record_seen 把它们全标"今天首次见到"。
  所以建库当天"今日新增"≈ 全量·从下一次刷新起才精确。

数据结构 data/radar_seen.json:
  { "updated_at": "...", "seen": { "<item_id>": "<first_seen_iso>" } }
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SEEN_FILE = DATA_DIR / "radar_seen.json"

logger = logging.getLogger("opus.radar_seen")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    if not SEEN_FILE.exists():
        return {"updated_at": None, "seen": {}}
    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        if not isinstance(data.get("seen"), dict):
            data["seen"] = {}
        return data
    except Exception as e:
        logger.warning("radar_seen.json corrupt: %s · 重置", e)
        return {"updated_at": None, "seen": {}}


def first_seen_map() -> dict[str, str]:
    """{item_id: first_seen_iso} · 给 radar_counts 归日 / 今日新增用。"""
    return _load().get("seen") or {}


def record_seen(items: Iterable[dict], *, now: Optional[str] = None) -> dict:
    """登记一批 item 的首次见到 · 新 item_id 记 now · 老的一律不动 (幂等)。

    items: 每个 dict 至少有 url。 返回 {"added": N, "total": M}。
    """
    try:
        from workers.radar_feedback import item_id_for_url
    except Exception as e:
        logger.warning("record_seen: item_id_for_url 不可用: %s", e)
        return {"added": 0, "total": 0, "error": str(e)}

    data = _load()
    seen = data.setdefault("seen", {})
    ts = now or _now_iso()
    added = 0
    for it in items or []:
        url = (it.get("url") or "").strip()
        if not url:
            continue
        iid = item_id_for_url(url)
        if iid and iid not in seen:
            seen[iid] = ts
            added += 1
    if added:
        _persist(data)
    return {"added": added, "total": len(seen)}


def _persist(data: dict) -> None:
    data["updated_at"] = _now_iso()
    try:
        from workers.safe_write import atomic_write_text
        atomic_write_text(
            SEEN_FILE,
            json.dumps(data, ensure_ascii=False, indent=2),
            backup=True,
        )
    except Exception as e:
        logger.warning("radar_seen write failed: %s", e)


def _published_day(item: dict) -> Optional[str]:
    """从 published_at 解析出【过去】的日期 iso (YYYY-MM-DD) · 失败/未来/缺失返回 None。"""
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime
    s = (item.get("published_at") or "").strip()
    if not s:
        return None
    d = None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        try:
            d = parsedate_to_datetime(s).date()
        except Exception:
            return None
    if d and d <= datetime.now(timezone.utc).date():
        return d.isoformat()
    return None


def backfill_existing(*, now: Optional[str] = None) -> dict:
    """一次性基线 (BRO 2026-06-06 拍板) · 给 radar.json 现有条目补首见日。

    只补还没记录的条目 · 取值: published_at 能解析成过去日 → 用它 (让基线当天
    日历按发表日展开·不全堆今天)·否则用 now (今天建库)。 之后真实 record_seen
    用当天·从下次刷新起精确。
    """
    from workers.radar_feedback import item_id_for_url
    radar_file = DATA_DIR / "radar.json"
    if not radar_file.exists():
        return {"added": 0, "total": 0, "note": "no radar.json"}
    try:
        items = json.loads(radar_file.read_text(encoding="utf-8")).get("items") or []
    except Exception as e:
        return {"added": 0, "total": 0, "error": str(e)}

    data = _load()
    seen = data.setdefault("seen", {})
    ts_now = now or _now_iso()
    added = 0
    for it in items:
        url = (it.get("url") or "").strip()
        if not url:
            continue
        iid = item_id_for_url(url)
        if iid and iid not in seen:
            pub = _published_day(it)
            seen[iid] = (pub + "T00:00:00+00:00") if pub else ts_now
            added += 1
    if added:
        _persist(data)
    return {"added": added, "total": len(seen)}
