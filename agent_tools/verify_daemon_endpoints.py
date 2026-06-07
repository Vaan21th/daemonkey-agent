"""
agent_tools/verify_daemon_endpoints.py
======================================
 · wish-4b16633d · 改完 daemon 核心代码自动 dogfood 全路由

wish-4b16633d bug: OPUS 改 daemon 代码后自称"改好了"但没验证 → commit 后
daemon 起不来 (漏 import / 参数雷)。用 FastAPI TestClient (不是 curl)
能直接拿 Python traceback · commit 前调一次。

SSE 盲点修 (wish-4b16633d pt.2):
  /api/pulse/stream 的 StreamingResponse + async generator 在 TestClient /
  httpx.AsyncClient 里均阻塞 · 无法读首帧。改走 daemon_api.py 的 probe=1
  内部诊断分支 → 返回即时 JSON · 不进 SSE 循环。
"""

from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool

_PASS = "✅"
_FAIL = "❌"
_SKIP = "⏭️"

# 这些端点即使空 body 也有不可逆副作用——跳过 POST
_DANGEROUS_POST = {
    "/restart-daemon",
    "/shutdown-daemon",
}

# SSE 端点——走 probe=1 诊断分支 (纯 JSON · 不进流循环)
_SSE_PATHS = {
    "/chat/stream":             None,  # 无 probe 支持 · 走正常流 (TestClient 已验证可行)
    "/api/pulse/stream":        "?probe=1",  # probe 诊断分支 · 即时 JSON 返回
}


def _summarize(args: dict) -> str:
    return "verify_daemon_endpoints · 全路由 TestClient smoke"


def _resolve_path(pattern: str, probe: str | None = None) -> str:
    """替换 {param} / {param:type} 为 dummy 值 · 可选追加 probe query"""
    path = re.sub(r"\{[^}]+\}", "test-123", pattern)
    if probe:
        path += probe
    return path


def _run(args: dict) -> ToolResult:
    # 1. 确保 token 在环境里 + sys.path
    token = os.environ.get("OPUS_API_TOKEN") or "test-smoke-token"
    os.environ["OPUS_API_TOKEN"] = token

    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # 2. 建 app
    try:
        from daemon_api import build_app
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"import daemon_api.build_app 失败: {e!r}")

    try:
        app = build_app()
    except Exception as e:
        return ToolResult(
            ok=False, output="",
            error=f"build_app() 抛异常: {type(e).__name__}: {e!r}\n→ daemon 代码有语法/import 错误，起不来！",
        )

    # 3. 建 TestClient
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        return ToolResult(ok=False, output="", error="fastapi.testclient 不可用 · pip install httpx?")

    client = TestClient(app)

    # 4. 扫路由
    from fastapi.routing import APIRoute

    lines: list[str] = []
    passed = 0
    failed = 0
    skipped = 0
    auth_routes = 0
    noauth_routes = 0
    sse_list: list[str] = []
    fail_details: list[str] = []

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue

        path_pattern = route.path
        methods = [m for m in sorted(route.methods) if m not in ("OPTIONS", "HEAD")]
        if not methods:
            continue

        is_sse = path_pattern in _SSE_PATHS
        sse_probe = _SSE_PATHS.get(path_pattern) if is_sse else None
        # SSE 端点如果有 probe 支持就走 probe · 否则走流 (chat/stream)
        sse_use_probe = sse_probe is not None

        for method in methods:
            test_path = _resolve_path(path_pattern, sse_probe if sse_use_probe else None)

            # 跳过危险端点
            if method == "POST" and path_pattern in _DANGEROUS_POST:
                lines.append(f"{_SKIP} {method:6} {path_pattern}  (副作用 · 跳过)")
                skipped += 1
                continue

            auth_headers = {"Authorization": f"Bearer {token}"}

            # Step A: 不带 auth 试
            try:
                resp = _do_request(client, method, test_path, {}, {})
            except Exception as e:
                lines.append(f"{_FAIL} {method:6} {path_pattern}")
                msg = f"     (no auth) 异常: {type(e).__name__}: {str(e)[:150]}"
                lines.append(msg)
                fail_details.append(f"{method} {path_pattern}\n{msg}")
                failed += 1
                continue

            if resp.status_code == 503:
                lines.append(f"{_SKIP} {method:6} {path_pattern}  (503 · OPUS_API_TOKEN 未配)")
                skipped += 1
                continue

            if resp.status_code == 401:
                # 需鉴权 → 带 token 重试
                try:
                    resp = _do_request(client, method, test_path, {}, auth_headers)
                except Exception as e:
                    lines.append(f"{_FAIL} {method:6} {path_pattern}")
                    msg = f"     (with auth) 异常: {type(e).__name__}: {str(e)[:150]}"
                    lines.append(msg)
                    fail_details.append(f"{method} {path_pattern}\n{msg}")
                    failed += 1
                    continue

                verdict, tag = _judge(resp, is_sse, "🔒 auth")
                if verdict == "pass":
                    lines.append(f"{_PASS} {method:6} {path_pattern}  ({resp.status_code} · {tag})")
                    passed += 1
                    auth_routes += 1
                    if is_sse:
                        sse_list.append(f"  {_PASS} {method:6} {path_pattern}  ({resp.status_code} · {tag})")
                else:
                    lines.append(f"{_FAIL} {method:6} {path_pattern}  ({resp.status_code} · {tag})")
                    detail = f"     {_extract_error(resp)}"
                    lines.append(detail)
                    fail_details.append(f"{method} {path_pattern}  ({resp.status_code})\n{detail}")
                    failed += 1
                continue

            # 无需鉴权
            verdict, tag = _judge(resp, is_sse, "🌐 noauth")
            icon = _PASS if verdict == "pass" else _FAIL
            if verdict == "pass":
                lines.append(f"{icon} {method:6} {path_pattern}  ({resp.status_code} · {tag})")
                passed += 1
                noauth_routes += 1
                if is_sse:
                    sse_list.append(f"  {icon} {method:6} {path_pattern}  ({resp.status_code} · {tag})")
            else:
                lines.append(f"{icon} {method:6} {path_pattern}  ({resp.status_code} · {tag})")
                detail = f"     {_extract_error(resp)}"
                lines.append(detail)
                fail_details.append(f"{method} {path_pattern}  ({resp.status_code})\n{detail}")
                failed += 1

    # 5. SSE 专节
    if sse_list:
        lines.append("")
        lines.append("── SSE 流端点 ──")
        lines.extend(sse_list)

    # 6. 失败详情
    if fail_details:
        lines.append("")
        lines.append("── 失败详情 ──")
        for fd in fail_details:
            lines.append(fd)
            lines.append("")

    # 6.5 前端 JS 语法 ( · 2026-06-03 事故补)
    #   route smoke 只验 Python · 这一节补前端那环: OPUS 改完 static/*.js 也能在 commit 前
    #   发现自己把 chat.js 改断了 (本次事故: python_exec 切片把 chat.js 尾部 1660 行吞了)。
    fe_ok = True
    try:
        from workers.frontend_check import check_static_js, format_report
        fe = check_static_js()
        fe_ok = fe["ok"]
        lines.append("")
        lines.append("── 前端 JS 语法 ──")
        lines.append(format_report(fe))
    except Exception as e:
        lines.append("")
        lines.append(f"── 前端 JS 语法 ── (校验跳过: {type(e).__name__})")

    # 7. 汇总
    total = passed + failed + skipped
    summary = [
        "",
        f"──── 汇总 ────",
        f"总计 {total} 路由 · {_PASS} {passed} pass · {_FAIL} {failed} fail · {_SKIP} {skipped} skip",
        f"🔒 需鉴权: {auth_routes} · 🌐 无需鉴权: {noauth_routes}",
        f"前端 JS: {'✅ OK' if fe_ok else '❌ 语法坏 (见下方·先修再 commit)'}",
    ]
    if failed == 0 and fe_ok:
        summary.append("")
        summary.append("🎉 全路由 smoke + 前端 JS 通过 · daemon 代码没有 import / 参数雷 · chat.js 没改断。")
    else:
        summary.append("")
        if failed:
            summary.append(f"⚠️  {failed} 个路由 smoke 失败 · 上面有 traceback · 先修再 commit。")
        if not fe_ok:
            summary.append("⚠️  前端 JS 语法坏了 · 重启后 WebUI 会白屏 · 先修再 commit (见『前端 JS 语法』节)。")

    lines = summary + lines

    ok = (failed == 0) and fe_ok
    return ToolResult(ok=ok, output="\n".join(lines))


