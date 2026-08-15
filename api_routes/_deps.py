"""
api_routes/_deps.py · 路由共享依赖 (wish-413999da · phase 1)
==========================================================

把 daemon_api.build_app() 内部的 closure helpers (`_check_auth`,
`_check_rate_limit`) 提到 module-level, 让 api_routes/*.py 可以
直接 import 使用。

为什么不用 FastAPI Depends:
  daemon_api 原版直接函数调 `_check_auth(authorization)`, 跟工具/
  workers 共享同一份模式。保持调用风格一致, 后续 phase 2 下沉 services
  时也好统一。

wish-bb84a386 · loopback 鉴权豁免 (2026-05-28 卷四十六续 V):
  问题: BRO 双击 start.bat 后还得手填 OPUS_API_TOKEN ·
       .env token 一被 rotate 就 401 · 部署版每个用户都要折腾。
  解药: 同机访问 127.0.0.1 自动信任·跨网仍需 token (业界 self-host 标准).
  实现: loopback_auth_middleware 在 request 进路由前判断来源 IP ·
       同机就往 scope[headers] 注入 .env 里的 Bearer token →
       现有 check_auth 看到的就是有效 token · 78 处调用零改动。
  禁用: 设 OPUS_LOOPBACK_TRUST=false (远程部署 / 多机共享时)。
"""
from __future__ import annotations

import hmac
import os
from typing import TYPE_CHECKING, Optional

from fastapi import HTTPException

if TYPE_CHECKING:
    from fastapi import Request


def check_auth(authorization: Optional[str]) -> None:
    """Bearer Token 鉴权。

    OPUS_API_TOKEN 未设 → 直接拒绝 (503), 这是安全默认姿态:
    .env 没配 token, API 不可用 (外部入口不会因配置遗漏而裸奔)。
    """
    expected = (os.environ.get("OPUS_API_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="OPUS_API_TOKEN not set; daemon refuses HTTP service for safety.",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing Bearer token")
    if authorization[7:].strip() != expected:
        raise HTTPException(status_code=401, detail="invalid token")
    # 恒时比较 (防时序侧信道 · 本地威胁模型下低优先但零成本 · 龙头 H-01 附带)
    if not hmac.compare_digest(
        authorization[7:].strip().encode("utf-8", "replace"),
        expected.encode("utf-8", "replace"),
    ):
        raise HTTPException(status_code=401, detail="invalid token")


# ────────────────────────────────────────────────────────────────────
# wish-bb84a386 · loopback 鉴权豁免
# ────────────────────────────────────────────────────────────────────

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _loopback_trust_enabled() -> bool:
    """读 env OPUS_LOOPBACK_TRUST · 默认 true (本机访问免 token).

    设 false / 0 / no / off 关闭豁免 (远程部署 / 多机共享场景).
    """
    raw = (os.environ.get("OPUS_LOOPBACK_TRUST") or "true").strip().lower()
    return raw not in ("false", "0", "no", "off", "")


def _is_loopback(request: "Request") -> bool:
    """判断 request 来源是不是同机 (loopback 接口)."""
    if not request or not request.client:
        return False
    host = (request.client.host or "").strip().lower()
    return host in _LOOPBACK_HOSTS


def _host_is_local(request: "Request") -> bool:
    """Host 头必须是本机名 (localhost / 127.0.0.1 / [::1] · 可带端口)。

    只看 client.host 会被两类远程流量伪装成 loopback:
      1. 本机隧道 (cloudflared/frp) 转发来的公网流量 —— client.host 恒为 127.0.0.1
      2. DNS 重绑定 —— 恶意域名解析到 127.0.0.1 后浏览器直连本机端口
    但这两类的 Host 头是公网域名而非本机名 → 联合校验即可拦住 token 注入。
    """
    host = ""
    for k, v in (request.scope.get("headers") or []):
        if k.lower() == b"host":
            try:
                host = v.decode("latin-1", "replace").strip().lower()
            except Exception:
                host = ""
            break
    h = host
    if h.startswith("["):          # IPv6 形如 [::1]:7860
        h = h.split("]", 1)[0].lstrip("[")
    elif ":" in h:                 # IPv4/域名带端口
        h = h.rsplit(":", 1)[0]
    return h in _LOOPBACK_HOSTS


async def loopback_auth_middleware(request: "Request", call_next):
    """FastAPI middleware · 同机访问自动注入有效 Bearer token.

    工作原理:
      1. 取 request.client.host · 判断是不是 127.0.0.1 / ::1 / localhost
      2. 是 + Host 头也是本机名 (防隧道转发/DNS 重绑定伪装·见 _host_is_local)
         + OPUS_LOOPBACK_TRUST 未禁用 → 在 ASGI scope[headers] 注入
         `Authorization: Bearer <env_token>` (覆盖前端可能发的过期 token)
      3. 下游 check_auth 看到的就是有效 token · 78 处调用全零改动
      4. 跨网请求 (e.g. 阿里云远程 daemon · 微信 bot 跨进程) 不动 ·
         原 check_auth 严格鉴权继续生效
    """
    if _loopback_trust_enabled() and _is_loopback(request) and _host_is_local(request):
        env_token = (os.environ.get("OPUS_API_TOKEN") or "").strip()
        if env_token:
            scope = request.scope
            existing = [
                (k, v) for k, v in scope.get("headers", [])
                if k.lower() != b"authorization"
            ]
            existing.append((b"authorization", f"Bearer {env_token}".encode("ascii")))
            scope["headers"] = existing
    return await call_next(request)


def check_rate_limit(request: "Request", authorization: Optional[str]) -> None:
    """卷四十六 III 补丁 5 · Y7 · 限流 (default disabled)。

    env OPUS_RATELIMIT_PER_MIN > 0 才生效·达限抛 429。
    limiter 自己挂了不能拖累 chat (吞异常)。
    """
    try:
        from workers.rate_limiter import check as _rl_check

        ip = (request.client.host if request and request.client else None) or "unknown"
        token = (authorization or "")[7:].strip() if authorization else None
        r = _rl_check(ip, token)
        if not r.get("ok"):
            raise HTTPException(
                status_code=429,
                detail=(
                    f"rate limit exceeded · retry in {r['retry_after_s']}s · "
                    f"raise OPUS_RATELIMIT_PER_MIN to allow more"
                ),
                headers={"Retry-After": str(int(r["retry_after_s"]) + 1)},
            )
    except HTTPException:
        raise
    except Exception:
        pass


async def safe_json_body(request: "Request") -> dict:
    """解析 POST body 为 JSON dict · 畸形/空/非对象 → 干净 400 (而非 500 + ASGI traceback)。

    前端 fetch 发的都是合法 JSON·这层只兜底畸形请求 (手工 curl 参数吃掉引号 / 探针 /
    坏客户端)·让端点少一堆 uvicorn traceback 噪音·给调用方明确的 400。始终返回 dict。
    """
    try:
        data = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON") from e
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")
    return data
