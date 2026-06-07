"""
workers/favorites.py
=====================

卷三十三 · 统一收藏夹

为什么需要这玩意：
  BRO 说"信息雷达 / 掘金机会 / 可行性分析都要有收藏功能" —— 但雷达的"⭐ starred"
  已经是 radar_feedback 里 4 种反馈之一·跟"thumbs_up/thumbs_down/hidden"同组·
  不能挪走。所以这里只管"掘金机会 + 可行性分析"两类·radar 维持现状。

  统一视图 list_favorites() 把三类汇总·让 BRO 一处看全。

数据结构 data/favorites.json:
  {
    "updated_at": "...",
    "items": {
      "opp:<opp_id>": {
        "kind": "opportunity",
        "ref_id": "<opp_id>",
        "title_snap": "标题快照（防数据滚动）",
        "domain": "self-evolve / 用户自建领域 ...",
        "starred_at": "...",
        "note": "用户 的备注"
      },
      "feas:<opp_id>": {
        "kind": "feasibility",
        "ref_id": "<opp_id>",  # 复用 opp_id · 因为可行性是挂在机会上的
        "title_snap": "...",
        "domain": "...",
        "starred_at": "...",
        "note": "..."
      }
    }
  }

红线：
  - 收藏 ≠ 反馈·收藏是 "BRO 想多看几眼" · 反馈是 "BRO 对它怎么看"
  - 不和 outcomes 系统耦合（执行反馈是另一回事·见 workers/outcomes.py）
  - 卷三十三补丁：雷达 starred 仍在 radar_feedback.py · 这里只管 opp + feasibility
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
FAV_FILE = DATA_DIR / "favorites.json"

logger = logging.getLogger("opus.favorites")

VALID_KINDS = {"opportunity", "feasibility"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, text: str) -> None:
    """卷四十六 III · wish-badd4 收编到 safe_write
    favorites.json 是 BRO 标记的兴趣项·backup=True"""
    from .safe_write import atomic_write_text
    atomic_write_text(path, text, backup=True)


def _key(kind: str, ref_id: str) -> str:
    short = {"opportunity": "opp", "feasibility": "feas"}.get(kind, kind)
    return f"{short}:{ref_id}"


def _load_all() -> dict:
    if not FAV_FILE.exists():
        return {"updated_at": None, "items": {}}
    try:
        d = json.loads(FAV_FILE.read_text(encoding="utf-8"))
        if not isinstance(d.get("items"), dict):
            d["items"] = {}
        return d
    except Exception as e:
        logger.warning("favorites.json corrupt: %s · 重置", e)
        return {"updated_at": None, "items": {}}


def _save_all(d: dict) -> None:
    d["updated_at"] = _now_iso()
    _atomic_write(FAV_FILE, json.dumps(d, ensure_ascii=False, indent=2))


def add_favorite(
    kind: str,
    ref_id: str,
    *,
    title_snap: str = "",
    domain: str = "",
    note: Optional[str] = None,
) -> dict:
    """收藏一项·重复收藏 = no-op(只更新 note)"""
    if kind not in VALID_KINDS:
        return {"ok": False, "error": f"kind 必须是 {sorted(VALID_KINDS)}·收到 {kind!r}"}
    if not ref_id:
        return {"ok": False, "error": "ref_id 必填"}
    d = _load_all()
    items = d.setdefault("items", {})
    k = _key(kind, ref_id)
    entry = items.get(k) or {}
    is_new = "starred_at" not in entry
    entry["kind"] = kind
    entry["ref_id"] = ref_id
    if title_snap:
        entry["title_snap"] = title_snap[:200]
    if domain:
        entry["domain"] = domain
    if note is not None:
        entry["note"] = note.strip()[:200]
    if is_new:
        entry["starred_at"] = _now_iso()
    items[k] = entry
    _save_all(d)
    logger.info("add_favorite · %s · %s", kind, ref_id)
    return {"ok": True, "key": k, "entry": entry, "was_new": is_new}


def remove_favorite(kind: str, ref_id: str) -> dict:
    if kind not in VALID_KINDS:
        return {"ok": False, "error": f"kind 必须是 {sorted(VALID_KINDS)}"}
    d = _load_all()
    items = d.get("items") or {}
    k = _key(kind, ref_id)
    if k not in items:
        return {"ok": True, "no_op": True}
    items.pop(k)
    _save_all(d)
    return {"ok": True, "removed": k}


def toggle_favorite(
    kind: str,
    ref_id: str,
    *,
    title_snap: str = "",
    domain: str = "",
    note: Optional[str] = None,
) -> dict:
    """收藏 ↔ 取消收藏 · UI 点 ⭐ 一键切换用这个"""
    d = _load_all()
    k = _key(kind, ref_id)
    if k in (d.get("items") or {}):
        r = remove_favorite(kind, ref_id)
        return {"ok": True, "now_starred": False, **{k: v for k, v in r.items() if k != "ok"}}
    r = add_favorite(kind, ref_id, title_snap=title_snap, domain=domain, note=note)
    return {"ok": True, "now_starred": True, **{k: v for k, v in r.items() if k != "ok"}}


def is_favorited(kind: str, ref_id: str) -> bool:
    d = _load_all()
    return _key(kind, ref_id) in (d.get("items") or {})


def fav_set(kind: str) -> set[str]:
    """返回某 kind 下所有 ref_id 的 set · O(1) 查询用"""
    d = _load_all()
    items = d.get("items") or {}
    return {e["ref_id"] for k, e in items.items() if e.get("kind") == kind}


def list_favorites(*, kind: Optional[str] = None, max_items: int = 100) -> dict:
    """列收藏·按 starred_at 倒序

    返回：
      {
        updated_at, total,
        by_kind: {opportunity: N, feasibility: N},
        items: [{kind, ref_id, title_snap, domain, starred_at, note}, ...]
      }
    """
    d = _load_all()
    items = d.get("items") or {}
    by_kind: dict[str, int] = {k: 0 for k in VALID_KINDS}
    rows: list[dict] = []
    for k, e in items.items():
        kk = e.get("kind") or "?"
        by_kind[kk] = by_kind.get(kk, 0) + 1
        if kind and kk != kind:
            continue
        rows.append({
            "key": k,
            "kind": kk,
            "ref_id": e.get("ref_id"),
            "title_snap": e.get("title_snap"),
            "domain": e.get("domain"),
            "starred_at": e.get("starred_at"),
            "note": e.get("note"),
        })
    rows.sort(key=lambda x: x.get("starred_at") or "", reverse=True)
    return {
        "updated_at": d.get("updated_at"),
        "total": len(rows) if kind else sum(by_kind.values()),
        "by_kind": by_kind,
        "items": rows[:max_items],
    }


def annotate_with_favorites(items: list[dict], *, kind: str, id_field: str = "id") -> list[dict]:
    """给一批 items 注入 is_favorited 字段 · UI 渲染时一次性 batch"""
    if not items:
        return items
    fav = fav_set(kind)
    out: list[dict] = []
    for it in items:
        new = dict(it)
        new["is_favorited"] = (it.get(id_field) or "") in fav
        out.append(new)
    return out
