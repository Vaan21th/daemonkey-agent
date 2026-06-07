"""workers/app_runner.py
========================

卷四十六续 12 · wish-165ea1f6 phase B · 跑一个 app · 复用 tool_loop · 独立 session

一个 app 跑一次 = 一个临时 messages list + 一次 run_tool_loop 调用。
不污染主对话历史·跑完即丢。 给两个上层场景用:

  1. POST /workshop/apps/{aid}/run  · BRO 在工坊『测试』tab 点 ▶ 真跑
  2. workflow_engine 跑到 app node 时 · 顺着拓扑调一次 run_app · 拿 outputs 接下游

设计哲学:
  - app 不是新的 daemon · 只是『带特定 system_prompt + 工具白名单』的一次 LLM 调用
  - 完全复用 tool_loop · 不写新 LLM 协议代码
  - confirm 在 app 上下文里 auto-approve (BRO 主动点了▶ · 已经隐式同意 · 不再阻塞)
  - app 内的 tool 调用 progress 通过 SSE 流回 UI · BRO 实时看 OPUS 在干啥
  - output_schema 存在时 · 在 prompt 末尾要求 LLM 输出 ```json {...}``` · 后处理 parse

调用约定:
    result = run_app(
        app=<dict>,
        inputs={'text': '...', 'emotion': '平静'},
        runtime=<RUNTIME>,
        progress=<hook>,
        cancel_check=<bool callable>,
        upstream_outputs=None,
    )
    # result = {
    #     'ok': True,
    #     'text': '...',                # LLM 最终回答全文 (markdown)
    #     'outputs': {'image_url': ...},# 按 output_schema 提取 · 没 schema 时 {'output': text}
    #     'usage': {...},
    #     'iterations': 3,              # tool_loop 跑了几个 turn
    # }
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from agent_tools import REGISTRY, TIER_AUTO


def _build_input_prompt(
    app: dict,
    inputs: dict,
    upstream_outputs: Optional[dict],
) -> str:
    """把 form 输入 + 工作流上游输出 拼成 user message · LLM 收到的就是这段话

    跟前端 _buildPromptFromForm 语义对齐 (一致体验)
    """
    lines: list[str] = []
    lines.append(f"请用应用「{app.get('name') or '(未命名)'}」处理这次请求 · 通过表单提供以下输入:")
    lines.append("")

    schema = app.get("ui_form_schema") or []
    name_to_meta = {f["name"]: f for f in schema if isinstance(f, dict) and f.get("name")}

    seen: set[str] = set()
    for f in schema:
        if not isinstance(f, dict):
            continue
        name = f.get("name") or ""
        if not name:
            continue
        seen.add(name)
        if name not in inputs:
            continue
        v = inputs[name]
        if v is None or v == "":
            continue
        label = f.get("label") or name
        ftype = (f.get("type") or "text").strip()
        if ftype == "textarea":
            lines.append(f"- **{label}** (`{name}`):")
            lines.append("  ```")
            for ln in str(v).split("\n"):
                lines.append("  " + ln)
            lines.append("  ```")
        elif ftype == "boolean":
            lines.append(f"- **{label}** (`{name}`): {'是' if v else '否'}")
        else:
            lines.append(f"- **{label}** (`{name}`): {v}")

    extra = {k: v for k, v in (inputs or {}).items() if k not in seen}
    if extra:
        lines.append("")
        lines.append("(额外参数·不在 schema 里·LLM 自己看着办)")
        for k, v in extra.items():
            lines.append(f"  - `{k}`: {v}")

    if upstream_outputs:
        lines.append("")
        lines.append("(工作流上游节点的输出·按需引用)")
        for k, v in upstream_outputs.items():
            preview = str(v)
            if len(preview) > 500:
                preview = preview[:500] + " ..."
            lines.append(f"  - `{k}`: {preview}")

    if app.get("description"):
        lines.append("")
        lines.append(f"(应用用途: {app['description']})")

    output_schema = app.get("output_schema") or []
    if output_schema:
        lines.append("")
        lines.append("---")
        lines.append("**输出契约** (重要 · 给下游工作流节点用):")
        lines.append("最终回答末尾请追加一个 ```json``` 代码块·包含以下字段:")
        for o in output_schema:
            if not isinstance(o, dict):
                continue
            n = o.get("name") or ""
            t = o.get("type") or "string"
            l = o.get("label") or n
            lines.append(f"  - `{n}` ({t}) · {l}")
        lines.append("示例: ```json\\n{\"field_a\": \"value\", \"field_b\": 42}\\n```")
        lines.append("正文部分照常给 BRO 看 · JSON 块给下游程序提取 · 二者别冲突。")

    return "\n".join(lines)


def _extract_outputs_from_text(text: str, output_schema: list[dict]) -> dict:
    """从 LLM 回答里提取 output 字段
    
    策略:
        1. 没 output_schema · 返回 {'output': text 全文}
        2. 有 schema · 找末尾的 ```json ... ``` 块·parse JSON · 按 schema name 字段提
        3. JSON 块缺失 / 解析失败 / 字段缺失 · 该字段值 = None · 上层决定降级到 raw text
    """
    text = text or ""
    if not output_schema:
        return {"output": text}

    out: dict = {}
    json_block = None
    for m in re.finditer(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, re.IGNORECASE):
        json_block = m.group(1)
    if json_block is None:
        m = re.search(r"(\{[\s\S]*\})\s*$", text.strip())
        if m:
            json_block = m.group(1)

    parsed: Optional[dict] = None
    if json_block:
        try:
            parsed = json.loads(json_block)
        except Exception:
            parsed = None

    for f in output_schema:
        if not isinstance(f, dict):
            continue
        n = f.get("name")
        if not n:
            continue
        if parsed and n in parsed:
            out[n] = parsed[n]
        else:
            out[n] = None

    out["_text"] = text
    out["_json_ok"] = parsed is not None
    return out


def _allowed_tools(app: dict) -> list:
    """根据 app.tools 白名单选 ToolSpec list · 空白名单 = 所有工具"""
    whitelist = app.get("tools") or []
    if not whitelist:
        return [s for s in REGISTRY.values()]
    return [REGISTRY[name] for name in whitelist if name in REGISTRY]


def _auto_confirm(spec, args, *more) -> str:
    """app 跑动时 · BRO 已主动点 ▶ · auto-approve 所有 tool tier
    
    安全考量: app 一定要从 BRO 信任的 OPUS / BRO 自己 create_app 出来 · 不是任意来源。
    后续如要更严·给 app json 加 safety 字段·让创建者决定级别。
    """
    return "yes"


def _no_observe(*args, **kwargs) -> None:
    pass


def run_app(
    *,
    app: dict,
    inputs: dict,
    runtime: Any,
    progress: Optional[Callable[[str, dict], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    upstream_outputs: Optional[dict] = None,
    max_iterations: int = 12,
    max_tokens: Optional[int] = None,
) -> dict:
    """跑一个 app · 返回结构化结果

    Args:
        app: app json (workshop_assets.load_app 出来的 dict · 含 system_prompt / tools / output_schema)
        inputs: form 字段名 → 值 · 跟 app.ui_form_schema 对齐 (但允许额外字段)
        runtime: daemon 的 RUNTIME 对象 · 从 daemon_api 注入
        progress: SSE hook · 来自 tool_loop 的 ProgressHook
        cancel_check: BRO 中途按取消时返回 True
        upstream_outputs: 工作流上游 node 的 outputs · 拼进 prompt 让 LLM 参考
        max_iterations: tool_loop 最多跑几个 turn (app 不该需要很多·12 足够)
        max_tokens: 输出 token 上限 · 默认走 RUNTIME 的全局值

    Returns:
        {
            'ok': bool,
            'text': str,            # LLM 最终回答 markdown
            'outputs': dict,        # 按 output_schema 提取 · 没 schema 时 {'output': text}
            'usage': dict,          # input_tokens / output_tokens / cache
            'iterations': int,
            'error': str | None,
        }
    """
    from tool_loop import run_tool_loop

    if not isinstance(app, dict) or not app.get("id"):
        return {"ok": False, "text": "", "outputs": {}, "usage": {},
                "iterations": 0, "error": "app spec invalid"}

    system_prompt = (app.get("system_prompt") or "").strip()
    if not system_prompt:
        system_prompt = (
            f"你正在以「{app.get('name') or 'app'}」这个 app 的身份运行。 "
            f"用途: {app.get('description') or '(未声明)'}。 "
            "BRO 通过表单提供输入·你按表单字段把活做漂亮·调用授权工具完成实际产出。"
        )

    user_msg = _build_input_prompt(app, inputs or {}, upstream_outputs)
    messages: list[dict] = [{"role": "user", "content": user_msg}]

    tools = _allowed_tools(app)

    used_max_tokens = max_tokens
    if used_max_tokens is None:
        used_max_tokens = getattr(runtime, "max_tokens", None) or 4096

    if progress:
        try:
            progress("app_run_start", {
                "app_id": app.get("id"),
                "app_name": app.get("name"),
                "input_keys": list((inputs or {}).keys()),
                "tools": [s.name for s in tools],
            })
        except Exception:
            pass

    iterations_before = 0  # tool_loop 不直接暴露 · 用 messages 长度变化近似
    initial_msg_len = len(messages)

    try:
        text, messages, usage = run_tool_loop(
            client=runtime.client,
            provider=runtime.provider,
            model=app.get("model_hint") or runtime.model,
            max_tokens=used_max_tokens,
            system=system_prompt,
            messages=messages,
            confirm=_auto_confirm,
            observe=_no_observe,
            max_iterations=max_iterations,
            base_url=runtime.base_url,
            progress=progress,
            cancel_check=cancel_check,
            on_message_commit=None,  # 不沉到 session jsonl · 跑完即丢
        )
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        if progress:
            try:
                progress("app_run_error", {"error": err})
            except Exception:
                pass
        return {
            "ok": False, "text": "", "outputs": {}, "usage": {},
            "iterations": 0, "error": err,
        }

    outputs = _extract_outputs_from_text(text, app.get("output_schema") or [])

    result_usage = {
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "cache_read_tokens": getattr(usage, "cache_read_tokens", 0),
        "cache_creation_tokens": getattr(usage, "cache_creation_tokens", 0),
    }

    iterations = max(1, (len(messages) - initial_msg_len + 1) // 2)

    if progress:
        try:
            progress("app_run_done", {
                "app_id": app.get("id"),
                "outputs_keys": list(outputs.keys()),
                "iterations": iterations,
                "usage": result_usage,
            })
        except Exception:
            pass

    return {
        "ok": True,
        "text": text or "",
        "outputs": outputs,
        "usage": result_usage,
        "iterations": iterations,
        "error": None,
    }
