"""workers/net_client.py
==========================

卷四十六 III 补丁 5 · R2 · 带 retry / backoff 的 HTTP wrapper · 2026-05-26

为什么需要这个
----------------
工程里 4 处直接调用 httpx / requests · 都是单次请求 · 网络抖动 / 上游 503 时
直接 raise · 调用方各自 try/except (有的甚至没 try)。 远程服务器上跑 daemon
时 (Week 1+ 目标) · 这种『硬抖动』会让 radar / fact_check / scripted app
间歇性失败 · 没法稳定运行。

这一模块给一个**纯 opt-in** 的 `safe_request` wrapper:
  - **default retries=0** · 行为完全跟 httpx 原样 · 不破坏现有调用
  - caller 显式 `retries=3` 才启用 · 真正想稳的接口才用 (radar / fact_check)
  - exponential backoff · jitter · 上限 · 标准做法
  - retry_on_status 默认 (502/503/504) · 不 retry 401/403/404 (无意义)
  - retry_on_exc 默认 (ConnectError/TimeoutException/ReadError) · 不 retry SSL/HTTP error

设计取舍
----------
- **基于 httpx**: 工程 3/4 处都用 httpx · 统一在这一层
- **不替换 requests**: http_executor 用 requests · 暂不动 · 等后续 wish
- **不做 circuit breaker**: 单进程内 retry 够了 · 真要 circuit 要全局协调状态 ·
  MVP 不做 (留 wish-future)
- **不做 token bucket**: 限流是 server 责任 · client retry 加 jitter 已经够温和
- **背景 fact_check 一律启用**: caller-side 单独 opt-in · 现有调用都不变

用法 (caller migrate 一行):
    # 旧
    r = httpx.get(url, timeout=10)
    # 新 (要 retry 才迁)
    from workers.net_client import safe_request
    r = safe_request("GET", url, retries=3, timeout=10)
"""
from __future__ import annotations

import logging
import random
import time
from typing import Optional, Sequence, Type, Union

try:
    import httpx  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - httpx 是工程已有依赖 · 这里只防爆
    httpx = None  # type: ignore[assignment]


_log = logging.getLogger("opus.net_client")


_DEFAULT_RETRY_STATUS = (502, 503, 504)


def _default_retry_exc() -> tuple:
    """httpx 可能没装时返空 tuple · 调用 safe_request 时会立刻 raise"""
    if httpx is None:
        return ()
    return (
        httpx.ConnectError,
        httpx.TimeoutException,
        httpx.ReadError,
        httpx.RemoteProtocolError,
        httpx.PoolTimeout,
    )


def _calc_backoff(attempt: int, initial: float, max_wait: float,
                  jitter: float = 0.3) -> float:
    """指数 backoff + jitter

    attempt=0 (首次失败后等待) → initial
    attempt=1 → initial * 2
    attempt=2 → initial * 4
    ...
    封顶 max_wait · jitter ± 30% 随机
    """
    base = initial * (2 ** attempt)
    base = min(base, max_wait)
    rand = base * jitter * (random.random() * 2 - 1)  # [-jitter, +jitter)
    return max(0.05, base + rand)


def safe_request(
    method: str,
    url: str,
    *,
    retries: int = 0,
    backoff_initial: float = 1.0,
    backoff_max: float = 30.0,
    timeout: float = 10.0,
    retry_on_status: Sequence[int] = _DEFAULT_RETRY_STATUS,
    retry_on_exc: Optional[Sequence[Type[Exception]]] = None,
    client: Optional["httpx.Client"] = None,
    **kwargs,
) -> "httpx.Response":
    """带 retry / backoff 的 HTTP 请求

    Args:
        method: HTTP method · 'GET' / 'POST' / 'PUT' / 'DELETE' / 'PATCH' / ...
        url: 目标 URL
        retries: 重试次数 · default=0 (完全向后兼容 · 同 httpx 原样)
                 retries=3 → 共 4 次请求 (1 次主 + 3 次 retry)
        backoff_initial: 首次 retry 前等待秒数 · default=1.0
        backoff_max: 单次 retry 最大等待秒数 · default=30.0
        timeout: 单次请求 timeout 秒 · default=10.0
        retry_on_status: 哪些 status code 触发 retry · default=(502, 503, 504)
        retry_on_exc: 哪些 exception 触发 retry · default 见 _default_retry_exc
        client: 可选 httpx.Client · 复用连接池 · None 则每次新 client
        **kwargs: 透传给 httpx (headers/json/data/params/files/...)

    Returns:
        httpx.Response

    Raises:
        最后一次失败的 exception · 或 retries=0 时的原始 exception
        ImportError: httpx 没装时

    Examples:
        # 完全向后兼容 (retries=0)
        r = safe_request("GET", "https://example.com")
        # 启用 retry
        r = safe_request("GET", "https://example.com", retries=3, timeout=5)
        # 复用 client (连接池)
        with httpx.Client(timeout=10) as c:
            r1 = safe_request("GET", url1, client=c, retries=2)
            r2 = safe_request("POST", url2, client=c, retries=2, json={...})
    """
    if httpx is None:
        raise ImportError("httpx 未安装 · pip install httpx")

    if retry_on_exc is None:
        retry_on_exc = _default_retry_exc()
    retry_on_exc = tuple(retry_on_exc)

    method = method.upper()
    total_attempts = retries + 1
    last_exc: Optional[Exception] = None
    last_resp: Optional["httpx.Response"] = None

    for attempt in range(total_attempts):
        try:
            if client is not None:
                resp = client.request(method, url, timeout=timeout, **kwargs)
            else:
                resp = httpx.request(method, url, timeout=timeout, **kwargs)
            last_resp = resp

            if resp.status_code in retry_on_status and attempt < total_attempts - 1:
                wait = _calc_backoff(attempt, backoff_initial, backoff_max)
                _log.info(
                    "safe_request retry · attempt=%d/%d · status=%d · wait=%.2fs · url=%s",
                    attempt + 1, total_attempts, resp.status_code, wait, url,
                )
                time.sleep(wait)
                continue
            return resp

        except retry_on_exc as e:
            last_exc = e
            if attempt < total_attempts - 1:
                wait = _calc_backoff(attempt, backoff_initial, backoff_max)
                _log.info(
                    "safe_request retry · attempt=%d/%d · exc=%s · wait=%.2fs · url=%s",
                    attempt + 1, total_attempts, type(e).__name__, wait, url,
                )
                time.sleep(wait)
                continue
            raise

    if last_resp is not None:
        return last_resp
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("safe_request internal error: no response and no exception")


__all__ = ["safe_request"]
