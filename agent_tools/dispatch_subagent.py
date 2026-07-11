"""agent_tools/dispatch_subagent.py
===================================

主对话派分身 (v0.6.0 · P1)

一句话: 主对话里的 AI 把 1~N 个子任务派给隔离的「分身」并行干 · 每个分身独立上下文
+ 收紧工具白名单 · 跑完自动汇总结论回到本轮 tool_result。

底层复用 workers/subagent_runner.run_subagent (P0 抽的通用子执行器) —— 零改工具协议。

典型场景:
  用户: "同时查一下 A 框架、B 框架、C 框架各自的坑 · 再给我对比"
  → 派 3 个分身各查一个 · 并发跑 · 一份对比汇总回来 (不占主对话上下文逐个查)

安全边界:
  - **不递归**: 分身白名单里剔除 dispatch_subagent 自身 (v0.6.0 限一层)
  - **不给系统控制权**: 硬 DENY 掉 request_restart / update_core / summon_cursor 等
  - **默认只读**: 不显式给 tools 时 · 分身只拿【只读/研究】白名单 (查证类)
  - **并发上限 2** + 每分身迭代预算 + 汇总截断 —— 防 token 爆 / 爆父上下文
"""

from __future__ import annotations

from . import (
    REGISTRY,
    TIER_CONFIRM,
    ToolResult,
    ToolSpec,
    current_session_id,
    push_tool_progress,
    register_tool,
)

# 并发/规模闸 (并行烧 token → 上限 + 预算)
_MAX_CONCURRENCY = 2       # 最多同时 2 个分身在跑 (即使派了更多也排队)
_MAX_TASKS = 6             # 一次最多派 6 个
_DEFAULT_MAX_ITER = 12     # 每分身默认迭代预算
_MAX_ITER_CAP = 24         # 单分身迭代硬顶
_TEXT_CLIP = 2500          # 每份分身产出汇总时截断 (防爆父上下文 · 全文在 sub-*.jsonl)

# 永不下放给分身的工具 (递归 + 系统控制 + 破坏性)。 即便调用方显式点名也剔除。
_ALWAYS_DENY = frozenset({
    "dispatch_subagent",   # 防无限递归 (v0.6.0 限一层)
    "request_restart", "update_core", "summon_cursor", "set_model",
    "empty_trash", "delete_app_to_trash",
    "service_start", "service_stop",
})

# 不显式给 tools 时的默认白名单 = 只读 / 研究 / 查证类 (最安全 · 覆盖"并行调研"主场景)。
# 运行时与 REGISTRY 取交集 · 容忍工具改名/裁剪。
_DEFAULT_READONLY = (
    "read_file", "grep_files", "glob_files", "search_code", "outline_file",
    "web_search", "web_fetch", "web_search_image", "pdf_read",
    "read_dashboard", "recall_memory", "session_search", "verify_claim",
    "list_apps", "list_flows", "look_at",
)


def _resolve_whitelist(task_tools) -> set[str]:
    """算一个分身该拿的工具白名单。 空 → 默认只读集。 给了 → 过 DENY + 存在性。"""
    if task_tools:
        wl = {t for t in task_tools if isinstance(t, str)}
    else:
        wl = set(_DEFAULT_READONLY)
    wl = {t for t in wl if t in REGISTRY and t not in _ALWAYS_DENY}
    return wl


def _summarize(args: dict) -> str:
    tasks = args.get("tasks") or []
    goals = [str((t or {}).get("goal") or "?")[:40] for t in tasks if isinstance(t, dict)]
    n = len(goals)
    head = " / ".join(goals[:3]) + (" …" if n > 3 else "")
    return f"派 {n} 个分身并行: {head}"


