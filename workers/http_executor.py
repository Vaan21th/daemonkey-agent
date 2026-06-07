"""workers/http_executor.py
============================

卷四十六续 13 · wish-165ea1f6 phase C · 直接 HTTP 执行引擎 · 0 LLM

跑一个 scripted app = 拿 exec_template + form 输入 + secrets · 拼 HTTP 请求 · 发出去 ·
拿 response 按规则提字段 · 落盘文件 · 返回 outputs dict。

跟 agentic (app_runner.run_app) 的差别:
  - agentic: form → 拼自然语言 prompt → LLM session → tool_loop → outputs
  - scripted: form → 模板插值 → 一次 requests · → outputs
  - scripted 一刀过 · 没 LLM · 快 (秒级 vs 分钟级) · 省 ($0 vs $0.01-0.1 per call) · 稳

设计哲学:
  - **不允许在 exec_template 里写任何代码** (没 lambda · 没 eval · 没条件表达式)
  - **不允许跑任意 shell / python** (那是 agentic 的事 · 走 tool_loop)
  - **只支持 HTTP** · 其他协议 (gRPC / WebSocket / FTP) 短期不做

输入输出:
    result = run_scripted_app(
        app=<dict>,         # workshop_assets.load_app 出来的 · 含 exec_template
        inputs={'prompt':...},
        runtime=<RUNTIME>,  # 主要拿 app_id 上下文 · scripted 不需要 LLM client
        progress=<hook>,    # SSE 推送
    )
    # result = {
    #     'ok': bool,
    #     'outputs': {'image_url': 'data/workshop/outputs/.../x.png', ...},
    #     'http': {'status': 200, 'elapsed_ms': 1234, 'request_id': '...'}
    #     'error': str | None,
    # }
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

from workers.template_interpolator import (
    interpolate,
    interpolate_deep,
    evaluate_when,
    TemplateError,
)

# 删了 _load_secrets · secret 全交给 template_interpolator · 走 workers.app_secrets
# (跟 shell_exec 同一存储 · 铁律 7 · 卷四十四 K stage 2c++ · 2026-05-26 第二十一根毛)


ROOT = Path(__file__).resolve().parents[1]


def _pick_route(routes: list[dict], ui: dict) -> Optional[dict]:
    """按顺序找第一个 when 命中的 route · 全没命中则返回 when='default' 的兜底"""
    default_route = None
    for r in routes:
        if r.get("when") == "default":
            default_route = r
            continue
        if evaluate_when(r.get("when") or "", ui):
            return r
    return default_route


def _jq_extract(obj: Any, path: str) -> Any:
    """简化版 jq · 支持 'a.b.c' / 'a[0].b' · 不存在返回 None"""
    if not path:
        return obj
    cur = obj
    parts = []
    i = 0
    while i < len(path):
        if path[i] == ".":
            i += 1
            continue
        if path[i] == "[":
            j = path.index("]", i)
            parts.append(int(path[i + 1:j]))
            i = j + 1
        else:
            j = i
            while j < len(path) and path[j] not in ".[":
                j += 1
            parts.append(path[i:j])
            i = j
    for p in parts:
        if cur is None:
            return None
        try:
            if isinstance(p, int):
                cur = cur[p]
            else:
                cur = cur.get(p) if isinstance(cur, dict) else None
        except (KeyError, IndexError, TypeError):
            return None
    return cur


def _save_binary(content: bytes, save_dir: str, filename: str) -> tuple[str, str]:
    """落盘 binary · 返回 (磁盘相对路径, daemon URL)
    
    磁盘相对路径: 'data/workshop/outputs/<aid>/<file>' (相对工程根 · 给日志 / debug 用)
    daemon URL:  '/workshop/outputs/<aid>/<file>' (前端 <img> src 用 · 走 daemon_api 静态路由)
    
    保存位置必须在 data/workshop/outputs/ 下 · 不然 daemon 静态路由访问不到 (会 404 / 跨目录 reject)
    """
    safe_filename = filename.replace("..", "_").replace("/", "_").replace("\\", "_")
    if not safe_filename:
        safe_filename = f"output-{int(time.time())}"
    
    dir_path = ROOT / save_dir
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / safe_filename
    file_path.write_bytes(content)

    rel = str(file_path.relative_to(ROOT)).replace("\\", "/")
    OUTPUTS_PREFIX = "data/workshop/outputs/"
    if rel.startswith(OUTPUTS_PREFIX):
        url = "/workshop/outputs/" + rel[len(OUTPUTS_PREFIX):]
    else:
        url = "/" + rel
    return rel, url


def run_scripted_app(
    *,
    app: dict,
    inputs: dict,
    runtime: Any = None,
    progress: Optional[Callable[[str, dict], None]] = None,
    upstream_outputs: Optional[dict] = None,
) -> dict:
    """跑一个 scripted app · 返回 outputs
    
    Args:
        app: app json (含 exec_template)
        inputs: form 字段值
        runtime: 兼容签名 · scripted 不用 LLM
        progress: SSE hook · 推 http_request / http_response 事件
        upstream_outputs: 工作流上游 node outputs (workflow_engine 注入)

    Returns:
        result dict (见模块 docstring)
    """
    try:
        import requests
    except ImportError:
        return {"ok": False, "outputs": {}, "http": {}, "error": "requests not installed"}

    if not isinstance(app, dict) or not app.get("id"):
        return {"ok": False, "outputs": {}, "http": {}, "error": "app spec invalid"}

    template = app.get("exec_template")
    if not isinstance(template, dict):
        return {"ok": False, "outputs": {}, "http": {}, "error": "app.exec_template missing"}

    aid = app["id"]
    routes = template.get("routes") or []
    if not routes:
        return {"ok": False, "outputs": {}, "http": {}, "error": "exec_template.routes empty"}

    # secret 不预加载 · template_interpolator 在 lazy 解析时直接调
    # workers.app_secrets.get_secret(app_id, name) · 跟铁律 7 / shell_exec 共用同一存储
    context = {
        "ui": inputs or {},
        "upstream": upstream_outputs or {},
        "app_id": aid,
        "ts": time.strftime("%Y%m%d_%H%M%S"),
        "ts_ms": str(int(time.time() * 1000)),
    }

    route = _pick_route(routes, context["ui"])
    if route is None:
        return {"ok": False, "outputs": {}, "http": {}, "error": "no matching route + no default"}

    try:
        method = route["method"]
        url = interpolate(route["url"], context)
        headers = interpolate_deep(route.get("headers") or {}, context)
        body_kind = route.get("body_kind") or "json"
        body_raw = route.get("body")
        timeout_sec = int(route.get("timeout_sec") or 60)
    except TemplateError as e:
        return {"ok": False, "outputs": {}, "http": {},
                "error": f"template interpolation failed: {e}"}

    if progress:
        try:
            progress("http_request", {
                "method": method, "url": url,
                "body_kind": body_kind,
                "headers_keys": list(headers.keys()),
                "when": route.get("when"),
            })
        except Exception:
            pass

    req_kwargs: dict[str, Any] = {
        "method": method,
        "url": url,
        "headers": headers,
        "timeout": timeout_sec,
    }

    try:
        if body_raw is not None:
            if body_kind == "json":
                req_kwargs["json"] = interpolate_deep(body_raw, context)
            elif body_kind == "form_urlencoded":
                req_kwargs["data"] = interpolate_deep(body_raw, context)
            elif body_kind == "multipart_form":
                interp_body = interpolate_deep(body_raw, context)
                files = {}
                data = {}
                for k, v in (interp_body or {}).items():
                    if isinstance(v, str) and v.startswith("@file:"):
                        local_path = v[len("@file:"):]
                        p = ROOT / local_path if not Path(local_path).is_absolute() else Path(local_path)
                        if not p.exists():
                            return {"ok": False, "outputs": {}, "http": {},
                                    "error": f"multipart file not found: {local_path}"}
                        files[k] = (p.name, open(p, "rb"))
                    else:
                        data[k] = str(v) if not isinstance(v, str) else v
                if files:
                    req_kwargs["files"] = files
                if data:
                    req_kwargs["data"] = data
            elif body_kind == "raw":
                req_kwargs["data"] = interpolate(body_raw if isinstance(body_raw, str) else json.dumps(body_raw), context)
    except TemplateError as e:
        return {"ok": False, "outputs": {}, "http": {},
                "error": f"body interpolation failed: {e}"}

    start = time.time()
    try:
        resp = requests.request(**req_kwargs)
    except requests.RequestException as e:
        elapsed_ms = int((time.time() - start) * 1000)
        if progress:
            try:
                progress("http_response", {"status": -1, "elapsed_ms": elapsed_ms, "error": str(e)})
            except Exception:
                pass
        return {"ok": False, "outputs": {}, "http": {"elapsed_ms": elapsed_ms},
                "error": f"http request failed: {e}"}

    elapsed_ms = int((time.time() - start) * 1000)
    if progress:
        try:
            progress("http_response", {
                "status": resp.status_code,
                "elapsed_ms": elapsed_ms,
                "content_length": len(resp.content),
                "content_type": resp.headers.get("Content-Type", ""),
            })
        except Exception:
            pass

    if not resp.ok:
        preview = (resp.text or "")[:500]
        # 卷四十六 III 补丁 5 · Y3 · error preview 可能 echo secret · redact 后再返
        try:
            from workers.secret_redactor import build_redactor
            preview = build_redactor(aid)(preview)
        except Exception:
            pass
        return {
            "ok": False,
            "outputs": {},
            "http": {"status": resp.status_code, "elapsed_ms": elapsed_ms},
            "error": f"http {resp.status_code}: {preview}",
        }

    response_spec = template.get("response") or {}
    resp_kind = response_spec.get("kind") or "json"
    extract_path = response_spec.get("extract") or ""
    save = response_spec.get("save")
    mapping = response_spec.get("mapping") or {}

    outputs: dict = {}
    try:
        if resp_kind == "json":
            data = resp.json()
            for out_name, src_path in mapping.items():
                outputs[out_name] = _jq_extract(data, src_path)
            outputs["_raw"] = data
        elif resp_kind == "text":
            text = resp.text
            for out_name, src_path in mapping.items():
                if src_path in ("__text__", ""):
                    outputs[out_name] = text
                else:
                    outputs[out_name] = None
            outputs["_text"] = text
        elif resp_kind == "binary_save":
            if not save:
                return {"ok": False, "outputs": {}, "http": {"status": resp.status_code, "elapsed_ms": elapsed_ms},
                        "error": "response.save required for binary_save"}
            dir_t = interpolate(save["dir"], context)
            file_t = interpolate(save["filename"], context)
            saved_rel, saved_url = _save_binary(resp.content, dir_t, file_t)
            outputs["__saved_path__"] = saved_rel
            outputs["__saved_url__"] = saved_url
            for out_name, src_path in mapping.items():
                if src_path == "__saved_path__":
                    outputs[out_name] = saved_url
                else:
                    outputs[out_name] = None
        elif resp_kind == "b64_save":
            if not save:
                return {"ok": False, "outputs": {}, "http": {"status": resp.status_code, "elapsed_ms": elapsed_ms},
                        "error": "response.save required for b64_save"}
            data = resp.json()
            b64_str = _jq_extract(data, extract_path)
            if not isinstance(b64_str, str):
                return {"ok": False, "outputs": {}, "http": {"status": resp.status_code, "elapsed_ms": elapsed_ms},
                        "error": f"b64_save extract '{extract_path}' got {type(b64_str).__name__}, not str"}
            try:
                binary = base64.b64decode(b64_str)
            except Exception as e:
                return {"ok": False, "outputs": {}, "http": {"status": resp.status_code, "elapsed_ms": elapsed_ms},
                        "error": f"base64 decode failed: {e}"}
            dir_t = interpolate(save["dir"], context)
            file_t = interpolate(save["filename"], context)
            saved_rel, saved_url = _save_binary(binary, dir_t, file_t)
            outputs["__saved_path__"] = saved_rel
            outputs["__saved_url__"] = saved_url
            for out_name, src_path in mapping.items():
                if src_path == "__saved_path__":
                    outputs[out_name] = saved_url
                else:
                    outputs[out_name] = _jq_extract(data, src_path)
            outputs["_raw"] = {k: v for k, v in (data or {}).items() if k != extract_path.split(".")[0]}
    except json.JSONDecodeError as e:
        return {"ok": False, "outputs": {}, "http": {"status": resp.status_code, "elapsed_ms": elapsed_ms},
                "error": f"response json parse failed: {e}"}

    # 卷四十六 III 补丁 5 · Y8 · scripted app async polling
    # 主请求拿到 task_id 后 · 如果 exec_template.polling.enabled · 走 polling loop
    # 直到 succeeded · merge polling outputs 进主 outputs
    polling_spec = template.get("polling") or {}
    if polling_spec.get("enabled"):
        try:
            from workers.polling_runner import run_polling
            pr = run_polling(
                polling_spec=polling_spec,
                upstream_outputs=outputs,
                app_id=aid,
                context=context,
                progress=progress,
                cancel_check=None,
            )
            if not pr["ok"]:
                return {
                    "ok": False,
                    "outputs": outputs,
                    "http": {"status": resp.status_code, "elapsed_ms": elapsed_ms,
                             "polling_attempts": pr["attempts"],
                             "polling_elapsed_ms": pr["elapsed_ms"]},
                    "error": f"polling failed: {pr['error']}",
                }
            outputs.update(pr["outputs"])
        except Exception as e:
            import logging
            logging.getLogger("opus.http_executor").exception(
                "polling 框架异常 app=%s: %s", aid, e,
            )
            return {
                "ok": False, "outputs": outputs,
                "http": {"status": resp.status_code, "elapsed_ms": elapsed_ms},
                "error": f"polling crash: {type(e).__name__}: {e}",
            }

    # 卷四十六 III 补丁 5 · Y3 · 输出前 redact secret 真值
    # 防上游 API 在 response 里 echo back secret (debug API / 错误信息 / URL echo)
    # outputs 接下来要进 LLM context · 不 redact 就违反铁律 7 (LLM 永远只看 placeholder)
    try:
        from workers.secret_redactor import build_redactor
        _redact = build_redactor(aid)
        outputs = _redact(outputs)
    except Exception as e:
        # redact 失败不阻塞主流程 · 但要 warn (这是安全相关)
        import logging
        logging.getLogger("opus.http_executor").warning(
            "redact failed app=%s: %s · outputs 可能含 secret · 检查 app_secrets",
            aid, e,
        )

    if progress:
        try:
            progress("scripted_run_done", {
                "outputs_keys": [k for k in outputs.keys() if not k.startswith("_")],
                "elapsed_ms": elapsed_ms,
            })
        except Exception:
            pass

    return {
        "ok": True,
        "outputs": outputs,
        "http": {"status": resp.status_code, "elapsed_ms": elapsed_ms},
        "error": None,
    }