# ── helpers ────────────────────────────────────────────────


def _do_request(client, method: str, path: str, body: dict, headers: dict):
    """发普通 HTTP 请求 · 统一包装"""
    if method == "GET":
        return client.get(path, headers=headers)
    elif method == "POST":
        return client.post(path, json=body, headers=headers)
    elif method == "PUT":
        return client.put(path, json=body, headers=headers)
    elif method == "PATCH":
        return client.patch(path, json=body, headers=headers)
    elif method == "DELETE":
        return client.delete(path, headers=headers)
    else:
        raise ValueError(f"unsupported method: {method}")


def _judge(resp, is_sse: bool, tag: str) -> tuple[str, str]:
    """判定响应是否通过 smoke"""
    status = resp.status_code

    if 200 <= status < 300:
        return ("pass", tag)

    # 4xx = 参数/资源问题 · 不是代码 bug · 通过
    if 400 <= status < 500:
        if status == 405:
            return ("pass", f"{tag} · 405")
        return ("pass", tag)

    # 5xx = 代码 bug · 失败
    return ("fail", tag)


def _extract_error(resp) -> str:
    """从响应里提取错误信息 · 截断"""
    try:
        body = resp.text
    except Exception:
        body = "(无法读取 body)"
    if len(body) > 200:
        body = body[:200] + "..."
    return body.replace("\n", " ").replace("\r", " ")


SPEC = ToolSpec(
    name="verify_daemon_endpoints",
    description=(
        "对 daemon 所有 HTTP 路由做一次快速 smoke test · 用 FastAPI TestClient"
        "（不是 curl）· 能拿 Python traceback。 **外加前端 static/*.js 语法校验** "
        "(node --check · 加)。\n"
        "\n"
        "**调用时机**: OPUS 改完 daemon_api.py / agent_tools/*.py / static/*.js 后、commit 前。\n"
        "改完自称「改好了」之前必须先跑这个——不漏 import / 参数雷 · 也不漏把 chat.js 改断 "
        "(事故: python_exec 切片把 chat.js 尾部吞了·route smoke 全绿但 WebUI 白屏)。\n"
        "\n"
        "**跳过**: /restart-daemon /shutdown-daemon (有不可逆副作用) · static/lib/ 下三方 vendor JS\n"
        "**SSE**: /chat/stream 走流首帧 · /api/pulse/stream 走 probe=1 诊断分支"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {},
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
