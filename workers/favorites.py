"""
workers/favorites.py
=====================

统一收藏夹

为什么需要这玩意：
  用户 说"信息雷达 / 掘金机会 / 可行性分析都要有收藏功能" —— 但雷达的"⭐ starred"
  已经是 radar_feedback 里 4 种反馈之一·跟"thumbs_up/thumbs_down/hidden"同组·
  不能挪走。所以这里管"掘金机会 + 可行性分析 + 产物"三类·radar 维持现状。

  统一视图 list_favorites() 把三类汇总·让 用户 一处看全。

  2026-09-18 · 加 kind=output (产物库的稿/演示稿/表格/原型)：
  用户 的痛点原话是「找不到之前做出来非常有用的东西」——是筛选需求·不是穷尽
  归档需求。所以没做文件夹·而是复用本文件已有的收藏机制 (加一个 kind)。
  output 独有 category 字段：用户 自己命名的分类 (客户交付 / 模板 / 常用参考…)。

数据结构 data/favorites.json:
  {
    "updated_at": "...",
    "items": {
      "opp:<opp_id>": {
        "kind": "opportunity",
        "ref_id": "<opp_id>",
        "title_snap": "标题快照（防数据滚动）",
        "domain": "ai / super-individual / ...",
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
  - 收藏 ≠ 反馈·收藏是 "用户 想多看几眼" · 反馈是 "用户 对它怎么看"
  - 不和 outcomes 系统耦合（执行反馈是另一回事·见 workers/outcomes.py）
  - 补丁：雷达 starred 仍在 radar_feedback.py · 这里只管 opp + feasibility + output
  - ⚠ 加新 kind 要同步改两处白名单·否则会【静默滤掉】不是报错：
      api_routes/dashboard.py  的 domain == "favorites" 分支 (kind in (...))
      api_routes/intelligence.py 的 POST /favorites (kind not in (...))
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

VALID_KINDS = {"opportunity", "feasibility", "output"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, text: str) -> None:
    """III · wish-badd4 收编到 safe_write
    favorites.json 是 用户 标记的兴趣项·backup=True"""
    from .safe_write import atomic_write_text
    atomic_write_text(path, text, backup=True)


def _key(kind: str, ref_id: str) -> str:
    short = {"opportunity": "opp", "feasibility": "feas", "output": "out"}.get(kind, kind)
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
        logger.warning("favorites.json corrupt: %s · 备份后重置", e)
        # B-① · 2026-08-27 · 损坏备份再重置 · 防随后一次写盘清空收藏 (Grok 全量审计)
        try:
            import shutil
            import time as _t
            bak = FAV_FILE.with_name(f"favorites.json.corrupt-{int(_t.time())}")
            shutil.copy2(FAV_FILE, bak)
            logger.warning("已备份损坏文件到 %s", bak.name)
        except Exception:
            pass
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
    category: Optional[str] = None,
) -> dict:
    """收藏一项·重复收藏 = no-op(只更新 note / category)

    category 只对 kind=output 有意义 (用户 自命名的分类) · 其它 kind 传了也不拦。
    """
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
    if category is not None:
        entry["category"] = category.strip()[:40]
    if is_new:
        entry["starred_at"] = _now_iso()
    items[k] = entry
    _save_all(d)
    logger.info("add_favorite · %s · %s", kind, ref_id)
    return {"ok": True, "key": k, "entry": entry, "was_new": is_new}


def set_category(kind: str, ref_id: str, category: str) -> dict:
    """给已收藏的项改分类·空串 = 移出分类(回到未分类)

    用户 2026-09-18：「收藏当中又要能分类·便于快速查询」——分类是他自己命名的
    字符串·没有预设枚举·所以不校验内容只限长度。
    """
    if kind not in VALID_KINDS:
        return {"ok": False, "error": f"kind 必须是 {sorted(VALID_KINDS)}"}
    d = _load_all()
    items = d.setdefault("items", {})
    k = _key(kind, ref_id)
    if k not in items:
        return {"ok": False, "error": "这项还没收藏·先收藏再分类"}
    items[k]["category"] = (category or "").strip()[:40]
    _save_all(d)
    return {"ok": True, "key": k, "category": items[k]["category"]}


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
    category: Optional[str] = None,
) -> dict:
    """收藏 ↔ 取消收藏 · UI 点 ⭐ 一键切换用这个"""
    d = _load_all()
    k = _key(kind, ref_id)
    if k in (d.get("items") or {}):
        r = remove_favorite(kind, ref_id)
        return {"ok": True, "now_starred": False, **{k: v for k, v in r.items() if k != "ok"}}
    r = add_favorite(kind, ref_id, title_snap=title_snap, domain=domain, note=note, category=category)
    return {"ok": True, "now_starred": True, **{k: v for k, v in r.items() if k != "ok"}}


def is_favorited(kind: str, ref_id: str) -> bool:
    d = _load_all()
    return _key(kind, ref_id) in (d.get("items") or {})


def fav_set(kind: str) -> set[str]:
    """返回某 kind 下所有 ref_id 的 set · O(1) 查询用"""
    d = _load_all()
    items = d.get("items") or {}
    return {e["ref_id"] for k, e in items.items() if e.get("kind") == kind}


def list_favorites(*, kind: Optional[str] = None, max_items: int = 200) -> dict:
    """列收藏·按 starred_at 倒序

    返回：
      {
        updated_at, total,
        by_kind: {opportunity: N, feasibility: N, output: N},
        by_category: {<分类名>: N},   # 只对 kind=output 有意义
        categories: [<分类名>, ...],  # 已用分类·供前端做筛选条
        items: [{kind, ref_id, title_snap, domain, starred_at, note, category}, ...]
      }
    """
    d = _load_all()
    items = d.get("items") or {}
    by_kind: dict[str, int] = {k: 0 for k in VALID_KINDS}
    by_category: dict[str, int] = {}
    rows: list[dict] = []
    for k, e in items.items():
        kk = e.get("kind") or "?"
        by_kind[kk] = by_kind.get(kk, 0) + 1
        cat = (e.get("category") or "").strip()
        if kk == "output" and cat:
            by_category[cat] = by_category.get(cat, 0) + 1
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
            "category": cat,
        })
    rows.sort(key=lambda x: x.get("starred_at") or "", reverse=True)
    return {
        "updated_at": d.get("updated_at"),
        "total": len(rows) if kind else sum(by_kind.values()),
        "by_kind": by_kind,
        "by_category": by_category,
        "categories": sorted(by_category.keys()),
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