def _run_one(idx: int, task: dict, runtime, parent_sid: str) -> dict:
    """跑单个分身 · 返回 {idx, goal, ok, text, iterations, usage, warning, error, sub_session_id}"""
    from workers.subagent_runner import run_subagent

    goal = str(task.get("goal") or "").strip()
    wl = _resolve_whitelist(task.get("tools"))
    try:
        max_iter = int(task.get("max_iter") or _DEFAULT_MAX_ITER)
    except Exception:
        max_iter = _DEFAULT_MAX_ITER
    max_iter = max(1, min(max_iter, _MAX_ITER_CAP))

    system = (
        "你是主对话派出的『子执行器分身』。 只负责完成下面这一个子任务 · "
        "用授权的（默认只读/研究）工具查证清楚 · 最后直接给一段【结构化、可被上层直接汇总】"
        "的结论: 先要点 · 再关键依据/信源 · 不寒暄 · 不展开无关内容 · 不复述任务。 "
        "拿不准或工具受限就如实说明 · 不要编造。"
    )
    user_msg = f"子任务目标:\n{goal}"

    push_tool_progress("🧩 分身启动", f"#{idx} · {goal[:30]}")
    r = run_subagent(
        system=system,
        user_msg=user_msg,
        runtime=runtime,
        tools_whitelist=wl,
        max_iterations=max_iter,
        progress=None,               # 分身工具级事件不逐个回灌主 SSE (只回灌启动/完成里程碑)
        persist=True,                # 落 sessions/sub-*.jsonl 可回看 (可追溯)
        parent_session_id=parent_sid,
        inject_budget_mandate=True,
    )
    push_tool_progress("✓ 分身完成", f"#{idx} · {r.iterations} 轮")
    return {
        "idx": idx, "goal": goal, "ok": r.ok, "text": r.text,
        "iterations": r.iterations, "usage": r.usage, "warning": r.warning,
        "error": r.error, "sub_session_id": r.sub_session_id,
        "whitelist": sorted(wl),
    }


def _run(args: dict) -> ToolResult:
    from concurrent.futures import ThreadPoolExecutor
    from daemon_runtime import RUNTIME

    raw = args.get("tasks")
    if not isinstance(raw, list) or not raw:
        return ToolResult(ok=False, output="", error="tasks 必填 · 是一个数组 · 每项 {goal, tools?, max_iter?}")

    tasks = [t for t in raw if isinstance(t, dict) and str(t.get("goal") or "").strip()]
    if not tasks:
        return ToolResult(ok=False, output="", error="每个 task 必须有非空 goal")
    if len(tasks) > _MAX_TASKS:
        return ToolResult(
            ok=False, output="",
            error=f"一次最多派 {_MAX_TASKS} 个分身 (你给了 {len(tasks)}) · 拆成多次或合并子任务",
        )

    if RUNTIME.client is None:
        return ToolResult(ok=False, output="", error="RUNTIME.client 未就绪 (daemon 未完全启动?)")

    parent_sid = current_session_id()
    push_tool_progress("🧩 派发分身", f"{len(tasks)} 个 · 并发 {min(_MAX_CONCURRENCY, len(tasks))}")

    # 并发跑 · max_workers 卡 2 · 即便派 6 个也只 2 个同时烧 (token 安全)
    results: list[dict] = [None] * len(tasks)  # type: ignore
    with ThreadPoolExecutor(max_workers=min(_MAX_CONCURRENCY, len(tasks))) as pool:
        futs = {
            pool.submit(_run_one, i + 1, t, RUNTIME, parent_sid): i
            for i, t in enumerate(tasks)
        }
        for fut in futs:
            i = futs[fut]
            try:
                results[i] = fut.result()
            except Exception as e:
                results[i] = {
                    "idx": i + 1, "goal": str(tasks[i].get("goal") or ""),
                    "ok": False, "text": "", "iterations": 0, "usage": {},
                    "warning": None, "error": f"{type(e).__name__}: {e}",
                    "sub_session_id": None, "whitelist": [],
                }

    ok_n = sum(1 for r in results if r and r.get("ok"))
    tot_in = sum((r.get("usage") or {}).get("input_tokens", 0) for r in results if r)
    tot_out = sum((r.get("usage") or {}).get("output_tokens", 0) for r in results if r)

    lines = [
        f"# 🧩 派出 {len(tasks)} 个分身 · 完成 {ok_n}/{len(tasks)} · "
        f"并发 {min(_MAX_CONCURRENCY, len(tasks))} · tokens in/out {tot_in}/{tot_out}",
        "",
    ]
    for r in results:
        if not r:
            continue
        head = f"## 分身 {r['idx']} · {r['goal']}"
        lines.append(head)
        if not r.get("ok"):
            lines.append(f"❌ 失败: {r.get('error') or '(未知)'}")
            lines.append("")
            continue
        text = r.get("text") or "(无输出)"
        clipped = len(text) > _TEXT_CLIP
        if clipped:
            text = text[:_TEXT_CLIP] + f"\n\n… [截断 · 全文见 sessions/sub-{r.get('sub_session_id')}.jsonl]"
        lines.append(text)
        meta = f"_(迭代 {r.get('iterations')} 轮 · sub-{r.get('sub_session_id')}"
        if r.get("warning"):
            meta += f" · ⚠ {r['warning']}"
        meta += ")_"
        lines.append("")
        lines.append(meta)
        lines.append("")

    # 全挂 → 工具级失败 (让主 LLM 知道要换法) · 部分成功 → ok=True 带失败标注
    return ToolResult(ok=ok_n > 0, output="\n".join(lines).rstrip(),
                      error=None if ok_n > 0 else "所有分身都失败了")


