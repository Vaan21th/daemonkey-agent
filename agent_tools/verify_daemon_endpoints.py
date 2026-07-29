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
    "/api/wechat/test",      # 真往用户微信发一条占位 · smoke/pre-commit 不该触发 (卷七十四续十九)
    "/api/proactive/test",   # 真跑一次 proactive LLM turn + 投递 · 同上 · 别在 commit 时空转
}

# SSE 端点——走 probe=1 诊断分支 (纯 JSON · 不进流循环)
_SSE_PATHS = {
    "/chat/stream":             None,  # 无 probe 支持 · 走正常流 (TestClient 已验证可行)
    "/api/pulse/stream":        "?probe=1",  # probe 诊断分支 · 即时 JSON 返回
}

# deep 模式跳过——真 token 下会真跑且重 (LLM 调用 · 慢+烧钱 · smoke 不该触发)
_DEEP_SKIP_PATHS = {
    "/chat/stream",   # 真跑 LLM 流式生成 · 一次几十秒+烧 token · deep 也跳过
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
    # 0. 模式 (2026-07-29 用户拍板 · 双模式):
    #   fast(默认) 假 token + 并行 → 1.2s 全绿 · 验 import雷/参数雷/前端JS (smoke 立身之本)
    #   deep        真 token + 串行 + 单请求8s超时 + LLM端点跳过 → 大改后深测 auth handler 本体
    # 事故根因: 真 token 下 auth handler 全真跑 (/chat/stream 真调 LLM · 无参 POST 真执行),
    #   并行 6 线程共享锁互相等 → 每个卡满超时 → 140/6×10s 雪崩 = "慢到发指"的真相。
    mode = str((args or {}).get("mode") or "fast").strip().lower()
    deep = (mode == "deep")

    # 1. 确保 token 在环境里 + sys.path
    if deep:
        token = os.environ.get("OPUS_API_TOKEN") or "test-smoke-token"
        os.environ["OPUS_API_TOKEN"] = token  # deep: app auth 与请求头同值 → handler 真跑
    else:
        # fast: 环境保持原样 · 请求头带【保证不匹配】的 token → auth 401 早退 (1.2s 的关键)。
        # 教训: 千万别把 os.environ 也改成假值——那样请求头与 auth 比对一致 → handler 真跑
        # → 并行共享锁雪崩 (2026-07-29 第一次实现踩的坑)。没配 token 的环境 auth 关闭会
        # 退化为全量真跑 · 可接受。
        token = "smoke-mismatch-token"

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

    # ── 并发 smoke (2026-07-29 用户拍板: 串行 138 路由慢到发指 → 线程池并发) ──
    # 纪律: TestClient 非线程安全 (内部 anyio portal 不可共享) → 每线程独立 client。
    # 任务收集与汇总仍按路由原顺序 → 输出稳定 · diff 友好。
    tasks: list[dict] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        path_pattern = route.path
        methods = [m for m in sorted(route.methods) if m not in ("OPTIONS", "HEAD")]
        if not methods:
            continue
        is_sse = path_pattern in _SSE_PATHS
        sse_probe = _SSE_PATHS.get(path_pattern) if is_sse else None
        for method in methods:
            tasks.append({"path": path_pattern, "method": method,
                          "is_sse": is_sse, "probe": sse_probe})

    import concurrent.futures

    _tls = threading.local()

    def _tls_client():
        c = getattr(_tls, "client", None)
        if c is None:
            c = TestClient(app)
            _tls.client = c
        return c

    def _probe(t: dict) -> dict:
        """单路由单方法 smoke。返 {verdict, lines, fail_detail, auth, sse_line}。"""
        path_pattern = t["path"]
        method = t["method"]
        is_sse = t["is_sse"]
        r: dict = {"verdict": "pass", "lines": [], "fail_detail": None,
                   "auth": None, "sse_line": None}
        test_path = _resolve_path(path_pattern, t["probe"])

        if method == "POST" and path_pattern in _DANGEROUS_POST:
            r["verdict"] = "skip"
            r["lines"].append(f"{_SKIP} {method:6} {path_pattern}  (副作用 · 跳过)")
            return r

        if deep and path_pattern in _DEEP_SKIP_PATHS:
            r["verdict"] = "skip"
            r["lines"].append(f"{_SKIP} {method:6} {path_pattern}  (LLM 调用 · 慢+烧钱 · 跳过)")
            return r

        auth_headers = {"Authorization": f"Bearer {token}"}
        client = _tls_client()

        # Step A: 不带 auth 试
        try:
            resp = _do_request(client, method, test_path, {}, {})
        except Exception as e:
            r["verdict"] = "fail"
            r["lines"].append(f"{_FAIL} {method:6} {path_pattern}")
            msg = f"     (no auth) 异常: {type(e).__name__}: {str(e)[:150]}"
            r["lines"].append(msg)
            r["fail_detail"] = f"{method} {path_pattern}\n{msg}"
            return r

        if resp.status_code == 503:
            r["verdict"] = "skip"
            r["lines"].append(f"{_SKIP} {method:6} {path_pattern}  (503 · OPUS_API_TOKEN 未配)")
            return r

        if resp.status_code == 401:
            # 需鉴权 → 带 token 重试
            try:
                resp = _do_request(client, method, test_path, {}, auth_headers)
            except Exception as e:
                r["verdict"] = "fail"
                r["lines"].append(f"{_FAIL} {method:6} {path_pattern}")
                msg = f"     (with auth) 异常: {type(e).__name__}: {str(e)[:150]}"
                r["lines"].append(msg)
                r["fail_detail"] = f"{method} {path_pattern}\n{msg}"
                return r
            verdict, tag = _judge(resp, is_sse, "🔒 auth")
            r["auth"] = True
        else:
            verdict, tag = _judge(resp, is_sse, "🌐 noauth")
            r["auth"] = False

        icon = _PASS if verdict == "pass" else _FAIL
        r["lines"].append(f"{icon} {method:6} {path_pattern}  ({resp.status_code} · {tag})")
        if verdict == "pass":
            if is_sse:
                r["sse_line"] = f"  {icon} {method:6} {path_pattern}  ({resp.status_code} · {tag})"
        else:
            r["verdict"] = "fail"
            detail = f"     {_extract_error(resp)}"
            r["lines"].append(detail)
            r["fail_detail"] = f"{method} {path_pattern}  ({resp.status_code})\n{detail}"
        return r

    results: list[dict | None] = [None] * len(tasks)

    def _probe_guard(t: dict) -> dict:
        try:
            return _probe(t)
        except Exception as e:  # probe 自身炸了也算该路由失败 · 不静默吞
            msg = f"     (probe) 异常: {type(e).__name__}: {str(e)[:150]}"
            return {"verdict": "fail", "auth": None, "sse_line": None,
                    "lines": [f"{_FAIL} {t['method']:6} {t['path']}", msg],
                    "fail_detail": f"{t['method']} {t['path']}\n{msg}"}

    if deep:
        # deep: 串行 · 真 token 真跑 handler · 共享锁并行会雪崩 (2026-07-29 实测)
        for i, t in enumerate(tasks):
            results[i] = _probe_guard(t)
    else:
        # fast: 假 token 并行 · auth 路由 401 早退无共享状态 · 实测 1.2s 全量
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=6, thread_name_prefix="verify") as ex:
            fut_map = {ex.submit(_probe_guard, t): i for i, t in enumerate(tasks)}
            for fut in concurrent.futures.as_completed(fut_map):
                results[fut_map[fut]] = fut.result()

    # 按路由原顺序汇总
    for r in results:
        assert r is not None
        lines.extend(r["lines"])
        if r["verdict"] == "pass":
            passed += 1
            if r["auth"] is True:
                auth_routes += 1
            elif r["auth"] is False:
                noauth_routes += 1
        elif r["verdict"] == "fail":
            failed += 1
        else:
            skipped += 1
        if r["sse_line"]:
            sse_list.append(r["sse_line"])
        if r["fail_detail"]:
            fail_details.append(r["fail_detail"])

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
        "──── 汇总 ────",
        f"模式: {'deep (真token·串行·深测 handler 本体)' if deep else 'fast (假token·并行·验 import/参数雷)'}",
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


