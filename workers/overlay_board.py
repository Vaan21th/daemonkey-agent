"""插件库「我的叠层」清单。只汇编，不执行用户代码。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from workers.mod_health import inspect_and_save, load_saved
from workers.mod_runtime import ROOT, _iter_py, list_mods


def _skins(base: Path) -> list:
    d = base / "static" / "user" / "skins"
    if not d.is_dir():
        return []
    out = []
    for folder in sorted(d.iterdir()):
        if not folder.is_dir():
            continue
        meta = {}
        sj = folder / "skin.json"
        if sj.is_file():
            try:
                meta = json.loads(sj.read_text(encoding="utf-8-sig"))
            except Exception:
                meta = {}
        if not isinstance(meta, dict):
            meta = {}
        out.append({
            "id": folder.name,
            "name": str(meta.get("name") or folder.name),
            "version": str(meta.get("version") or "1.0.0"),
            "hint": "换肤在右上角调色板，不在这里开关",
        })
    return out


def _decorate(base: Path) -> dict:
    ujs = base / "static" / "user" / "user.js"
    ucss = base / "static" / "user" / "user.css"
    return {
        "user_js": ujs.is_file(),
        "user_css": ucss.is_file(),
        "user_js_bytes": ujs.stat().st_size if ujs.is_file() else 0,
        "hint": "侧栏自定义页来自 user.js，不是一份 MOD",
    }


def _user_tools(base: Path, health: dict) -> list:
    bad = {u.get("file"): u for u in (health.get("user_tools") or [])}
    ud = base / "agent_tools_user"
    out = []
    for p in _iter_py(ud):
        rel = f"agent_tools_user/{p.name}"
        hit = bad.get(rel) or {}
        out.append({
            "file": rel,
            "ok": not hit,
            "problems": list(hit.get("problems") or []),
            "hint": "想分享就挪进 data/mods/<id>/tools/",
        })
    return out


def _mods(base: Path, health: dict) -> list:
    by_id = {m.get("id"): m for m in (health.get("mods") or [])}
    out = []
    for m in list_mods(base):
        hit = by_id.get(m["id"]) or {}
        problems = list(hit.get("problems") or [])
        ok = bool(hit.get("ok", True)) if hit else True
        out.append({
            "id": m["id"],
            "name": m.get("name") or m["id"],
            "version": m.get("version") or "1.0.0",
            "enabled": bool(m.get("enabled")),
            "ok": ok,
            "problems": problems,
            "has_ui": bool(m.get("js")),
            "hint": (
                f"说「停用 MOD {m['id']}」回官方"
                if m.get("enabled") and not ok else ""
            ),
        })
    return out


def inventory(*, refresh: bool = False, root: Optional[Path] = None) -> dict:
    base = root or ROOT
    if refresh:
        inspect_and_save(base)
    health = load_saved(base)
    return {
        "health": {
            "checked_at": health.get("checked_at") or "",
            "alert": int(health.get("alert") or 0),
        },
        "mods": _mods(base, health),
        "user_tools": _user_tools(base, health),
        "skins": _skins(base),
        "decorate": _decorate(base),
    }
