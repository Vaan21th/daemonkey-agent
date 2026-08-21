"""api_routes/vision.py · 视觉模型配置 + Embedding 语义检索配置 (wish-4a6331b2 + wish-b313583b)

GET  /vision-config  · 读当前视觉模型配置 (api_key 掩码)
POST /vision-config  · 写 + 可选烟测 (传 test=true)
GET  /embed-config   · 读 embedding 语义检索状态 (开关/覆盖/模型 · 复用智谱 provider)
POST /embed-config   · 写 embedding 开关 / 触发回填
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException

from api_routes._deps import check_auth

router = APIRouter()


def _mask(s: str) -> str:
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "****" + s[-4:]


@router.get("/vision-config")
async def get_vision_config(authorization: Optional[str] = Header(None)):
    """读当前视觉模型配置。api_key 掩码返回。"""
    check_auth(authorization)
    from workers.vision_config import load_vision_config

    cfg = load_vision_config()
    masked = dict(cfg)
    if masked.get("api_key"):
        masked["api_key"] = _mask(masked["api_key"])
    return masked


@router.post("/vision-config")
async def set_vision_config(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """写入视觉模型配置。可选 test=true 做一次烟测。

    payload: { model, base_url, api_key, test?: bool }
    """
    check_auth(authorization)

    model = (payload.get("model") or "").strip()
    base_url = (payload.get("base_url") or "").strip()
    api_key = (payload.get("api_key") or "").strip()
    do_test = bool(payload.get("test"))

    if not model:
        raise HTTPException(400, "model is required")
    if not base_url:
        raise HTTPException(400, "base_url is required")
    if not api_key:
        raise HTTPException(400, "api_key is required")
    if "****" in api_key:
        # 社区 7/31 反馈: GET 回显的是掩码·前端原样回传保存会覆盖真 key → 永久 401
        raise HTTPException(400, "api_key 是掩码显示值 (含 ****)·请粘贴完整 API key 再保存")
    if not base_url.startswith("https://"):
        raise HTTPException(400, "base_url must start with https://")

    # 自动去尾 · 用户可能贴完整端点 · OpenAI SDK 自己会加 /chat/completions
    _clean_url = base_url.rstrip("/")
    if _clean_url.endswith("/chat/completions"):
        _clean_url = _clean_url[: -len("/chat/completions")]

    from workers.vision_config import save_vision_config

    cfg = {"model": model, "base_url": _clean_url, "api_key": api_key}
    save_vision_config(cfg)

    test_result = None
    if do_test:
        try:
            from openai import OpenAI
            # 测试连接 · 给慢视觉/thinking 模型 buffer · 比主超时短让 key 错时快失败
            client = OpenAI(api_key=api_key, base_url=_clean_url, timeout=60)
            resp = client.chat.completions.create(
                model=model,
                max_tokens=30,
                messages=[{"role": "user", "content": "say 'ok' in one word"}],
            )
            test_result = {
                "ok": True,
                "reply": resp.choices[0].message.content or "",
                "ms": 0,
            }
        except Exception as e:
            test_result = {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
            }

    return {
        "saved": True,
        "model": model,
        "base_url": _clean_url,
        "api_key_masked": _mask(api_key),
        "test": test_result,
    }


# ──────────────────────────────────────────────────────────────
# Embedding 语义检索配置 (wish-b313583b · BRO 拍板放视觉 tab 一起 · 改名"视觉 & Embedding")
# 配置存 data/embedding_config.json · 可自定义 model/base_url/api_key · 兼容开源纯净版
# 优先级: 用户自配 → 智谱 provider fallback (母体开箱即用) → .env
# ──────────────────────────────────────────────────────────────

@router.get("/embed-config")
async def get_embed_config(authorization: Optional[str] = Header(None)):
    """读 embedding 语义检索状态 + 配置。api_key 掩码。"""
    check_auth(authorization)

    try:
        from workers.memory_embed import load_config, stats
        from workers.memory_index import _get_conn
    except ImportError as e:
        # numpy 未装的老用户 (0.9.6 前 requirements 从未登记它) —— 返回缺依赖态代替裸 500
        return {"enabled": False, "configured": False, "missing_dep": e.name,
                "error": f"缺依赖 {e.name} · 到启动器「环境」页点【开始安装】补装后重启即恢复",
                "covered": 0, "total": 0}

    conn = _get_conn()
    st = stats(conn)
    conn.close()

    cfg = load_config()
    masked = {
        "enabled": cfg.get("enabled", True),
        "configured": cfg.get("configured", False),
        "source": cfg.get("source", ""),          # user / zhipu-provider / env / ''
        "model": cfg.get("model", ""),
        "base_url": cfg.get("base_url", ""),
        "api_key": _mask(cfg["api_key"]) if cfg.get("api_key") else "",
        "covered": st["covered"],
        "total": st["total"],
    }
    return masked


@router.post("/embed-config")
async def set_embed_config(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """写 embedding 配置。payload: { model?, base_url?, api_key?, enabled?, action?: 'backfill'|'test' }"""
    check_auth(authorization)

    from workers.memory_embed import save_config, load_config

    result = {}

    # 保存配置 (model/base_url/api_key/enabled 任一存在即写)
    save_keys = [k for k in ("model", "base_url", "api_key", "enabled") if k in payload]
    if save_keys:
        cfg = {}
        for k in save_keys:
            cfg[k] = payload[k]
        if "api_key" in cfg and ("****" in str(cfg["api_key"]) or not str(cfg["api_key"]).strip()):
            # 掩码回传 / 空 → 保留原 key (不覆盖)
            cfg.pop("api_key")
        ok = save_config(cfg)
        result["config_saved"] = ok
        result["saved_keys"] = save_keys

    if payload.get("action") == "backfill":
        import threading

        def _do_backfill():
            try:
                from workers.memory_embed import backfill_all
                from workers.memory_index import _get_conn
                conn = _get_conn()
                ok, fail = backfill_all(conn)
                conn.close()
                import logging
                logging.getLogger("memory_embed").info("backfill done ok=%s fail=%s", ok, fail)
            except Exception:
                pass

        threading.Thread(target=_do_backfill, daemon=True).start()
        result["backfill_started"] = True

    if payload.get("action") == "test":
        # 烟测: 用提交的 (或已存) 配置试 embed 一次
        # 掩码 key (sk-****xxxx) 不能当真 key 测 → 忽略用已存
        _pk = payload.get("api_key") or ""
        _use_key = "" if "****" in str(_pk) else _pk
        test_key = _use_key or load_config().get("api_key") or ""
        test_model = payload.get("model") or load_config().get("model") or ""
        test_base = payload.get("base_url") or load_config().get("base_url") or ""
        if not (test_key and test_model and test_base):
            result["test"] = {"ok": False, "error": "model/base_url/api_key 都要有才能测试"}
        else:
            try:
                import requests
                r = requests.post(
                    f"{test_base.rstrip('/')}/embeddings",
                    headers={"Authorization": f"Bearer {test_key}"},
                    json={"model": test_model, "input": ["连接测试"]},
                    timeout=60,
                )
                if r.status_code == 200:
                    data = r.json()
                    dim = len((data.get("data") or [{}])[0].get("embedding", []))
                    result["test"] = {"ok": True, "dim": dim, "ms": r.elapsed.total_seconds() * 1000}
                else:
                    result["test"] = {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:150]}"}
            except Exception as e:
                result["test"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    if not result:
        raise HTTPException(400, "no valid payload (model/base_url/api_key/enabled/action)")
    return result
