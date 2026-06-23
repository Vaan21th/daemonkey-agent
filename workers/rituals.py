"""
workers/rituals.py
==================

卷五十八续 VII · wish-149eab3f phase B · 周期仪式(节律)到期表

月度 review / 能力镜像刷新 这类周期仪式·过去没有任何东西盯着它们到期·
BRO 原话「月度 review 那个·我也一直不知道他会怎么触发」。 这个模块把它们的
下次到期日 + 状态算出来·给信息日历当 overlay —— 让 Layer2 仪式从"没人盯"
变成"看得见、点得动"。

数据源(全只读):
  - data/reviews/*.md           · 最近一份月度复盘 (status / period_end)
  - data/bro_capability_snapshot.md · 能力镜像最近生成日 (mtime)
  - env OPUS_CAPABILITY_MIRROR_INTERVAL_DAYS · 镜像周期自驱开关

纯计算·不调 LLM·不写盘·失败优雅降级。 触发本身仍走 NLP (前端按钮发 prompt →
OPUS 调 monthly_review / mirror_capability 工具)·这里只负责"显示节律"。
"""
from __future__ import annotations

import calendar as _cal
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

# 月度 review 锚点 —— 开源版：每个用户的起点不同·从他『相遇』完成那天 +1 个月起算·
# 之后每月同一号。BRO 2026-06-07 决议：不写死 23 号 (那是母体自己的周期)。
ONBOARDING_FILE = ROOT / "soul" / "onboarding.json"


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _safe_date(year: int, month: int, day: int) -> date:
    """构造 date · day 超过当月天数时夹到月末 (纯防御)。"""
    last = _cal.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def _add_month(d: date) -> date:
    """往后推一个自然月 · 日超过当月天数时夹到月末。"""
    y = d.year + (1 if d.month == 12 else 0)
    m = 1 if d.month == 12 else d.month + 1
    return _safe_date(y, m, d.day)


def _anchor() -> date:
    """关系起点 = 用户『相遇』完成那天 (soul/onboarding.json completed_at)。
    还没相遇就回退到今天 (不报错·相遇一完成就自动校正)。"""
    try:
        if ONBOARDING_FILE.exists():
            s = (json.loads(ONBOARDING_FILE.read_text(encoding="utf-8-sig")).get("completed_at") or "").strip()
            if s:
                return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        pass
    return _today()


def _first_due() -> date:
    """第一次月度 review = 相遇 + 1 个月。"""
    return _add_month(_anchor())


def _review_dom() -> int:
    """review 落在每月的几号 = 相遇那天的号数。"""
    return _anchor().day


def _next_review_due(today: Optional[date] = None) -> date:
    """下次月度 review 到期日 = 从首次到期 (相遇+1月) 起逐月递推、不早于今天的那天。"""
    today = today or _today()
    due = _first_due()
    while due < today:
        due = _add_month(due)
    return due


def _review_period_start(due: date) -> date:
    """该期 review 的起点 = 上一个 review 日 (上月同号)。"""
    y, m = (due.year - 1, 12) if due.month == 1 else (due.year, due.month - 1)
    return _safe_date(y, m, due.day)


def _last_review() -> Optional[dict]:
    """读 data/reviews/ 最近一份 · 返 {period_end, status, filename}。 只读 · 失败返 None。"""
    try:
        from workers.review_generator import list_reviews
        items = list_reviews()
        return items[0] if items else None
    except Exception:
        return None


def _mirror_last_done() -> Optional[str]:
    """能力镜像快照最近生成日 (文件 mtime)。 没有返 None。"""
    p = DATA_DIR / "bro_capability_snapshot.md"
    if not p.exists():
        return None
    try:
        return date.fromtimestamp(p.stat().st_mtime).isoformat()
    except Exception:
        return None


# ── 能力发现节律 (入口 A · 每周一提醒挖一轮外部 AI 能力) ──
# 语义: 每周一是提醒点。 本周 (从本周一起) 没发起过 discover_skill → 提醒该挖了;
# 发起过 → next_due 顺延到下周一。 触发仍走 NLP (看板按钮 / 节律条 → spawnQuickly →
# 调 discover_skill) · 这里只算『显示节律』· 跟月度复盘同款『看得见点得动』。
SKILL_STATE_FILE = DATA_DIR / "skill_discovery_state.json"


def _skill_discovery_last_run() -> Optional[date]:
    """上次发起能力发现的日期 (discover_skill 工具跑完落的时间戳)。 没有返 None。"""
    if not SKILL_STATE_FILE.exists():
        return None
    try:
        s = (json.loads(SKILL_STATE_FILE.read_text(encoding="utf-8")).get("last_run_at") or "").strip()
        if s:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        pass
    return None


def _skill_discovery_ritual(today: date) -> dict:
    this_monday = today - timedelta(days=today.weekday())  # weekday: Mon=0
    last_run = _skill_discovery_last_run()
    done_this_week = last_run is not None and last_run >= this_monday
    next_due = this_monday + timedelta(days=7) if done_this_week else this_monday
    return {
        "id": "skill_discovery",
        "label": "能力发现",
        "next_due": next_due.isoformat(),
        "days_left": (next_due - today).days,  # 本周没做且过了周一 → 负数 (过期未做·该提醒)
        "last_done": last_run.isoformat() if last_run else None,
        "done_this_week": done_this_week,
        "draft_prompt": (
            "帮我做一轮能力发现 (调 discover_skill 工具) · 按我的画像去 GitHub / 技术站"
            "挖点新的 AI 能力 · 评估后出一份发现报告 · 靠谱的给我落地建议"
        ),
    }


def get_rituals(today: Optional[date] = None) -> list[dict]:
    """返回所有周期仪式的状态 · 给日历『节律条』用。"""
    today = today or _today()
    out: list[dict] = []

    # 1. 月度 review
    due = _next_review_due(today)
    last = _last_review()
    out.append({
        "id": "monthly_review",
        "label": "月度复盘",
        "next_due": due.isoformat(),
        "period_start": _review_period_start(due).isoformat(),
        "days_left": (due - today).days,
        "last_done": last.get("period_end") if last else None,
        "last_status": last.get("status") if last else None,
        "drafted_for_next": bool(last and last.get("period_end") == due.isoformat()),
        "draft_prompt": f"帮我起草这个周期的月度复盘 (monthly_review action=draft · period_end={due.isoformat()})",
    })

    # 2. 能力镜像刷新 (.env 开关 · 桥的下游)
    interval_env = (os.environ.get("OPUS_CAPABILITY_MIRROR_INTERVAL_DAYS") or "0").strip()
    try:
        interval_days = int(interval_env)
    except ValueError:
        interval_days = 0
    out.append({
        "id": "capability_mirror",
        "label": "能力镜像刷新",
        "enabled": interval_days > 0,
        "interval_days": interval_days,
        "last_done": _mirror_last_done(),
        "draft_prompt": "帮我照一次市场能力镜像 (mirror_capability action=generate)",
    })

    # 3. 能力发现 (每周一 · 入口 A)
    out.append(_skill_discovery_ritual(today))

    return out


def rituals_for_month(year: int, month: int) -> list[dict]:
    """该月内落在哪几天有仪式到期 (给日历格子打标)。"""
    out: list[dict] = []
    rday = _safe_date(year, month, _review_dom())
    if rday >= _first_due():
        out.append({"date": rday.isoformat(), "id": "monthly_review", "label": "月度复盘"})
    return out
