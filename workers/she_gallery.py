"""
workers/she_gallery.py
======================

她·画廊 · 羁绊式朋友圈。

每条 = 一张她的图 + 一句想对你说的话。6 小时 tick 只来问一句：
有新信号、冷却过了、骰子过了，才寄。开机那一拍不补发。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from workers.she_gallery_bond import (
    _SOLO_RETRY,
    copy_to_gallery,
    draft_copy,
    generate_image,
    has_image_app,
    has_other_person,
    rel_path,
)
from workers.she_gallery_gate import (
    cooldown_blocked,
    last_post_dt,
    mark_posted,
    new_signals,
    roll_dice,
    scene_repeats,
    used_from,
)

logger = logging.getLogger("opus.she_gallery")

_ROOT = Path(__file__).resolve().parents[1]
GALLERY_FILE = _ROOT / "soul" / "SHE-GALLERY.md"
_ENTRY_KEYS = ("date", "image", "text", "mood", "scene")
_KV_RE = re.compile(r"^([A-Za-z\u4e00-\u9fff]+):\s*(.*)$")
_RETRY = "上一稿撞了近条。换构图，换那句。窗台+杯子和「刚醒/你醒了/早安」都不要再来。"


def she_gallery(*, path: Path | None = None) -> list[dict]:
    """读画廊列表(倒序·朋友圈)。每项 {date, image, text, mood, scene}。"""
    p = Path(path) if path else GALLERY_FILE
    if not p.exists():
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return []
    body = text
    marker = "## gallery"
    if marker in text:
        body = text.split(marker, 1)[1]
        nxt = re.search(r"\n## ", body)
        if nxt:
            body = body[: nxt.start()]
    items: list[dict] = []
    current: dict | None = None
    for raw_line in body.splitlines():
        stripped = raw_line.rstrip().strip()
        if stripped.startswith("- date:"):
            if current and current.get("date"):
                items.append(current)
            current = {k: "" for k in _ENTRY_KEYS}
            current["date"] = stripped.split(":", 1)[1].strip()
            continue
        if current is None:
            continue
        m = _KV_RE.match(stripped)
        if not m:
            continue
        key = m.group(1).strip().lower()
        if key in current:
            current[key] = (m.group(2) or "").strip()
    if current and current.get("date"):
        items.append(current)
    items.reverse()
    return items


def _append_gallery(date, image, text, mood, scene="", *, path: Path | None = None) -> dict:
    p = Path(path) if path else GALLERY_FILE
    entry = {
        "date": str(date or "").strip(),
        "image": str(image or "").strip(),
        "text": str(text or "").strip(),
        "mood": str(mood or "").strip(),
        "scene": str(scene or "").strip(),
    }
    block = (
        f"- date: {entry['date']}\n"
        f"  image: {entry['image']}\n"
        f"  text: {entry['text']}\n"
        f"  mood: {entry['mood']}\n"
        f"  scene: {entry['scene']}\n"
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("# 她 · 画廊\n\n## gallery\n" + block, encoding="utf-8")
        return entry
    existing = p.read_text(encoding="utf-8")
    if "## gallery" not in existing:
        existing = existing.rstrip() + "\n\n## gallery\n"
    if not existing.endswith("\n"):
        existing += "\n"
    p.write_text(existing + block, encoding="utf-8")
    return entry


def _pick_draft(existing: list[dict], signals: list[str], *, extra: str = "") -> tuple[dict | None, str | None]:
    used = used_from(existing)
    try:
        from workers.she_gallery_feedback import vetoed_used
        more = vetoed_used()
        used["texts"].extend(more.get("texts") or [])
        used["moods"].extend(more.get("moods") or [])
        used["scenes"].extend(more.get("scenes") or [])
    except Exception:
        pass
    parsed, err = draft_copy(signals, used, extra)
    if err or not parsed:
        return None, err or "empty"
    text = str(parsed.get("text") or "").strip()
    scene = str(parsed.get("scene") or "").strip()
    if not text:
        return None, "empty_text"
    if has_other_person(scene):
        return None, "other_person"
    if scene_repeats(scene, text, used):
        return None, "repeat"
    return parsed, None


def make_gallery_entry(
    *,
    force: bool = False,
    path: Path | None = None,
    state_path: Path | None = None,
) -> dict:
    """生成一条。非 force：冷却 → 新信号 → 骰子 → 文案。force 仍防复读。"""
    gallery_path = Path(path) if path else GALLERY_FILE
    existing = she_gallery(path=gallery_path)
    now = datetime.now()
    signals = new_signals(last_post_dt(existing))

    if not force:
        if cooldown_blocked(now, existing, state_path=state_path):
            return {"ok": False, "reason": "calm"}
        if not signals:
            return {"ok": False, "reason": "no_signal"}
        if not roll_dice():
            return {"ok": False, "reason": "quiet"}

    if not has_image_app():
        return {"ok": False, "reason": "no_image_app", "hint": "没有生图应用"}

    pinned = ""
    try:
        from workers.mood_shift import live_mood
        pinned = live_mood()
    except Exception:
        pinned = ""
    mood_extra = ""
    if pinned:
        mood_extra = (
            f"这场必须先{pinned}。text 和 scene 都要让人一眼看出{pinned}。"
            "画面里只有她，不要画他。"
        )

    feed = signals or (["他点名要一句"] if force else [])
    parsed, err = _pick_draft(existing, feed, extra=mood_extra)
    if err in ("repeat", "other_person"):
        extra = " ".join(x for x in (mood_extra, _SOLO_RETRY if err == "other_person" else _RETRY) if x)
        parsed, err = _pick_draft(existing, feed, extra=extra)
    if err in ("repeat", "other_person"):
        return {"ok": False, "reason": err}
    if err or not parsed:
        return {"ok": False, "reason": "llm_failed", "error": err or "empty"}

    if not force and not bool(parsed.get("worth_saying")):
        return {"ok": False, "reason": "no_signal"}

    text = str(parsed.get("text") or "").strip()
    mood = pinned or str(parsed.get("mood") or "").strip()
    scene = str(parsed.get("scene") or "").strip()

    src, img_err = generate_image(scene or text, mood=mood)
    if img_err == "no_image_app":
        return {"ok": False, "reason": "no_image_app", "hint": "没有生图应用"}
    if src is None:
        return {"ok": False, "reason": "image_failed", "error": img_err, "text": text}

    dst = copy_to_gallery(src, now.strftime("%Y-%m-%d"))
    entry = _append_gallery(
        now.strftime("%Y-%m-%dT%H:%M:%S"),
        rel_path(dst),
        text,
        mood,
        scene,
        path=gallery_path,
    )
    hours = mark_posted(now, state_path=state_path)
    try:
        from workers.she_gallery_feedback import set_inbox
        set_inbox(entry, state_path=state_path)
    except Exception:
        pass
    logger.info("she_gallery posted · next lock %.1fh · signals=%s", hours, ",".join(signals) or "-")
    return {"ok": True, "signals": signals, "cooldown_hours": round(hours, 2), **entry}