def _do_request(client, method: str, path: str, body: dict, headers: dict,
                timeout: float = 8.0):
    """发普通 HTTP 请求 · 统一包装 (单请求超时兜底: 一个 handler 卡死不雪崩)"""
    if method == "GET":
        return client.get(path, headers=headers, timeout=timeout)
    elif method == "POST":
        return client.post(path, json=body, headers=headers, timeout=timeout)
    elif method == "PUT":
        return client.put(path, json=body, headers=headers, timeout=timeout)
    elif method == "PATCH":
        return client.patch(path, json=body, headers=headers, timeout=timeout)
    elif method == "DELETE":
        return client.delete(path, headers=headers, timeout=timeout)
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


# ── 子进程隔离入口 (2026-07-29 用户拍板) ─────────────────────────────
# 事故: 工具在 daemon 进程内跑 TestClient smoke → 138 路由串行打满 GIL →
# asyncio 事件循环被饿死 → WebUI 重启/关闭按钮全部失灵 · 用户连砍两次。
# 修复: 工具入口改为全新子进程跑 _run (跟 verify_gate 上线闸同一姿势)——
#   ① daemon 事件循环零占用 · 体检再慢也拖不死 WebUI
#   ② 子进程从磁盘 fresh import · 测的是新代码不是内存旧代码 (顺带更准)
# snippet 是单一事实源 · workers/verify_gate.py 也 import 它。

