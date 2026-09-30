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


@router.get("/tool-profiles")
async def list_tool_profiles(authorization: Optional[str] = Header(None)):
    """wish-16fa5930 · 会话能力档位清单（给选档卡 / 顶栏 chip / 管理页用）
    · wish-6350cced：profile_list 已合并用户预设（带 user: true 标记）"""
    check_auth(authorization)
    try:
        from workers.tool_profiles import profile_list, suggest_profile
        return {"ok": True, "profiles": profile_list(), "suggested": suggest_profile()}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "profiles": []}


@router.post("/profiles/save")
async def save_profile(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    """wish-6350cced · 装配台「保存为预设」→ data/cognition/tool_profiles_user.json。

    与内置分离：升级永不覆盖。入参 {name, desc?, tools[], soul_thickness?, based_on?}。
    返回新 id（u- 开头）。校验在 workers.tool_profiles.save_user_preset。
    """
    check_auth(authorization)
    payload = payload or {}
    try:
        from workers.tool_profiles import save_user_preset
        pid, err = save_user_preset(payload)
        if err:
            return {"ok": False, "error": err}
        return {"ok": True, "id": pid}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@router.post("/profiles/delete")
async def delete_profile(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    """删一个用户预设（内置拒删）。入参 {id}。"""
    check_auth(authorization)
    payload = payload or {}
    try:
        from workers.tool_profiles import delete_user_preset
        ok, err = delete_user_preset(str(payload.get("id") or ""))
        return {"ok": True} if ok else {"ok": False, "error": err}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@router.post("/profiles/default")
async def set_profile_default(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    """wish-0571fd96 · 钉「新对话默认档」（standard = 恢复出厂默认）。入参 {id}。

    任意档位（含自设预设）可钉；daemon 侧存储 → 电脑 / 手机打开一致。
    """
    check_auth(authorization)
    payload = payload or {}
    try:
        from workers.tool_profiles import set_user_default
        ok, err = set_user_default(str(payload.get("id") or ""))
        return {"ok": True} if ok else {"ok": False, "error": err}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@router.post("/profiles/override")
async def save_builtin_override_ep(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    """wish-36ef3ea9 续 · 内置档编辑：把当前状态存成用户覆盖（升级永不覆盖 · 可还原出厂）。

    入参 {pid, tools[], layers?}；clear=true 时 = 还原出厂。
    """
    check_auth(authorization)
    payload = payload or {}
    try:
        from workers.tool_profiles import save_builtin_override, clear_builtin_override
        pid = str(payload.get("pid") or "")
        if payload.get("clear"):
            ok, err = clear_builtin_override(pid)
        else:
            ok, err = save_builtin_override(pid, payload)
        return {"ok": True} if ok else {"ok": False, "error": err}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@router.post("/profiles/update")
async def update_preset_ep(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    """wish-36ef3ea9 续 · 编辑一个用户预设：更新当前定义（保留创建时快照）。入参 {id, tools[], layers?, name?, desc?}。"""
    check_auth(authorization)
    payload = payload or {}
    try:
        from workers.tool_profiles import update_user_preset
        ok, err = update_user_preset(str(payload.get("id") or ""), payload)
        return {"ok": True} if ok else {"ok": False, "error": err}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@router.post("/profiles/meta")
async def update_preset_meta_ep(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    """wish-4607fd37 · 改用户预设的名称 / 描述（窄通道：不碰工具与层）。

    跟 /profiles/update 分开是故意的：那条要求带 tools[]，只改名会被拒 + 重置快照。
    入参 {id, name, desc?}。
    """
    check_auth(authorization)
    payload = payload or {}
    try:
        from workers.tool_profiles import update_user_preset_meta
        ok, err = update_user_preset_meta(str(payload.get("id") or ""), payload)
        return {"ok": True} if ok else {"ok": False, "error": err}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@router.post("/profiles/restore")
async def restore_preset_ep(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    """wish-36ef3ea9 续 · 预设回到「最初创建时的状态」。入参 {id}。"""
    check_auth(authorization)
    payload = payload or {}
    try:
        from workers.tool_profiles import restore_user_preset
        ok, err = restore_user_preset(str(payload.get("id") or ""))
        return {"ok": True} if ok else {"ok": False, "error": err}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


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
        from provider_presets import resolve_think_off  # wish-33624071 · 关思考能力声明表
        from provider_presets import EFFORT_STANDARD_LEVELS, resolve_effort_profile  # wish-4fd607c5

        data = list_configs(include_keys=False)
        active_id = data.get("active_id")
        options = []
        for c in data.get("configs") or []:
            if not c.get("pinned"):
                continue
            real = c.get("model", "")
            _to_mode, _to_token = resolve_think_off(real, c.get("base_url") or "")
            options.append({
                "alias": c["id"],
                "real_id": real,
                "name": c.get("name") or real,
                "family": family_of(real),
                "cache": supports_anthropic_cache(real),
                "think_off": _to_mode,        # wish-33624071 · api_param / soft_prompt / none
                "think_off_token": _to_token,  # 仅 soft_prompt 非空 (如 /no_think)
                "note": f"{c.get('provider_kind')} · {c.get('base_url') or '(SDK 默认)'}",
                "current": c["id"] == active_id,
                "config_id": c["id"],
            })
        current_real = RUNTIME.model or ""
        _cur_th_mode, _cur_th_token = resolve_think_off(current_real, RUNTIME.base_url or "")
        # wish-4fd607c5 v2 · UI 永远摆通用标准档 (泛用) · 每模型的接受集合/默认/说明来自这张表
        _cur_eff_supported, _cur_eff_default, _cur_eff_note = resolve_effort_profile(
            current_real, RUNTIME.base_url or "")
        from provider_presets import map_effort_level
        _cur_eff_map = {lv: map_effort_level(lv, current_real, RUNTIME.base_url or "")
                        for lv in EFFORT_STANDARD_LEVELS}
        # BRO 2026-07-28 · 前端协同 toggle 禁用判断用: 当前模型=总监模型时协同无意义
        director_info = None
        try:
            from workers.director import get_director_config as _get_dcfg
            _d = _get_dcfg()
            if _d:
                director_info = {
                    "model": (_d.get("model") or "").strip(),
                    "name": (_d.get("name") or "").strip(),
                }
        except Exception:
            pass
        return {
            "current": {
                "model": current_real,
                "family": family_of(current_real) if current_real else "unknown",
                "provider": RUNTIME.provider,
                "base_url": RUNTIME.base_url,
                "cache": supports_anthropic_cache(current_real) if current_real else False,
                "config_id": active_id,
                # wish-33624071 · 当前模型能不能真关思考·UI 据此标灰开关
                "think_off": _cur_th_mode,
                "think_off_token": _cur_th_token,
                # wish-4fd607c5 v2 · 标准档全集 + 每档实际发什么 (UI 标注「→高」)
                "effort_levels": list(EFFORT_STANDARD_LEVELS),
                "effort_default": _cur_eff_default,
                "effort_note": _cur_eff_note,
                "effort_map": _cur_eff_map,
                "effort_supported": list(_cur_eff_supported),
            },
            "director": director_info,
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
        # source="user": 顶栏手动切 · 落会话记忆 + 新会话继承它 (2026-09-23 治「切了被打回」)
        _activate_provider_config(
            cfg_id, sid=str((payload or {}).get("session_id") or ""), source="user")
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
