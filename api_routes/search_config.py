"""GET/POST /search-config · 外网搜索 KEY（掩码，可选）。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException

from api_routes._deps import check_auth

router = APIRouter()


@router.get("/search-config")
async def get_search_config(authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    from workers.search_config import get_active_search, load_search_config, mask_key

    cfg = load_search_config()
    _prov, _key, source = get_active_search()
    return {
        "provider": cfg.get("provider") or "bocha",
        "enabled": bool(cfg.get("enabled", True)),
        "configured": bool(cfg.get("configured")),
        "api_key": mask_key(cfg.get("api_key") or ""),
        "source": source,
        "active": bool(_key),
    }


@router.post("/search-config")
async def set_search_config(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    check_auth(authorization)
    from workers.search_config import get_active_search, save_search_config

    action = (payload.get("action") or "").strip()
    patch = {}
    if "enabled" in payload:
        patch["enabled"] = bool(payload["enabled"])
    if "provider" in payload:
        patch["provider"] = payload["provider"]
    raw_key = (payload.get("api_key") or "").strip()
    if raw_key and "****" not in raw_key:
        patch["api_key"] = raw_key

    saved = None
    if patch and action != "test":
        saved = save_search_config(patch)

    if action == "test":
        _prov, key, _src = get_active_search()
        if raw_key and "****" not in raw_key:
            key = raw_key
            _prov = _prov or "bocha"
        if not key:
            raise HTTPException(400, "还没贴搜索 KEY · 不填也能搜，只是中文长尾会弱")
        try:
            from agent_tools._web_search_bocha import search_bocha
            rows = search_bocha("口播文案技巧", 4, key)
        except Exception as e:
            return {"ok": False, "test": {"ok": False, "error": str(e)[:220]}}
        heads = [r.get("title") or r.get("url") for r in rows[:3]]
        return {
            "ok": True,
            "test": {"ok": True, "n": len(rows), "titles": heads},
            "config_saved": bool(saved),
        }

    from workers.search_config import get_active_search as _again, load_search_config, mask_key
    cfg = saved or load_search_config()
    _p, _k, source = _again()
    return {
        "ok": True,
        "configured": bool(cfg.get("configured")),
        "enabled": bool(cfg.get("enabled", True)),
        "active": bool(_k),
        "source": source,
        "api_key": mask_key(cfg.get("api_key") or ""),
    }