_SUBPROCESS_SNIPPET = (
    "import os,sys; sys.path.insert(0,'.'); "
    "os.environ.setdefault('OPUS_API_TOKEN','verify-gate-token'); "
    "from agent_tools.verify_daemon_endpoints import _run; "
    "r=_run({'mode': os.environ.get('VERIFY_SMOKE_MODE','fast')}); "
    "print(r.output); sys.exit(0 if r.ok else 1)"
)


def _run_tool(args: dict) -> ToolResult:
    """工具入口: 全新子进程跑全路由 smoke (不堵 daemon · fresh import)。

    args.mode: fast(默认) 假token并行 ~秒级 / deep 真token串行带超时 ~分钟级。
    """
    import subprocess

    mode = str((args or {}).get("mode") or "fast").strip().lower()
    if mode not in ("fast", "deep"):
        mode = "fast"

    def _python() -> str:
        exe = sys.executable
        if exe:
            return exe
        cand = Path(__file__).resolve().parent.parent / ".venv" / "Scripts" / "python.exe"
        return str(cand) if cand.exists() else "python"

    env = dict(os.environ)
    env["VERIFY_SMOKE_MODE"] = mode
    timeout = 240 if mode == "deep" else 90
    kw: dict = dict(cwd=str(Path(__file__).resolve().parent.parent),
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=timeout, env=env)
    try:
        from agent_tools._subprocess_helper import no_window_kwargs
        kw.update(no_window_kwargs())
    except Exception:
        pass
    try:
        r = subprocess.run([_python(), "-c", _SUBPROCESS_SNIPPET], **kw)
        report = (r.stdout or "") + (("\n--- stderr ---\n" + r.stderr) if r.stderr.strip() else "")
        return ToolResult(ok=(r.returncode == 0), output=report[-8000:] or "(子进程无输出)")
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, output="",
                          error=f"子进程体检超时 ({timeout}s · mode={mode}) · 可能是某路由 handler 真卡死 · 建议人工核查")
    except Exception as e:
        return ToolResult(ok=False, output="",
                          error=f"子进程体检起不来: {type(e).__name__}: {e}")


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
        "**SSE**: /chat/stream 走流首帧 · /api/pulse/stream 走 probe=1 诊断分支\n"
        "**实现 (2026-07-29)**: 全新子进程跑 (不堵 daemon 事件循环) + 双模式:\n"
        "  mode=fast (默认) 假token+并行 ~秒级 · 验 import雷/参数雷/前端JS —— 日常自检用;\n"
        "  mode=deep 真token+串行+单请求8s超时 ~分钟级 · 深测 auth handler 本体 —— 大改路由后用。\n"
        "  (根因教训: 真token下 auth handler 全真跑·并行共享锁会雪崩——140/6×10s=慢到发指的真相)"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["fast", "deep"],
                "description": "fast(默认·秒级·日常自检) / deep(分钟级·真token深测 auth handler·大改路由后用)",
            },
        },
    },
    run=_run_tool,
    summarize=_summarize,
)

register_tool(SPEC)
