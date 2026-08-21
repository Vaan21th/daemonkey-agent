"""
workers/task_plan.py
====================

任务计划层 —— 给任务账本补上"有序步骤 + 进度"这一维。

为什么单独一层(而不是塞进 task_ledger):
  账本原本记的是【结论】(哪条通了✓/哪条死了✗/定了什么决策)——它是**日志**。
  日志答不了两个问题:「这活总共分几步」「现在走到第几步」。
  于是长任务里 AI 知道"试过什么"·却不知道"还剩什么"·人也在界面上看不见进度。
  这一层补的就是那个**清单**: 有序、有状态、能勾掉、能改。

真源仍是同一个 data/ledgers/<slug>.json(账本的 steps 字段)——
步骤和结论是一个任务的两面·分家会立刻产生"两个真源不一致"。

状态机(故意只有四态·别再加):
  todo  ○ 待做      doing ▶ 正在做
  done  ✓ 做完      skip  ✗ 跳过(计划有变·不是失败)

失败不进步骤状态·失败走账本的 ruledout —— 那是"结论"不是"进度"。
"""

from __future__ import annotations

import time
from typing import Any, Optional

from . import task_ledger as tl

_STATUSES = ("todo", "doing", "done", "skip")

_STATUS_ALIASES = {
    "todo": "todo", "pending": "todo", "待做": "todo", "未做": "todo", "待办": "todo",
    "doing": "doing", "wip": "doing", "active": "doing", "running": "doing",
    "进行中": "doing", "正在做": "doing", "在做": "doing", "开始": "doing",
    "done": "done", "ok": "done", "finished": "done", "complete": "done", "completed": "done",
    "做完": "done", "完成": "done", "已完成": "done", "搞定": "done", "通了": "done",
    "skip": "skip", "skipped": "skip", "cancel": "skip", "cancelled": "skip", "drop": "skip",
    "跳过": "skip", "取消": "skip", "不做了": "skip", "作废": "skip",
}

_ICONS = {"todo": "○", "doing": "▶", "done": "✓", "skip": "✗"}

_MAX_STEPS = 40        # 一个任务拆过 40 步 = 该拆成两个任务了
_STEP_TEXT_CAP = 200


def resolve_status(s: Any) -> str:
    return _STATUS_ALIASES.get(str(s or "").strip().lower(), "todo")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def _resolve(slug: Optional[str], session_id: str) -> str:
    """把"人给的名字"和"落盘用的 slug"统一成一个 key · 拿不到就退回本会话活跃账本。

    2026-08-19 修 · 病根是两条路对同一个任务名算出两个 key:
      · `plan` 落盘走 `tl.open_ledger()` —— 它内部 `_slugify`(空格→`-`)
      · `step` 查账本走 `tl.get_ledger()` —— 这边原来只 `.lower()`
    于是任务名**一带空格**就必然错位: 计划列成了 `记忆检索-fts5→向量-改造评估`·
    勾步骤却去找 `记忆检索 fts5→向量 改造评估` → "没找到第 N 步(或没有活跃计划)"。
    真机实测里 AI 因此连列三次计划、换了个不带空格的名字才蒙对(多烧两轮 LLM +
    留下一本重复账本)。 `_slugify` 幂等·所以已经是 slug 的值(前端传的)再过一遍无害。
    """
    s = (slug or "").strip()
    return (tl._slugify(s) if s else "") or tl.active_slug(session_id) or ""


# ---------- 读 ----------

def get_steps(slug: str) -> list[dict]:
    led = tl.get_ledger(slug)
    return list(led.get("steps") or []) if led else []


def progress(led: Optional[dict]) -> dict:
    """算进度摘要 · 前端 banner 和 LLM 回灌共用一份口径(防两处各算一套)。"""
    steps = list((led or {}).get("steps") or [])
    total = len(steps)
    done = sum(1 for s in steps if s.get("status") == "done")
    skipped = sum(1 for s in steps if s.get("status") == "skip")
    doing = next((s for s in steps if s.get("status") == "doing"), None)
    nxt = next((s for s in steps if s.get("status") == "todo"), None)
    return {
        "total": total,
        "done": done,
        "skipped": skipped,
        # 已结算 = 做完 + 跳过 · 进度条按这个走(跳过的步不该让进度永远卡着)
        "settled": done + skipped,
        "current": doing or nxt,
        "current_i": (doing or nxt or {}).get("i"),
        "all_done": total > 0 and (done + skipped) >= total,
    }


def render_steps(led: Optional[dict]) -> str:
    """渲染成给 LLM 每轮看的清单。无步骤返回空串。"""
    steps = list((led or {}).get("steps") or [])
    if not steps:
        return ""
    p = progress(led)
    title = (led or {}).get("title") or (led or {}).get("slug") or "任务"
    head = f"任务《{title}》计划 · 已结算 {p['settled']}/{p['total']} 步"
    lines = [head]
    for s in steps:
        st = s.get("status") or "todo"
        mark = _ICONS.get(st, "○")
        tail = ""
        if st == "doing":
            tail = "   ← 正在做"
        elif st == "skip" and s.get("note"):
            tail = f"   ({s['note']})"
        lines.append(f"  {mark} {s.get('i')}. {s.get('text', '')}{tail}")
    return "\n".join(lines)


