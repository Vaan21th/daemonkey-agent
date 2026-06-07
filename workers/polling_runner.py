"""workers/polling_runner.py
==============================

卷四十六 III 补丁 5 · Y8 · scripted app async polling 框架 · 2026-05-26

为什么需要这个
----------------
很多视频 / 图像 / 长文本 API 是**异步**的:

  POST /v1/video {prompt}        → {task_id: "abc-123"}    立刻返
  GET  /v1/query/abc-123          → {status: "Queueing"}   等
  GET  /v1/query/abc-123 (3s 后) → {status: "Processing"}  等
  GET  /v1/query/abc-123 (10s 后) → {status: "Success", video_url: "..."}

现状 http_executor 只支持单次请求 · OPUS 想接入 Hailuo / Runway / Replicate
这类 API · 必须在 LLM 里自己手动 polling — token 浪费 + 体验差。

Y8 给一个**结构化 polling 框架** · 在 exec_template 里加 `polling` 字段 ·
http_executor 检测到就委托给本模块跑完整 polling loop · LLM 看到一次完成的
结果。

设计取舍
----------
- **default off**: 没 polling 字段 / polling.enabled=False · 完全跟现状一致 ·
  现有 app 0 改 0 影响
- **不引入 asyncio**: 同步 polling (time.sleep) · 跟 http_executor 用的同款
  requests 库 · 复杂度低。 异步留下个 wish
- **不做线程并行**: 一个 polling 阻塞 _chat_impl 这个 turn · 加 cancel_event
  支持 (BRO 点 stop 时能中断)
- **succeeded / failed / continue 三态**: 用 status_path 取出来的值跟
  succeeded_values / failed_values 比 · 其他算 continue
- **超时**: max_attempts (默认 60) + timeout_sec (默认 300) · 取早到的

template schema (在 app json 的 exec_template 里加 `polling`):
    {
      "polling": {
        "enabled": true,
        "kind": "url_template",
        "url": "https://api.x.com/v1/query/${upstream:task_id}",
        "method": "GET",
        "headers": {"Authorization": "Bearer ${secret:...}"},
        "interval_sec": 3,
        "max_attempts": 60,
        "timeout_sec": 300,
        "status_path": "data.status",
        "succeeded_values": ["Success", "succeeded"],
        "failed_values": ["Failed", "failed"],
        "mapping": {
          "video_url": "data.result.video_url",
          "duration": "data.result.duration_sec"
        }
      }
    }
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

import requests

from workers.template_interpolator import (
    TemplateError, interpolate, interpolate_deep,
)


_log = logging.getLogger("opus.polling_runner")


def _jq_extract(obj: Any, path: str) -> Any:
    """跟 http_executor._jq_extract 同款 · dot-notation 提取 nested"""
    if not path or path == "":
        return obj
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def run_polling(
    polling_spec: dict,
    upstream_outputs: dict,
    app_id: str,
    context: dict,
    progress: Optional[Callable[[str, dict], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> dict:
    """跑一次 polling loop · 直到 succeeded / failed / timeout / canceled

    Args:
        polling_spec: exec_template.polling · 见 module docstring schema
        upstream_outputs: 主请求拿到的 task_id 等 outputs · 用于 url template
        app_id: 给 secret_redactor 用
        context: 主请求用的 context · 含 ui/upstream/app_id/ts/ts_ms · 这里
                 注入了 upstream_outputs 后传给 interpolate
        progress: SSE event 回调
        cancel_check: callable · 返 True 时立刻退出

    Returns:
        {
          "ok": bool,
          "final_status": str | None,
          "attempts": int,
          "elapsed_ms": int,
          "outputs": dict,  # polling.mapping 提取出的
          "error": str | None,
        }
    """
    if not polling_spec.get("enabled"):
        return {
            "ok": True, "final_status": None, "attempts": 0,
            "elapsed_ms": 0, "outputs": {}, "error": None,
        }

    interval_sec = max(0.5, float(polling_spec.get("interval_sec") or 3.0))
    max_attempts = max(1, int(polling_spec.get("max_attempts") or 60))
    timeout_sec = max(10.0, float(polling_spec.get("timeout_sec") or 300.0))

    url_t = polling_spec.get("url") or ""
    if not url_t:
        return {
            "ok": False, "final_status": None, "attempts": 0,
            "elapsed_ms": 0, "outputs": {},
            "error": "polling.url required",
        }

    method = (polling_spec.get("method") or "GET").upper()
    headers_t = polling_spec.get("headers") or {}
    request_timeout = max(5.0, float(polling_spec.get("request_timeout_sec") or 10.0))

    status_path = polling_spec.get("status_path") or "status"
    succeeded = set(polling_spec.get("succeeded_values") or [])
    failed = set(polling_spec.get("failed_values") or [])
    mapping = polling_spec.get("mapping") or {}

    # 合并 upstream → context · polling URL 引用主请求输出用 ${upstream:__self__:task_id}
    # __self__ 是个伪 node_id · 复用 workflow_engine 已有的 ${upstream:<node>:<port>} 格式
    # 单 node scripted app 的 polling 也能拿到主请求 outputs · 0 改 interpolator
    ctx = dict(context or {})
    existing_upstream = dict(ctx.get("upstream") or {})
    existing_upstream["__self__"] = upstream_outputs or {}
    ctx["upstream"] = existing_upstream

    try:
        url = interpolate(url_t, ctx)
        headers = interpolate_deep(headers_t, ctx)
    except TemplateError as e:
        return {
            "ok": False, "final_status": None, "attempts": 0,
            "elapsed_ms": 0, "outputs": {},
            "error": f"polling url/headers interpolate failed: {e}",
        }

    if progress:
        try:
            progress("polling_start", {
                "url": url,
                "interval_sec": interval_sec,
                "max_attempts": max_attempts,
                "timeout_sec": timeout_sec,
                "status_path": status_path,
            })
        except Exception:
            pass

    start = time.time()
    attempts = 0
    final_status: Optional[str] = None
    last_data: Any = None

    while attempts < max_attempts:
        if cancel_check and cancel_check():
            elapsed_ms = int((time.time() - start) * 1000)
            return {
                "ok": False, "final_status": "canceled", "attempts": attempts,
                "elapsed_ms": elapsed_ms, "outputs": {},
                "error": "polling canceled by user",
            }

        elapsed = time.time() - start
        if elapsed >= timeout_sec:
            elapsed_ms = int(elapsed * 1000)
            return {
                "ok": False, "final_status": "timeout", "attempts": attempts,
                "elapsed_ms": elapsed_ms, "outputs": {},
                "error": f"polling timeout ({timeout_sec}s)",
            }

        attempts += 1
        try:
            resp = requests.request(
                method=method, url=url, headers=headers, timeout=request_timeout,
            )
        except requests.RequestException as e:
            # 网络抖动 · 继续 polling (下次再试 · 不算 fatal)
            if progress:
                try:
                    progress("polling_attempt", {
                        "attempt": attempts, "ok": False,
                        "error": f"network: {type(e).__name__}",
                    })
                except Exception:
                    pass
            time.sleep(interval_sec)
            continue

        if not resp.ok:
            if progress:
                try:
                    progress("polling_attempt", {
                        "attempt": attempts, "ok": False,
                        "status": resp.status_code,
                    })
                except Exception:
                    pass
            # 4xx / 5xx · 继续轮询 (上游可能短暂错误) · 但 401/403 直接 fail
            if resp.status_code in (401, 403, 404):
                elapsed_ms = int((time.time() - start) * 1000)
                return {
                    "ok": False, "final_status": f"http_{resp.status_code}",
                    "attempts": attempts, "elapsed_ms": elapsed_ms,
                    "outputs": {},
                    "error": f"polling auth/notfound failed: http {resp.status_code}",
                }
            time.sleep(interval_sec)
            continue

        try:
            data = resp.json()
        except Exception as e:
            elapsed_ms = int((time.time() - start) * 1000)
            return {
                "ok": False, "final_status": "json_parse_error",
                "attempts": attempts, "elapsed_ms": elapsed_ms, "outputs": {},
                "error": f"polling json parse: {e}",
            }

        last_data = data
        status_value = _jq_extract(data, status_path)
        status_str = str(status_value) if status_value is not None else ""

        if progress:
            try:
                progress("polling_attempt", {
                    "attempt": attempts,
                    "ok": True,
                    "status_value": status_str,
                })
            except Exception:
                pass

        if status_str in succeeded:
            final_status = status_str
            break
        if status_str in failed:
            elapsed_ms = int((time.time() - start) * 1000)
            err_msg = _jq_extract(data, polling_spec.get("error_message_path") or "message")
            return {
                "ok": False, "final_status": status_str,
                "attempts": attempts, "elapsed_ms": elapsed_ms,
                "outputs": {},
                "error": f"polling reported failure: {status_str}" +
                         (f" · {err_msg}" if err_msg else ""),
            }

        time.sleep(interval_sec)

    elapsed_ms = int((time.time() - start) * 1000)

    if final_status is None:
        return {
            "ok": False, "final_status": "max_attempts",
            "attempts": attempts, "elapsed_ms": elapsed_ms, "outputs": {},
            "error": f"polling exhausted max_attempts={max_attempts}",
        }

    # succeeded · 用 mapping 提取
    outputs: dict = {}
    for out_name, src_path in mapping.items():
        outputs[out_name] = _jq_extract(last_data, src_path)
    outputs["_polling_raw"] = last_data
    outputs["_polling_attempts"] = attempts
    outputs["_polling_elapsed_ms"] = elapsed_ms

    if progress:
        try:
            progress("polling_done", {
                "attempts": attempts,
                "elapsed_ms": elapsed_ms,
                "final_status": final_status,
                "outputs_keys": [k for k in outputs.keys() if not k.startswith("_")],
            })
        except Exception:
            pass

    return {
        "ok": True,
        "final_status": final_status,
        "attempts": attempts,
        "elapsed_ms": elapsed_ms,
        "outputs": outputs,
        "error": None,
    }


__all__ = ["run_polling"]
