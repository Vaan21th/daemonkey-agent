"""api_routes/providers.py · provider 管理 9 路由

卷三十七 · 多 Provider 配置 CRUD (6 路由):
  GET    /provider-configs                  · list (api_key 掩码)
  POST   /provider-configs                  · 新增
  PATCH  /provider-configs/{cfg_id}         · 改
  DELETE /provider-configs/{cfg_id}         · 删
  POST   /provider-configs/{cfg_id}/activate · 切 active · 热重建 RUNTIME · 不重启
  POST   /provider-configs/{cfg_id}/test    · 烟测一条 · 不动 RUNTIME

卷三十六 · 旧 provider 接口 (3 路由) · 前端 chat.js 还在调:
  GET    /providers                         · list presets + active (BRO 新增 config 时挑 OpenAI/Anthropic)
  POST   /providers/test                    · 烟测 (输 base_url/key/model · 不存盘)
  POST   /providers/switch                  · 热切 (输完整四元组 · 直接改 RUNTIME + .env · 不走 cfg 表)

数据存 data/provider_configs.json · 每条 config 独立 api_key
右上角切换器从 pinned=True 的 configs 里出 · BRO 在中栏配置 view 增删改

wish-413999da phase 1-L · 补漏 (phase 1 拆分时这 9 路由整组从 daemon_api.py
删掉但没移到任何 api_routes/*.py · 卷四十六续 18 BRO 看到设置页 'configs 404' 才发现)

依赖 daemon_api 的 module-level helpers · lazy import 防循环依赖:
  _activate_provider_config  · 重建 RUNTIME · 不重启 daemon
  _test_provider_inner       · 烟测一条 config
  _API_LOCK                  · /providers/switch 用 (heat-swap RUNTIME 时上锁)
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException

from api_routes._deps import check_auth
from daemon_runtime import RUNTIME

router = APIRouter()


# ─── 卷三十六 · 旧 provider 接口 (3 路由 · 前端 chat.js 在用) ──────────
@router.get("/providers")
async def list_providers(authorization: Optional[str] = Header(None)):
    """卷三十六 · 列所有 LLM provider 预设 + 当前活动配置.

    UI 用这个填下拉框 · 显示当前选中预设 + 当前 model / base_url / api_key (掩码).
    """
    check_auth(authorization)
    from provider_presets import list_presets, guess_preset_id, mask_api_key
    active = {
        "preset_id": guess_preset_id(RUNTIME.base_url or "", RUNTIME.provider),
        "provider_kind": RUNTIME.provider,
        "model": RUNTIME.model,
        "base_url": RUNTIME.base_url or "",
        "api_key_masked": mask_api_key(
            os.environ.get("OPUS_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or ""
        ),
    }
    return {
        "presets": list_presets(),
        "active": active,
    }


@router.post("/providers/test")
async def test_provider(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """烟测一个 provider 配置 · 不写 .env · 不动 RUNTIME.

    body: {provider_kind, base_url, model, api_key}
    """
    check_auth(authorization)
    provider_kind = (payload.get("provider_kind") or "openai").strip()
    base_url = (payload.get("base_url") or "").strip() or ""
    model = (payload.get("model") or "").strip()
    api_key = (payload.get("api_key") or "").strip()
    if not model or not api_key:
        raise HTTPException(400, "model and api_key are required")
    from daemon_api import _test_provider_inner
    return await _test_provider_inner(
        provider_kind=provider_kind, base_url=base_url, model=model, api_key=api_key
    )


@router.post("/providers/switch")
async def switch_provider(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """热切换 LLM provider · 重建 RUNTIME.client · 写 .env · 不重启 daemon.

    body: {provider_kind, base_url, model, api_key}
    """
    check_auth(authorization)
    provider_kind = (payload.get("provider_kind") or "openai").strip()
    base_url = (payload.get("base_url") or "").strip()
    model = (payload.get("model") or "").strip()
    api_key = (payload.get("api_key") or "").strip()
    if not model or not api_key:
        raise HTTPException(400, "model and api_key are required")
    if provider_kind not in ("openai", "anthropic"):
        raise HTTPException(400, f"unknown provider_kind: {provider_kind}")

    from daemon_provider import write_public_env, setup_client, clean_base_url
    # base_url 去尾(.../v1/chat/completions → .../v1)·避免 SDK 重复拼接 404
    base_url = clean_base_url(base_url)
    # 写 .env 对外用 DAEMONKEY_ 前缀(去 OPUS 泄漏)·write_public_env 同步 os.environ 内核名
    write_public_env("OPUS_PROVIDER", provider_kind)
    write_public_env("OPUS_BASE_URL", base_url)
    write_public_env("OPUS_MODEL", model)
    if provider_kind == "anthropic":
        write_public_env("ANTHROPIC_API_KEY", api_key)
    else:
        write_public_env("OPUS_API_KEY", api_key)

    try:
        client, _default_model, resolved_base = setup_client(provider_kind)
    except SystemExit as e:
        raise HTTPException(500, f"setup_client failed: {e}") from e
    except Exception as e:
        raise HTTPException(500, f"setup_client raised {type(e).__name__}: {e}") from e

    from daemon_api import _API_LOCK
    with _API_LOCK:
        RUNTIME.client = client
        RUNTIME.provider = provider_kind
        RUNTIME.model = model
        RUNTIME.base_url = resolved_base

    return {
        "ok": True,
        "provider_kind": provider_kind,
        "model": model,
        "base_url": resolved_base or "",
        "note": "已热切换 · session 不丢 · 下次发消息走新 provider",
    }


# ─── 卷三十七 · 多 Provider 配置 CRUD (6 路由) ────────────────────────


@router.get("/provider-configs")
async def get_provider_configs(authorization: Optional[str] = Header(None)):
    """列所有 provider configs (api_key 掩码)."""
    check_auth(authorization)
    from workers.provider_configs import list_configs
    return list_configs(include_keys=False)


@router.post("/provider-configs")
async def create_provider_config(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """新增一条 provider config.

    body: {name, provider_kind, base_url, model, api_key, preset_id?, pinned?, set_active?}
    """
    check_auth(authorization)
    from workers.provider_configs import add_config
    try:
        cfg = add_config(
            name=payload.get("name") or "",
            provider_kind=payload.get("provider_kind") or "openai",
            base_url=payload.get("base_url") or "",
            model=payload.get("model") or "",
            api_key=payload.get("api_key") or "",
            preset_id=payload.get("preset_id") or "custom",
            pinned=payload.get("pinned", True),
            set_active=bool(payload.get("set_active")),
            max_tokens=payload.get("max_tokens"),
            vision=payload.get("vision"),  # wish-4a6331b2
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if payload.get("set_active"):
        from daemon_api import _activate_provider_config
        _activate_provider_config(cfg["id"])
    cfg_safe = dict(cfg)
    cfg_safe["api_key"] = "***" if cfg_safe.get("api_key") else ""
    return {"ok": True, "config": cfg_safe}


@router.patch("/provider-configs/{cfg_id}")
async def patch_provider_config(
    cfg_id: str,
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """改一条 config · 只能改: name / base_url / model / api_key / pinned / preset_id.

    如果改的是当前 active config · 自动重建 RUNTIME.
    """
    check_auth(authorization)
    from workers.provider_configs import update_config, get_active_config
    try:
        cfg = update_config(cfg_id, payload or {})
    except KeyError:
        raise HTTPException(404, f"config not found: {cfg_id}")
    active = get_active_config(include_key=False)
    if active and active.get("id") == cfg_id:
        from daemon_api import _activate_provider_config
        _activate_provider_config(cfg_id)
    cfg_safe = dict(cfg)
    cfg_safe["api_key"] = "***" if cfg_safe.get("api_key") else ""
    return {"ok": True, "config": cfg_safe}


@router.delete("/provider-configs/{cfg_id}")
async def delete_provider_config(
    cfg_id: str,
    authorization: Optional[str] = Header(None),
):
    """删一条 config · 如果删的是 active · 自动切到下一条 pinned."""
    check_auth(authorization)
    from workers.provider_configs import delete_config
    try:
        result = delete_config(cfg_id)
    except KeyError:
        raise HTTPException(404, f"config not found: {cfg_id}")
    new_active = result.get("new_active")
    if new_active:
        try:
            from daemon_api import _activate_provider_config
            _activate_provider_config(new_active)
        except Exception as e:
            return {"ok": True, **result,
                    "warning": f"new active config 重建 RUNTIME 失败: {e}"}
    return {"ok": True, **result}


@router.post("/provider-configs/{cfg_id}/activate")
async def activate_provider_config_ep(
    cfg_id: str,
    authorization: Optional[str] = Header(None),
):
    """切换 active config · 重建 RUNTIME · 不重启 daemon · session 不丢."""
    check_auth(authorization)
    from workers.provider_configs import set_active
    try:
        set_active(cfg_id)
    except KeyError:
        raise HTTPException(404, f"config not found: {cfg_id}")
    try:
        from daemon_api import _activate_provider_config
        _activate_provider_config(cfg_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"activate failed: {type(e).__name__}: {e}")
    return {
        "ok": True,
        "active_id": cfg_id,
        "model": RUNTIME.model,
        "provider_kind": RUNTIME.provider,
        "note": "已热切换 · session 不丢",
    }


@router.post("/provider-configs/{cfg_id}/test")
async def test_provider_config_ep(
    cfg_id: str,
    authorization: Optional[str] = Header(None),
):
    """烟测一条已保存的 config · 不动 RUNTIME."""
    check_auth(authorization)
    from workers.provider_configs import get_config
    cfg = get_config(cfg_id, include_key=True)
    if not cfg:
        raise HTTPException(404, f"config not found: {cfg_id}")
    from daemon_api import _test_provider_inner
    return await _test_provider_inner(
        provider_kind=cfg["provider_kind"],
        base_url=cfg.get("base_url") or "",
        model=cfg["model"],
        api_key=cfg["api_key"],
    )