SPEC = ToolSpec(
    name="dispatch_subagent",
    description=(
        "派 1~N 个『子执行器分身』并行完成子任务 · 各自独立上下文 + 收紧工具白名单 · "
        "跑完自动汇总结论回到本轮。 适合【并行调研 / 多方向查证 / 分头取材再汇总】。\n\n"
        "**什么时候用**:\n"
        "  - 一个请求天然拆成几个独立子任务 (查 A、查 B、查 C 再对比) → 并行比自己逐个查省时\n"
        "  - 想把一段查证隔离出去 · 不让中间过程占满主对话上下文\n"
        "  - 也可放进某个工坊 app 的 tools · 让 app 步内并行 (如『素材并行查询』把每个镜头的\n"
        "    检索词一次并行搜) → app 跑到这步会自动放行 · 不打断你\n\n"
        "**用法**:\n"
        "  - tasks: 数组 · 每项 {goal(必填一句话目标), tools?(工具白名单), max_iter?(迭代预算)}\n"
        "  - 不给 tools → 分身默认只拿【只读/研究】工具 (read_file/grep/web_search/… · 最安全)\n"
        "  - 要分身能写文件才显式给 tools · 但破坏性/系统控制类工具永远被剔除\n\n"
        "**边界 (安全)**:\n"
        f"  - 一次最多 {_MAX_TASKS} 个 · 并发上限 {_MAX_CONCURRENCY} (排队跑 · 防 token 爆)\n"
        "  - 分身【不能】再派分身 (限一层递归) · 【不给】request_restart/update_core 等系统控制权\n"
        "  - 每个分身跑完落 sessions/sub-*.jsonl 可回看 (可追溯)\n\n"
        "**tier**: CONFIRM · 会并行烧 token · 派之前让你拍一下确认 (信任 flow 内自动放行)"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "description": "要并行派发的子任务列表 (1~6 个)",
                "items": {
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string", "description": "这个分身要完成的一句话目标 (必填)"},
                        "tools": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可选 · 该分身的工具白名单 · 空则默认只读/研究集",
                        },
                        "max_iter": {"type": "integer", "description": f"可选 · 迭代预算 · 默认 {_DEFAULT_MAX_ITER} · 硬顶 {_MAX_ITER_CAP}"},
                    },
                    "required": ["goal"],
                },
            },
        },
        "required": ["tasks"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
