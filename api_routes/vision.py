"""api_routes/vision.py · 视觉模型配置 2 路由 (wish-4a6331b2)

GET  /vision-config  · 读当前视觉模型配置 (api_key 掩码)
POST /vision-config  · 写 + 可选烟测 (传 test=true)
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
            # 用去尾后的 _clean_url(否则贴了完整端点时·测试会拼成 .../chat/completions/chat/completions → 404)
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