def render_hint(led: Optional[dict]) -> str:
    """计划段的回灌文本(嵌进 task_ledger.render_hint 的最前面)。

    放最前面是有意的: 「现在该干哪一步」比「以前试过什么」更急·
    前者决定下一个动作·后者只是避免走回头路。
    """
    body = render_steps(led)
    if not body:
        return ""
    p = progress(led)
    hint = "\n\n=== 当前任务计划 · 你自己列的 ===\n" + body + "\n"
    if p["all_done"]:
        hint += (
            "【全部步骤已结算】收尾: 跟用户汇报结果·"
            "该沉淀的(playbook / learnings / 账本结论)别漏。\n"
        )
    else:
        cur = p.get("current") or {}
        hint += (
            f"【下一个动作】第 {cur.get('i')} 步: {cur.get('text', '')}\n"
            "【纪律】做完一步立刻 `track_task(action='step', step=N, status='done')` —— "
            "别攒到最后一次性勾(中途断了就全丢了·用户也看不到进度在动)。\n"
            "【计划该改就改】发现原计划不对(漏了步/顺序错/某步不必做了)→ "
            "`action='plan'` 重列整份·或 `action='step'` 把某步标 skip 并说清原因。"
            "**照着一个已知错的计划往下走·比改计划的代价大得多。**\n"
        )
    return hint


# ---------- 写 ----------

def set_steps(
    session_id: str,
    steps: list,
    slug: Optional[str] = None,
    title: Optional[str] = None,
) -> Optional[dict]:
    """整份替换步骤清单(AI 开工列计划 / 中途重列)。返回更新后的账本。

    保状态: 重列时若某步文案跟旧步完全一致·继承它的 status ——
    否则"加一步"这种小改会把已经做完的进度全抹回 todo。
    """
    target = _resolve(slug, session_id)
    if not target:
        return None
    led = tl.get_ledger(target)
    if led is None:
        led = tl.open_ledger(target, session_id, title=title)

    old_by_text = {
        (s.get("text") or "").strip(): s
        for s in (led.get("steps") or [])
    }

    norm: list[dict] = []
    for idx, raw in enumerate(steps[:_MAX_STEPS], start=1):
        if isinstance(raw, dict):
            text = str(raw.get("text") or "").strip()
            status = resolve_status(raw.get("status")) if raw.get("status") else None
            note = str(raw.get("note") or "").strip()
        else:
            text, status, note = str(raw or "").strip(), None, ""
        if not text:
            continue
        prev = old_by_text.get(text)
        if status is None:
            status = (prev.get("status") if prev else None) or "todo"
        item = {
            "i": idx,
            "text": text[:_STEP_TEXT_CAP],
            "status": status,
            "ts": (prev or {}).get("ts") or _now(),
        }
        if note:
            item["note"] = note[:_STEP_TEXT_CAP]
        norm.append(item)

    # 重排 i(过滤空行后要连续) —— 前端和 LLM 都按 i 定位·不能有洞
    for n, item in enumerate(norm, start=1):
        item["i"] = n

    led["steps"] = norm
    if title:
        led["title"] = title.strip()
    tl.save_ledger(led)
    if session_id:
        tl.set_active(session_id, led["slug"])
    return led


def update_step(
    session_id: str,
    i: int,
    status: Optional[str] = None,
    text: Optional[str] = None,
    note: Optional[str] = None,
    slug: Optional[str] = None,
) -> Optional[dict]:
    """改某一步的状态/文案。i 是 1-based 序号(render 里显示的那个数字)。"""
    target = _resolve(slug, session_id)
    if not target:
        return None
    led = tl.get_ledger(target)
    if not led or not led.get("steps"):
        return None
    hit = next((s for s in led["steps"] if int(s.get("i") or 0) == int(i)), None)
    if hit is None:
        return None
    if status:
        hit["status"] = resolve_status(status)
    if text:
        hit["text"] = str(text).strip()[:_STEP_TEXT_CAP]
    if note is not None:
        note_s = str(note).strip()[:_STEP_TEXT_CAP]
        if note_s:
            hit["note"] = note_s
        else:
            hit.pop("note", None)
    hit["ts"] = _now()
    tl.save_ledger(led)
    return led


def add_step(
    session_id: str,
    text: str,
    slug: Optional[str] = None,
    after: Optional[int] = None,
) -> Optional[dict]:
    """追加一步(after 给了就插在该序号后面)。用于"干着干着发现还得多做一步"。"""
    text = (text or "").strip()
    if not text:
        return None
    target = _resolve(slug, session_id)
    if not target:
        return None
    led = tl.get_ledger(target)
    if led is None:
        return None
    steps = list(led.get("steps") or [])
    if len(steps) >= _MAX_STEPS:
        return None
    item = {"i": 0, "text": text[:_STEP_TEXT_CAP], "status": "todo", "ts": _now()}
    if after is None:
        steps.append(item)
    else:
        pos = next((n for n, s in enumerate(steps) if int(s.get("i") or 0) == int(after)), len(steps) - 1)
        steps.insert(pos + 1, item)
    for n, s in enumerate(steps, start=1):
        s["i"] = n
    led["steps"] = steps
    tl.save_ledger(led)
    return led


def remove_step(session_id: str, i: int, slug: Optional[str] = None) -> Optional[dict]:
    """删一步(用户在界面上删)。AI 侧优先用 skip 而不是删——留痕比抹掉有价值。"""
    target = _resolve(slug, session_id)
    if not target:
        return None
    led = tl.get_ledger(target)
    if not led or not led.get("steps"):
        return None
    steps = [s for s in led["steps"] if int(s.get("i") or 0) != int(i)]
    for n, s in enumerate(steps, start=1):
        s["i"] = n
    led["steps"] = steps
    tl.save_ledger(led)
    return led
