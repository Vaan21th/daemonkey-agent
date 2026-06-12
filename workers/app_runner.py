"""workers/app_runner.py
========================

 12 · wish-165ea1f6 phase B · 跑一个 app · 复用 tool_loop · 独立 session

一个 app 跑一次 = 一个临时 messages list + 一次 run_tool_loop 调用。
不污染主对话历史·跑完即丢。 给两个上层场景用:

  1. POST /workshop/apps/{aid}/run  · 用户 在工坊『测试』tab 点 ▶ 真跑
  2. workflow_engine 跑到 app node 时 · 顺着拓扑调一次 run_app · 拿 outputs 接下游

设计哲学:
  - app 不是新的 daemon · 只是『带特定 system_prompt + 工具白名单』的一次 LLM 调用
  - 完全复用 tool_loop · 不写新 LLM 协议代码
  - confirm 在 app 上下文里 auto-approve (用户 主动点了▶ · 已经隐式同意 · 不再阻塞)
  - app 内的 tool 调用 progress 通过 SSE 流回 UI · 用户 实时看 AI 在干啥
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
        lines.append("正文部分照常给 用户 看 · JSON 块给下游程序提取 · 二者别冲突。")

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
    """app 跑动时 · 用户 已主动点 ▶ · auto-approve 所有 tool tier

    安全考量: app 一定要从 用户 信任的 AI / 用户 自己 create_app 出来 · 不是任意来源。
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
    max_iterations: int = 8,
    max_tokens: Optional[int] = None,
) -> dict:
    """跑一个 app · 返回结构化结果

    Args:
        app: app json (workshop_assets.load_app 出来的 dict · 含 system_prompt / tools / output_schema)
        inputs: form 字段名 → 值 · 跟 app.ui_form_schema 对齐 (但允许额外字段)
        runtime: daemon 的 RUNTIME 对象 · 从 daemon_api 注入
        progress: SSE hook · 来自 tool_loop 的 ProgressHook
        cancel_check: 用户 中途按取消时返回 True
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
            "用户 通过表单提供输入·你按表单字段把活做漂亮·调用授权工具完成实际产出。"
        )

    # 沉淀闭环 v2 刀① · 运行时强制注入 (不依赖 app 作者是否写对):
    #   1. 产出隔离——治产出串目录的事故
    #   2. 资产槽必读——治"多版本资产只剩废版"的事故
    #  P1 (2026-06-10) 补丁③ · 调度预算 — 治 token 失控 (用户 看计费台"意外的高")
    aid = app.get("id") or ""
    mandates = [
        "",
        "---",
        f"[内核纪律 · 产出隔离] 本次运行所有落盘产出 (图/音/视频/文档) 必须写入 "
        f"data/workshop/outputs/{aid}/ · 严禁写入其他 app 的 outputs 目录。"
        "需要引用其他 app 的历史产出·只读·不写。",
    ]
    slots = app.get("asset_slots") or []
    if slots:
        slot_desc = " · ".join(
            f"{s.get('name')}({s.get('label') or s.get('type')})"
            for s in slots if isinstance(s, dict)
        )
        mandates.append(
            f"[内核纪律 · 资产必读] 本 app 声明了用户个性资产槽: {slot_desc}。"
            f"用到时必须先读登记表 data/workshop/assets/{aid}.json "
            "(read_file 或 manage_app_asset 工具) 取 active/最新值 · 严禁凭记忆硬编码。"
        )
    # 调度预算: app sub-agent 不是主对话 · 没有"再来一轮"机会 · 必须在预算内出活
    # max_iterations - 2 留两轮给"汇总 + 最终 output" · 防 LLM 调到上限还在加工
    soft_budget = max(1, max_iterations - 2)
    mandates.append(
        f"[内核纪律 · 调度预算] 本次最多 {max_iterations} 轮 LLM 调用 (含工具调用 + 推理 · "
        f"上限到达即截断)。 把工具调用集中在前 {soft_budget} 轮 · "
        f"最后 {max_iterations - soft_budget} 轮必须给完整 output_schema 字段 · 不再调任何 tool。 "
        f"token 紧 · 不重复读同一文件 · 不 grep 后又 read 同一内容 · "
        f"可以的话一个 turn 里发多个 tool_call 并行 (tool batching)。"
    )
    system_prompt = system_prompt + "\n".join(mandates)

    user_msg = _build_input_prompt(app, inputs or {}, upstream_outputs)
    messages: list[dict] = [{"role": "user", "content": user_msg}]

    tools = _allowed_tools(app)
    # 沉淀闭环 v2 修补 · 工具白名单真生效 (之前 tools 只挂在 progress event 里给前端看
    # LLM 实际看的是全 REGISTRY · 审稿 app 因此能调 run_app 跑 5 分钟内容制作 · 现在拦)
    allowed_names: set[str] | None = {s.name for s in tools} if app.get("tools") else None

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
            allowed_tool_names=allowed_names,  # 白名单真生效
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

    # 沉淀闭环 v2 刀② · runs 自增 (字段早就有 · 自增一直缺失 · 所有 agentic 跑法都过这里)
    try:
        from .workshop_assets import increment_app_runs
        increment_app_runs(app.get("id") or "")
    except Exception:
        pass

    # 沉淀闭环 v2 刀④ · 收口提示计数 (反复跑 ≥3 次 30 分钟内会触发"要不要固化"提示)
    try:
        from .workshop_run_closure import note_app_run
        note_app_run(app.get("id") or "")
    except Exception:
        pass

    result_usage = {
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "cache_read_tokens": getattr(usage, "cache_read_tokens", 0),
        "cache_creation_tokens": getattr(usage, "cache_creation_tokens", 0),
    }

    iterations = max(1, (len(messages) - initial_msg_len + 1) // 2)

    #  P1 (2026-06-10) · token 撞顶检测 (用户 看计费台"意外的高"的根因之一)
    # iterations 接近 max_iterations 时 · LLM 大概率没真正出活 · 需要 用户 注意 + 落账
    hit_budget = iterations >= max_iterations
    near_budget = iterations >= max(1, max_iterations - 1) and not hit_budget
    warning = None
    if hit_budget:
        warning = (
            f"撞 max_iterations 上限 ({iterations}/{max_iterations}) · "
            f"sub-agent 没在预算内出完整 output_schema 字段 · 输出可能不完整 · "
            f"考虑: ① 提高 app 的 max_iterations · ② 精简 system_prompt · ③ 拆分成更小的 sub-app"
        )
    elif near_budget:
        warning = f"接近预算上限 ({iterations}/{max_iterations}) · 下次跑要注意 token 消耗"

    #  P1 (2026-06-10) · sub-agent token usage sink (sub-agent 跑完不进 session jsonl ·
    # 用户 之前只能去计费台对账 · 现在 sink 到 data/runtime/app_runs_usage.jsonl 一次性查)
    try:
        _sink_app_usage(app, inputs, result_usage, iterations, max_iterations, warning)
    except Exception:
        pass

    if progress:
        try:
            progress("app_run_done", {
                "app_id": app.get("id"),
                "outputs_keys": list(outputs.keys()),
                "iterations": iterations,
                "max_iterations": max_iterations,
                "usage": result_usage,
                "warning": warning,
                "hit_budget": hit_budget,
            })
        except Exception:
            pass

    return {
        "ok": True,
        "text": text or "",
        "outputs": outputs,
        "usage": result_usage,
        "iterations": iterations,
        "max_iterations": max_iterations,
        "warning": warning,
        "hit_budget": hit_budget,
        "error": None,
    }


def _sink_app_usage(
    app: dict,
    inputs: dict,
    usage: dict,
    iterations: int,
    max_iterations: int,
    warning: Optional[str],
) -> None:
    """落 sub-agent token usage 一行 jsonl · 给 用户 事后对账 · 不进 session 主流"""
    from pathlib import Path as _P
    import time as _t

    root = _P(__file__).resolve().parent.parent
    sink = root / "data" / "runtime" / "app_runs_usage.jsonl"
    sink.parent.mkdir(parents=True, exist_ok=True)

    in_tok = int(usage.get("input_tokens") or 0)
    out_tok = int(usage.get("output_tokens") or 0)
    cache_read = int(usage.get("cache_read_tokens") or 0)
    cache_create = int(usage.get("cache_creation_tokens") or 0)
    total = in_tok + out_tok

    entry = {
        "ts": _t.strftime("%Y-%m-%dT%H:%M:%S"),
        "app_id": app.get("id") or "",
        "app_name": app.get("name") or "",
        "iterations": iterations,
        "max_iterations": max_iterations,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_create,
        "total_tokens": total,
        "warning": warning,
        "input_keys": list((inputs or {}).keys()),
    }
    with open(sink, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
