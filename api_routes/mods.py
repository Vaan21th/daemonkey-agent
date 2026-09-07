"""叠层 MOD 清单 + UI 资产。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from workers.mod_runtime import ROOT, list_mods, sanitize_id

router = APIRouter()
_UI_ALLOW = {"mod.js": "application/javascript; charset=utf-8",
             "mod.css": "text/css; charset=utf-8"}


@router.get("/api/mods")
async def api_mods():
    mods = []
    for m in list_mods():
        if not m.get("enabled"):
            continue
        mods.append({
            "id": m["id"], "name": m.get("name") or m["id"],
            "version": m.get("version") or "1.0.0",
            "js": m.get("js") or "", "css": m.get("css") or "",
        })
    return {"mods": mods}


@router.get("/mod-assets/{mod_id}/{filename}")
async def mod_asset(mod_id: str, filename: str):
    mid = sanitize_id(mod_id)
    if filename not in _UI_ALLOW:
        raise HTTPException(404, "asset not allowed")
    full = ROOT / "data" / "mods" / mid / "ui" / filename
    try:
        full.resolve().relative_to((ROOT / "data" / "mods" / mid / "ui").resolve())
    except Exception:
        raise HTTPException(400, "invalid path")
    if not full.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(full, media_type=_UI_ALLOW[filename],
                        headers={"Cache-Control": "no-cache, must-revalidate"})
