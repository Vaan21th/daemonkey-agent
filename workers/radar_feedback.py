"""
workers/radar_feedback.py
=========================

卷三十二 · 信息雷达打标闭环

BRO 在雷达条目上能做四个动作：
  - 👍 thumbs_up   · "这条对·OPUS 多关注这类"
  - 👎 thumbs_down · "这条不对·OPUS 别再抓类似的"（最关键的负反馈信号）
  - ⭐ starred     · "收藏·我以后还要看"
  - 🗑 hidden      · "藏起来·不出现在雷达视图"

数据结构 data/radar_feedback.json:
  {
    "updated_at": "...",
    "items": {
      "<item_id>": {
        "feedback": "thumbs_up|thumbs_down|starred|hidden",
        "note": "可选文本",
        "title_snap": "标题快照·防 radar.json 滚动后丢失",
        "source": "源 slug 快照",
        "domain": "领域快照",
        "url": "url 快照",
        "at": "...",
        "history": [{at, feedback, note}, ...]
      }
    }
  }

item_id 用 url 的 md5(10) · radar.json 每条 url 唯一·hash 稳定·不依赖 radar.json
里有没有 id 字段。

反哺时机：
  - mine_opportunities / trend_finder 跑 LLM 前 · 把 thumbs_down + thumbs_up 渲染
    成 prompt 块塞进去——告诉 LLM 「这些信源/类型 BRO 拒过 / 这些 BRO 喜欢」
  - radar UI 渲染时 · hidden 的条目隐藏 · starred 的条目置顶
  - 软文判别用 thumbs_down 的源做 prior（同源 future items 软文嫌疑 +1）

红线：
  - 不删 radar.json 里的条目 · 只在 feedback 里打标
  - history 永远追加 · 即使 BRO 翻悔多次也留痕
  - radar items 滚动出去后·feedback 里 title_snap 仍可读
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
FEEDBACK_FILE = DATA_DIR / "radar_feedback.json"

logger = logging.getLogger("opus.radar_feedback")

VALID_FEEDBACK = {"thumbs_up", "thumbs_down", "starred", "hidden"}
FEEDBACK_LABEL = {
    "thumbs_up":   "👍 关注这类",
    "thumbs_down": "👎 别再抓",
    "starred":     "⭐ 收藏",
    "hidden":      "🗑 隐藏",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, text: str) -> None:
    """卷四十六 III · wish-badd4 收编到 safe_write
    radar_feedback.json 是 BRO 对雷达条目的标注·backup=True"""
    from .safe_write import atomic_write_text
    atomic_write_text(path, text, backup=True)


def item_id_for_url(url: str) -> str:
    """雷达条目稳定 id · md5(url) 前 12 位"""
    if not url:
        return ""
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:12]


def _load_all() -> dict:
    if not FEEDBACK_FILE.exists():
        return {"updated_at": None, "items": {}}
    try:
        data = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
        if not isinstance(data.get("items"), dict):
            data["items"] = {}
        return data
    except Exception as e:
        logger.warning("radar_feedback.json corrupt: %s · 重置", e)
        return {"updated_at": None, "items": {}}


def _save_all(data: dict) -> None:
    data["updated_at"] = _now_iso()
    _atomic_write(FEEDBACK_FILE, json.dumps(data, ensure_ascii=False, indent=2))


def _lookup_radar_item(item_id: str) -> Optional[dict]:
    """从 radar.json 找一条 item · 用于 feedback 时取 title/source/domain 快照"""
    radar_file = DATA_DIR / "radar.json"
    if not radar_file.exists():
        return None
    try:
        radar = json.loads(radar_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    for it in radar.get("items") or []:
        if item_id_for_url(it.get("url") or "") == item_id:
            return it
    return None


def set_feedback(
    item_id: str,
    feedback: str,
    *,
    note: Optional[str] = None,
    title_hint: Optional[str] = None,
    url_hint: Optional[str] = None,
) -> dict:
    """记录一条 feedback · 返回最新这条 entry"""
    if not item_id:
        return {"ok": False, "error": "item_id 必填"}
    feedback = (feedback or "").strip().lower()
    if feedback not in VALID_FEEDBACK:
        return {
            "ok": False,
            "error": f"feedback 必须是 {sorted(VALID_FEEDBACK)} 之一·收到 {feedback!r}",
        }

    data = _load_all()
    items = data.setdefault("items", {})
    entry = items.get(item_id) or {}

    if not entry.get("title_snap"):
        radar_item = _lookup_radar_item(item_id)
        if radar_item:
            entry["title_snap"] = (
                radar_item.get("title_zh") or radar_item.get("title") or ""
            )[:200]
            entry["source"] = radar_item.get("source") or ""
            entry["domain"] = radar_item.get("domain") or ""
            entry["url"] = radar_item.get("url") or ""
        elif title_hint or url_hint:
            entry["title_snap"] = (title_hint or "")[:200]
            entry["url"] = url_hint or ""

    history = entry.get("history") or []
    history.append({
        "at": _now_iso(),
        "feedback": feedback,
        "note": (note or "").strip()[:200],
    })
    entry["history"] = history[-20:]
    entry["feedback"] = feedback
    if note is not None and note.strip():
        entry["note"] = note.strip()[:200]
    entry["at"] = _now_iso()
    items[item_id] = entry
    _save_all(data)
    logger.info("radar_feedback %s set %s", item_id, feedback)
    return {"ok": True, "item_id": item_id, "entry": entry}


def clear_feedback(item_id: str) -> dict:
    """清掉一条 feedback · 留 history（如有）"""
    data = _load_all()
    items = data.get("items") or {}
    if item_id not in items:
        return {"ok": True, "no_op": True}
    entry = items[item_id]
    history = entry.get("history") or []
    history.append({"at": _now_iso(), "feedback": "(cleared)", "note": ""})
    entry["history"] = history[-20:]
    entry.pop("feedback", None)
    entry["at"] = _now_iso()
    items[item_id] = entry
    _save_all(data)
    return {"ok": True, "item_id": item_id, "cleared": True}


def get_feedback(item_id: str) -> Optional[dict]:
    data = _load_all()
    return (data.get("items") or {}).get(item_id)


def list_feedback(*, only: Optional[str] = None, max_items: int = 200) -> dict:
    """列出所有 feedback · only 可以是 starred/thumbs_down 等"""
    data = _load_all()
    items = data.get("items") or {}
    rows: list[dict] = []
    for iid, e in items.items():
        if only and e.get("feedback") != only:
            continue
        if not e.get("feedback"):
            continue
        rows.append({
            "item_id": iid,
            "feedback": e.get("feedback"),
            "label": FEEDBACK_LABEL.get(e.get("feedback"), "?"),
            "title": e.get("title_snap"),
            "source": e.get("source"),
            "domain": e.get("domain"),
            "url": e.get("url"),
            "note": e.get("note"),
            "at": e.get("at"),
        })
    rows.sort(key=lambda x: x.get("at") or "", reverse=True)
    counts: dict[str, int] = {k: 0 for k in VALID_FEEDBACK}
    for e in items.values():
        f = e.get("feedback")
        if f in counts:
            counts[f] += 1
    return {
        "updated_at": data.get("updated_at"),
        "total": len(rows),
        "by_feedback": counts,
        "items": rows[:max_items],
    }


def feedback_map() -> dict[str, dict]:
    """给 radar UI 用 · {item_id: entry}·只含还活着的 feedback"""
    data = _load_all()
    items = data.get("items") or {}
    return {iid: e for iid, e in items.items() if e.get("feedback")}


def load_for_prompt(*, max_chars: int = 1200) -> str:
    """
    给 trend_finder / mine_opportunities 的 LLM prompt 用·
    渲染成纯文本块·让 LLM 知道 BRO 对哪些信源/方向是 thumbs_down·哪些是 starred。
    优先放 thumbs_down——这是最关键的负反馈信号。
    """
    data = _load_all()
    items = data.get("items") or {}
    if not items:
        return "（BRO 还没在雷达上打过标 · 这是 OPUS 跟 BRO 配合的第一次）"

    by_fb: dict[str, list[dict]] = {k: [] for k in VALID_FEEDBACK}
    for e in items.values():
        f = e.get("feedback")
        if f in by_fb:
            by_fb[f].append(e)

    lines: list[str] = []
    counts = {k: len(v) for k, v in by_fb.items()}
    lines.append(
        f"BRO 在雷达条目上的打标: "
        f"👎 {counts['thumbs_down']} / 👍 {counts['thumbs_up']} / "
        f"⭐ {counts['starred']} / 🗑 {counts['hidden']}"
    )
    lines.append("")

    if by_fb["thumbs_down"]:
        lines.append("【BRO 明确 👎 拒过的（最重要 · 别再推同源/同类）】")
        for e in by_fb["thumbs_down"][:8]:
            src = e.get("source") or "?"
            title = (e.get("title_snap") or "?")[:60]
            note = e.get("note") or ""
            line = f"- [{src}] {title}"
            if note:
                line += f" — BRO 说：{note}"
            lines.append(line)
        lines.append("")

    if by_fb["starred"]:
        lines.append("【BRO ⭐ 收藏的（多关注这类方向）】")
        for e in by_fb["starred"][:6]:
            src = e.get("source") or "?"
            title = (e.get("title_snap") or "?")[:60]
            lines.append(f"- [{src}] {title}")
        lines.append("")

    if by_fb["thumbs_up"]:
        lines.append("【BRO 👍 认可的（同类 OK）】")
        for e in by_fb["thumbs_up"][:5]:
            src = e.get("source") or "?"
            title = (e.get("title_snap") or "?")[:60]
            lines.append(f"- [{src}] {title}")
        lines.append("")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…（已截断）"
    return text


def source_negative_score(source: str) -> int:
    """
    某个 source（信源 slug）有多少条 thumbs_down·给软文判别当先验。
    返回 0/1/2/3+——卷三十二 b 用。
    """
    if not source:
        return 0
    data = _load_all()
    items = data.get("items") or {}
    n = 0
    for e in items.values():
        if e.get("source") == source and e.get("feedback") == "thumbs_down":
            n += 1
    return n


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO)
    print(json.dumps(list_feedback(), ensure_ascii=False, indent=2))
