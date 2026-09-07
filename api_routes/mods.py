"""叠层 MOD 清单 + UI 资产 + 我的改装看板。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api_routes._deps import check_auth
from workers.mod_runtime import ROOT, list_mods, sanitize_id

router = APIRouter()
_UI_ALLOW = {"mod.js": "application/javascript; charset=utf-8",
             "mod.css": "text/css; charset=utf-8"}


class EnabledBody(BaseModel):
    enabled: bool


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


@router.get("/api/overlays/health")
async def api_overlay_health(authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    from workers.mod_health import load_saved
    saved = load_saved()
    return {"alert": int(saved.get("alert") or 0),
            "checked_at": saved.get("checked_at") or ""}


@router.get("/api/overlays")
async def api_overlays(refresh: bool = False,
                       authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    from workers.overlay_board import inventory
    return inventory(refresh=refresh)


@router.post("/api/mods/{mod_id}/enabled")
async def api_mod_enabled(mod_id: str, body: EnabledBody,
                          authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    from workers.mod_health import disable, enable, inspect_and_save
    mid = sanitize_id(mod_id)
    ok, msg = enable(mid) if body.enabled else disable(mid)
    if not ok:
        raise HTTPException(400, msg)
    inspect_and_save()
    return {"ok": True, "output": msg}


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
