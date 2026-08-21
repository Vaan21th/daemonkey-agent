"""
workers/task_ledger.py
=======================

任务账本 —— 抗"套娃"的确定性工作记忆(卷 · ③)。

问题：
  长会话被语义压缩后、或用户开新窗口后，AI 丢掉了"哪条路已验证通、哪条已排除死"
  的细粒度工作状态 → 重新去试已确认的、又撞进已排除的死路 → 无限套娃 → 放弃。

设计：
  把"结论"从"过程"里蒸馏出来，单独持久化成一本按【任务名(slug)】组织的账本：
    - verified   ✓ 已验证 / 已确认可行
    - ruledout   ✗ 已排除 / 死路(带原因)
    - pending    · 待验证 / 进行中的假设
    - decision   ▶ 关键决策
    - note       · 其它要点

  账本【不进语义压缩】：每轮由 closure_check.ledger_hint 无损回灌进易变尾巴。
  跨窗口：同一 slug 一本账；新会话 open/load 同名 slug 即接上上一次的进展。

  真源落盘 data/ledgers/<slug>.json；每会话"当前活跃 slug"落 data/runtime/ledger_active.json。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
_LEDGER_DIR = _ROOT / "data" / "ledgers"
_ACTIVE_PATH = _ROOT / "data" / "runtime" / "ledger_active.json"

_KINDS = ("verified", "ruledout", "pending", "decision", "note")

_KIND_ALIASES = {      # 规范 kind ← 中文/同义词别名
    a: canon
    for canon, aliases in {
        "verified": ("verify", "ok", "pass", "done", "works", "confirmed",
                     "已验证", "验证", "通过", "确认", "通了"),
        "ruledout": ("ruled_out", "rejected", "deadend", "dead_end", "fail", "failed", "no",
                     "已排除", "排除", "死路", "行不通", "放弃"),
        "pending": ("todo", "wip", "trying", "hypothesis",
                    "待验证", "进行中", "假设", "试", "待办"),
        "decision": ("decide", "chose", "picked", "决策", "决定", "选定"),
        "note": ("备注", "记录", "要点"),
    }.items()
    for a in (canon,) + aliases
}

_ICONS = {"verified": "✓ 已验证", "ruledout": "✗ 已排除", "pending": "· 待验证",
          "decision": "▶ 决策", "note": "· 记录"}

_MAX_ENTRIES = 200          # 单本账最多留多少条(超出丢最旧的 note/verified·保 ruledout/decision)
_HINT_MAX_PER_KIND = 12     # 回灌时每类最多列几条(防提示膨胀)
_TEXT_CAP = 500             # 单条正文上限


def resolve_kind(k: Any) -> str:
    key = str(k or "").strip().lower()
    return _KIND_ALIASES.get(key, "note")


def _slugify(title: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", (title or "").strip())
    s = re.sub(r"\s+", "-", s)
    s = s.strip("._-")
    return (s[:60] or "task").lower()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def _ledger_path(slug: str) -> Path:
    return _LEDGER_DIR / f"{slug}.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # 社区 7/31 · Bug #7 · Windows Defender 瞬态句柄锁 → replace 失败 · 带重试
    try:
        from workers.safe_write import robust_replace
        robust_replace(tmp, path)
    except ImportError:
        tmp.replace(path)


# ---------- 活跃指针 ----------

def active_slug(session_id: str) -> Optional[str]:
    if not session_id:
        return None
    return _read_json(_ACTIVE_PATH, {}).get(session_id)


def set_active(session_id: str, slug: str) -> None:
    if not session_id or not slug:
        return
    m = _read_json(_ACTIVE_PATH, {})
    if not isinstance(m, dict):
        m = {}
    m[session_id] = slug
    _write_json(_ACTIVE_PATH, m)


# ---------- 账本读写 ----------

def get_ledger(slug: str) -> Optional[dict]:
    slug = (slug or "").strip().lower()
    if not slug:
        return None
    return _read_json(_ledger_path(slug), None)


def save_ledger(led: dict) -> None:
    """整本落盘 · 给 task_plan(步骤层)复用同一份原子写 + 同一个真源文件。"""
    if not led or not led.get("slug"):
        return
    led["updated"] = _now()
    _write_json(_ledger_path(led["slug"]), led)


def open_ledger(slug_or_title: str, session_id: str = "", title: Optional[str] = None) -> dict:
    """按 slug 打开(不存在则新建)· 设为该会话活跃账本 · 返回账本 dict。"""
    raw = (slug_or_title or "").strip()
    slug = _slugify(raw)
    led = get_ledger(slug)
    if led is None:
        led = {
            "slug": slug,
            "title": (title or raw or slug).strip(),
            "created": _now(),
            "updated": _now(),
            "entries": [],
        }
        _write_json(_ledger_path(slug), led)
    if session_id:
        set_active(session_id, slug)
    return led


def _trim_entries(entries: list) -> list:
    if len(entries) <= _MAX_ENTRIES:
        return entries
    # 保 ruledout / decision(最值钱) · 优先丢最旧的 note/verified/pending
    protected = [e for e in entries if e.get("kind") in ("ruledout", "decision")]
    droppable = [e for e in entries if e.get("kind") not in ("ruledout", "decision")]
    keep_drop = droppable[-(_MAX_ENTRIES - len(protected)):] if _MAX_ENTRIES > len(protected) else []
    merged = protected + keep_drop
    merged.sort(key=lambda e: e.get("ts", ""))
    return merged


def add_entry(
    session_id: str,
    kind: str,
    text: str,
    slug: Optional[str] = None,
    title: Optional[str] = None,
) -> Optional[dict]:
    """往(活跃或指定)账本追加一条。返回更新后的账本;无活跃账本且没给 slug → None。"""
    text = (text or "").strip()
    if not text:
        return None
    target = (slug or "").strip().lower() or active_slug(session_id)
    if not target:
        return None
    led = get_ledger(target)
    if led is None:
        led = open_ledger(target, session_id, title=title)
    led.setdefault("entries", []).append({
        "kind": resolve_kind(kind),
        "text": text[:_TEXT_CAP],
        "ts": _now(),
        "session": session_id or "",
    })
    led["entries"] = _trim_entries(led["entries"])
    led["updated"] = _now()
    if title:
        led["title"] = title.strip()
    _write_json(_ledger_path(led["slug"]), led)
    if session_id:
        set_active(session_id, led["slug"])
    return led


# ---------- 回灌 / 检索 ----------

def render_ledger(led: dict) -> str:
    """把一本账本渲染成紧凑的分组文本(给 LLM 看)。"""
    if not led or not led.get("entries"):
        return ""
    by_kind: dict[str, list] = {k: [] for k in _KINDS}
    for e in led["entries"]:
        by_kind.setdefault(e.get("kind", "note"), []).append(e)
    lines = [f"任务《{led.get('title') or led.get('slug')}》进展账本:"]
    for k in ("verified", "ruledout", "pending", "decision", "note"):
        items = by_kind.get(k) or []
        if not items:
            continue
        for e in items[-_HINT_MAX_PER_KIND:]:
            lines.append(f"  {_ICONS[k]}: {e.get('text', '')}")
    return "\n".join(lines)


def render_hint(session_id: str) -> str:
    """本会话活跃账本 → 每轮回灌。两段:【计划】走到第几步 +【结论】试过什么。

    计划在前 —— 它决定下一个动作;结论只是避免走回头路。
    """
    slug = active_slug(session_id)
    if not slug:
        return ""
    led = get_ledger(slug)
    if not led:
        return ""
    try:
        from workers.task_plan import render_hint as _plan_hint
        plan = _plan_hint(led)
    except Exception:
        plan = ""      # 计划层坏了不该拖垮结论回灌
    body = render_ledger(led)
    if not body:
        return plan    # 刚开工: 只有计划还没结论 · 别把计划也吞掉
    hint = (
        plan
        + "\n\n=== 任务账本 · 之前的结论(参考·别盲从) ===\n"
        + body
        + "\n【怎么用】默认别重复劳动:✓ 的先别重验、✗ 的先别再走、从『待验证』往前推。\n"
        "【结论可能过时】若和你现在的观察冲突、或代码/环境已变——**以现在为准**,"
        "并调 track_task 记一条更正把旧结论纠正掉;有新结论(通了/死了/决策)也随手记一条。\n"
    )
    # 卡住 nudge(抗套娃 · vibe coding):已排除 ≥2 条路、还没有一条 ✓ → 别闷头硬撑,请顾问
    entries = led.get("entries", []) if led else []
    n_ruledout = sum(1 for e in entries if e.get("kind") == "ruledout")
    n_verified = sum(1 for e in entries if e.get("kind") == "verified")
    if n_ruledout >= 2 and n_verified == 0:
        hint += (
            f"\n【⚠ 别硬撑 · 抗套娃】这任务已排除 {n_ruledout} 条路、还没一条走通——"
            "别一个人闷头继续试同类思路(那就是原地套娃)。调 `replan` 请一个『干净视角的顾问』:"
            "它拿到上面的 ✗ 列表、不会重走死路,会给一个新方案。真到极限就带着账本清楚问一句,而不是默默放弃。\n"
        )
    return hint


def search(query: str, limit: int = 5) -> list[dict]:
    """给 recall_memory 用:跨所有账本按关键词粗检索,返回命中账本摘要。"""
    q = (query or "").strip().lower()
    if not q or not _LEDGER_DIR.exists():
        return []
    hits: list[dict] = []
    for p in sorted(_LEDGER_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        led = _read_json(p, None)
        if not led:
            continue
        blob = (led.get("title", "") + " " + " ".join(
            e.get("text", "") for e in led.get("entries", [])
        )).lower()
        if any(tok and tok in blob for tok in q.split()):
            hits.append({
                "slug": led.get("slug"),
                "title": led.get("title"),
                "updated": led.get("updated"),
                "count": len(led.get("entries", [])),
                "render": render_ledger(led),
            })
        if len(hits) >= limit:
            break
    return hits


def list_ledgers(limit: int = 30) -> list[dict]:
    if not _LEDGER_DIR.exists():
        return []
    out: list[dict] = []
    for p in sorted(_LEDGER_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        led = _read_json(p, None)
        if led:
            out.append({
                "slug": led.get("slug"),
                "title": led.get("title"),
                "updated": led.get("updated"),
                "count": len(led.get("entries", [])),
            })
    return out
