"""
workers/calendar_view.py
========================

卷三十三 · 信息日历视图

BRO 卷三十三原话：
  「信息日历和今日趋势那个要有日历和折线图·最终实现周趋势·月趋势·
   来观察某一个点的发展趋势和市场相应」

这一版先做"日历格子"——按天聚合 radar / trends / reports / outcomes 的
事件量·让 BRO 一眼看见"哪一天信号最强、哪一天我做了什么决策"。

wish-4500c91c (2026-06-01) 加了 sessions 维度：
  - 扫描 data/sessions/*.jsonl · 按 user message 时间戳聚合"每天对话活跃度"
  - 这是 BRO 最频繁的活动——比 radar 抓取更能反映"每天都在做事"
  - radar 的 fetched_at 在一轮刷新里全标同一时间（合理——那是抓取日）
    所以如果长时间不刷新 radar，日历就靠 sessions 撑着不空

返回结构（一个月）：
  {
    "year": 2026, "month": 5,
    "days": [
      { "date": "2026-05-23", "weekday": 5,
        "radar": N, "trends": N, "reports": N, "outcomes": N, "sessions": N,
        "total": N }
    ],
    "totals": {radar, trends, reports, outcomes, sessions},
    "peak_day": "2026-05-23"
  }
"""
from __future__ import annotations

import calendar as _cal
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

logger = logging.getLogger("opus.calendar")


def _parse_iso_date(s: str) -> Optional[date]:
    """容错解析 · 任何 iso8601 串都先尝试·失败返回 None"""
    if not s:
        return None
    try:
        # 截前 10 个字符 = YYYY-MM-DD
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        pass
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def _iter_radar_dates() -> list[date]:
    """从 radar.json 拿可见条目的归日 · 卷五十八续 X 走唯一真相源 radar_counts
    (扣 hidden + fetched 优先归日)·让月历 radar 数跟边栏/雷达页同一口径。"""
    try:
        from workers.radar_counts import visible_days
        return visible_days()
    except Exception as e:
        logger.debug("radar dates via radar_counts failed: %s", e)
    # 兜底 (真相源不可用时退回旧逻辑·含 hidden)
    p = DATA_DIR / "radar.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    out2: list[date] = []
    for it in data.get("items") or []:
        d = _parse_iso_date(it.get("fetched_at") or it.get("published_at") or "")
        if d:
            out2.append(d)
    return out2


def count_sessions_on(day: str) -> int:
    """某一天 (YYYY-MM-DD) 的对话条数 · 给日详情单独显示用 (不进"共 N 件事"信息总数)。"""
    target = _parse_iso_date(day)
    if not target:
        return 0
    return sum(1 for d in _iter_sessions_dates() if d == target)


def _iter_trends_dates() -> list[date]:
    p = DATA_DIR / "trends.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    d = _parse_iso_date(data.get("generated_at") or "")
    if not d:
        return []
    count = len(data.get("trends") or [])
    return [d] * count


def _iter_reports_dates() -> list[date]:
    """报告 docx 落在 data/reports/ · 用文件 mtime 当日期"""
    p = DATA_DIR / "reports"
    if not p.exists():
        return []
    out: list[date] = []
    try:
        for f in p.glob("*.docx"):
            d = date.fromtimestamp(f.stat().st_mtime)
            out.append(d)
    except Exception as e:
        logger.debug("scan reports failed: %s", e)
    return out


def _iter_outcomes_dates() -> list[date]:
    """outcomes 每条 update 都算一个事件"""
    p = DATA_DIR / "outcomes"
    if not p.exists():
        return []
    out: list[date] = []
    try:
        for f in p.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            for u in d.get("updates") or []:
                dt = _parse_iso_date(u.get("at") or "")
                if dt:
                    out.append(dt)
            if not (d.get("updates") or []):
                dt = _parse_iso_date(d.get("created_at") or "")
                if dt:
                    out.append(dt)
    except Exception as e:
        logger.debug("scan outcomes failed: %s", e)
    return out


def _iter_sessions_dates() -> list[date]:
    """扫描 data/sessions/*.jsonl · 按每条 user message 的时间戳聚合

    每条 user message (role=user) 的日期算一次"会话活动"——
    这是 BRO 每天跟 OPUS 互动的真实痕迹，比 radar 抓取更能反映"每天都在做事"。

    返回: 每个 user message 一个 date（同一天多条 = 多个相同 date）"""
    p = ROOT / "sessions"
    if not p.exists():
        return []
    out: list[date] = []
    try:
        for f in sorted(p.glob("*.jsonl")):
            try:
                for line in f.read_text(encoding="utf-8").strip().split("\n"):
                    if not line:
                        continue
                    msg = json.loads(line)
                    if msg.get("role") != "user":
                        continue
                    ts = msg.get("ts") or msg.get("timestamp") or msg.get("created_at") or ""
                    d = _parse_iso_date(ts)
                    if d:
                        out.append(d)
            except Exception:
                continue
    except Exception as e:
        logger.debug("scan sessions failed: %s", e)
    return out


