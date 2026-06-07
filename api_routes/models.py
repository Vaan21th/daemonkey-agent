"""api_routes/models.py · /models + /models/switch

wish-413999da phase 1 · 2 路由 · 模型 list + 切换 (热重建 RUNTIME)

(originally planned as models_providers.py · phase 1 当时误判 providers
系列不存在 → 实际 baseline 有 6 个 /provider-configs · 已补到 providers.py
卷四十六续 18)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException

from api_routes._deps import check_auth
from daemon_runtime import RUNTIME

router = APIRouter()


@router.get("/models")
async def list_models(authorization: Optional[str] = Header(None)):
    """卷二十九 · 给 WebUI 模型切换器用 · 返当前模型 + 可切换列表

    卷三十七升级 · 从 provider_configs.json 拉 pinned configs 当选项 ·
    切换时连 base_url / key 一起切 · 不再只切 model
    """
    check_auth(authorization)
    try:
        from workers.provider_configs import list_configs
        from model_aliases import family_of, supports_anthropic_cache

        data = list_configs(include_keys=False)
        active_id = data.get("active_id")
        options = []
        for c in data.get("configs") or []:
            if not c.get("pinned"):
                continue
            real = c.get("model", "")
            options.append({
                "alias": c["id"],
                "real_id": real,
                "name": c.get("name") or real,
                "family": family_of(real),
                "cache": supports_anthropic_cache(real),
                "note": f"{c.get('provider_kind')} · {c.get('base_url') or '(SDK 默认)'}",
                "current": c["id"] == active_id,
                "config_id": c["id"],
            })
        current_real = RUNTIME.model or ""
        return {
            "current": {
                "model": current_real,
                "family": family_of(current_real) if current_real else "unknown",
                "provider": RUNTIME.provider,
                "base_url": RUNTIME.base_url,
                "cache": supports_anthropic_cache(current_real) if current_real else False,
                "config_id": active_id,
            },
            "options": options,
        }
    except Exception as e:
        raise HTTPException(500, f"list models failed: {e}")


@router.post("/models/switch")
async def switch_model(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """卷二十九 · 切换当前模型

    卷三十七升级 · 'model' 字段实际是 config_id (右上角 alias) ·
    切到一条完整 provider config · 不是单切 model 字段
    """
    check_auth(authorization)
    cfg_id = (payload or {}).get("model", "").strip() or (payload or {}).get("config_id", "").strip()
    if not cfg_id:
        raise HTTPException(400, "model (config_id) field is required")
    try:
        from workers.provider_configs import get_config
        from model_aliases import family_of
        from daemon_api import _activate_provider_config

        cfg = get_config(cfg_id, include_key=False)
        if cfg is None:
            raise HTTPException(404, f"config not found: {cfg_id}")
        old = RUNTIME.model or "(unset)"
        _activate_provider_config(cfg_id)
        return {
            "ok": True,
            "before": old,
            "after": RUNTIME.model,
            "family": family_of(RUNTIME.model or ""),
            "note": "已切到 " + (cfg.get("name") or cfg_id) + " · session 不丢",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"switch model failed: {type(e).__name__}: {e}")