def build_calendar(year: int, month: int) -> dict:
    """组装某月的日历视图

    days 数组按"日历从周一开始"对齐——前面会有上个月的尾巴日（empty=True）
    后面会有下个月的开头日（empty=True）·让 UI 拿来直接画 7 列网格不用算偏移。
    """
    if month < 1 or month > 12:
        raise ValueError(f"month 越界: {month}")
    if year < 2000 or year > 2100:
        raise ValueError(f"year 越界: {year}")

    radar_dates = _iter_radar_dates()
    trends_dates = _iter_trends_dates()
    reports_dates = _iter_reports_dates()
    outcomes_dates = _iter_outcomes_dates()
    sessions_dates = _iter_sessions_dates()

    def _count_on(target: date, src: list[date]) -> int:
        return sum(1 for d in src if d == target)

    # 月内所有天
    last_day = _cal.monthrange(year, month)[1]
    days: list[dict] = []
    radar_sum = trends_sum = reports_sum = outcomes_sum = sessions_sum = 0
    peak_count = 0
    peak_day: Optional[str] = None

    # 前面补上个月尾巴（让周一对齐）
    first_dow = date(year, month, 1).weekday()  # 0=Mon
    if first_dow > 0:
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        prev_last = _cal.monthrange(prev_year, prev_month)[1]
        for i in range(first_dow):
            d = date(prev_year, prev_month, prev_last - first_dow + 1 + i)
            days.append({
                "date": d.isoformat(),
                "weekday": d.weekday(),
                "out_of_month": True,
                "radar": 0, "trends": 0, "reports": 0, "outcomes": 0, "sessions": 0,
                "total": 0,
            })

    for day in range(1, last_day + 1):
        d = date(year, month, day)
        r = _count_on(d, radar_dates)
        t = _count_on(d, trends_dates)
        rp = _count_on(d, reports_dates)
        oc = _count_on(d, outcomes_dates)
        se = _count_on(d, sessions_dates)
        # 卷五十八续 X · BRO 拍板: 对话(sessions)单独标记·不进"信息"总数/热力·
        # 否则 251 条对话淹没掉真正的信息(雷达/趋势)·BRO 看不懂格子。
        tot = r + t + rp + oc
        days.append({
            "date": d.isoformat(),
            "weekday": d.weekday(),
            "out_of_month": False,
            "radar": r, "trends": t, "reports": rp, "outcomes": oc,
            "sessions": se,
            "total": tot,
        })
        radar_sum += r
        trends_sum += t
        reports_sum += rp
        outcomes_sum += oc
        sessions_sum += se
        if tot > peak_count:
            peak_count = tot
            peak_day = d.isoformat()

    # 后面补下个月头几天 · 凑 7 的倍数
    while len(days) % 7 != 0:
        last_d = date.fromisoformat(days[-1]["date"])
        nxt = date(
            last_d.year + (1 if last_d.month == 12 else 0),
            (last_d.month % 12) + 1,
            1,
        ) if last_d.day == _cal.monthrange(last_d.year, last_d.month)[1] else date(
            last_d.year, last_d.month, last_d.day + 1,
        )
        days.append({
            "date": nxt.isoformat(),
            "weekday": nxt.weekday(),
            "out_of_month": True,
            "radar": 0, "trends": 0, "reports": 0, "outcomes": 0, "sessions": 0,
            "total": 0,
        })

    # 卷五十八续 VII · 节律 overlay (Layer2 周期仪式到期日) · 失败不影响日历主体
    rituals_summary: list[dict] = []
    try:
        from workers.rituals import get_rituals, rituals_for_month
        rituals_summary = get_rituals()
        month_marks = {r["date"]: r for r in rituals_for_month(year, month)}
        if month_marks:
            for d in days:
                if d.get("out_of_month"):
                    continue
                mark = month_marks.get(d["date"])
                if mark:
                    d["ritual"] = mark["id"]
                    d["ritual_label"] = mark["label"]
    except Exception as e:
        logger.debug("ritual overlay failed: %s", e)

    return {
        "year": year,
        "month": month,
        "days": days,
        "totals": {
            "radar": radar_sum,
            "trends": trends_sum,
            "reports": reports_sum,
            "outcomes": outcomes_sum,
            "sessions": sessions_sum,
        },
        "peak_day": peak_day,
        "peak_count": peak_count,
        "rituals": rituals_summary,
    }
