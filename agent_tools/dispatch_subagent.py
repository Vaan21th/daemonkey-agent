"""agent_tools/dispatch_subagent.py
===================================

主对话派分身 (v0.6.0 · P1 · wish-ea92d2f9 三件套: 注册表/status/cancel/预设)

一句话: 主对话里的 Daemonkey 把 1~N 个子任务派给隔离的「分身」并行干 · 每个分身独立上下文
+ 收紧工具白名单 · 跑完自动汇总结论回到本轮 tool_result。

底层复用 workers/subagent_runner.run_subagent (P0 抽的通用子执行器) —— 零改工具协议。

典型场景:
  BRO: "同时查一下 A 框架、B 框架、C 框架各自的坑 · 再给我对比"
  → 派 3 个分身各查一个 · 并发跑 · 一份对比汇总回来 (不占主对话上下文逐个查)

安全边界:
  - **不递归**: 分身白名单里剔除 dispatch_subagent 自身 (v0.6.0 限一层)
  - **不给系统控制权**: 硬 DENY 掉 request_restart / update_core / summon_cursor 等
  - **默认只读**: 不显式给 tools 时 · 分身只拿【只读/研究】白名单 (查证类)
  - **并发上限 2** + 每分身迭代预算 + 汇总截断 —— 防 token 爆 / 爆父上下文
"""

from __future__ import annotations

import concurrent.futures
import threading
import uuid

from . import (
    REGISTRY,
    TIER_AUTO,
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
_SUBAGENT_WALL_CLOCK_SEC = 600.0  # 墙钟熔断 (2026-08-11 · 墨言贡献评估 · 08-09 卡死事故同源):
                                   # 分身 LLM 挂起时 fut.result 裸等会永久占线程 · 硬墙钟到点判超时释放

# 永不下放给分身的工具 (递归 + 系统控制 + 破坏性 + 真实世界副作用)。 即便调用方显式点名也剔除。
_ALWAYS_DENY = frozenset({
    "dispatch_subagent",   # 防无限递归 (v0.6.0 限一层)
    "request_restart", "update_core", "summon_cursor", "set_model",
    "empty_trash", "delete_app_to_trash",
    "service_start", "service_stop",
    # 真实世界副作用 (分身 _auto_confirm 全自动批准 · 不能让它无确认发微信/开应用/写剪贴板)
    "wechat_send", "open_app", "write_clipboard",
})

# 不显式给 tools 时的默认白名单 = 只读 / 研究 / 查证类 (最安全 · 覆盖"并行调研"主场景)。
# 运行时与 REGISTRY 取交集 · 容忍工具改名/裁剪。
_DEFAULT_READONLY = (
    "read_file", "grep_files", "glob_files", "search_code", "outline_file",
    "web_search", "web_fetch", "web_search_image", "pdf_read",
    "read_dashboard", "recall_memory", "session_search", "verify_claim",
    "list_apps", "list_flows", "look_at",
)

# ── 活跃分身注册表 (生命周期状态机 · wish-d012591e) ─────────────────────────
# 派出的每个分身在这里登记一条: subagent_id → 实时状态。
# 状态流转: running → success / failed / cancelled (由 _run_one 收尾时更新)。
# 目的: ① 主对话能查/打断正在跑的分身 ② 汇总输出带每个分身的状态与用量明细。
_ACTIVE_SUBAGENTS: dict[str, dict] = {}
_ACTIVE_LOCK = threading.Lock()
_SUBAGENT_ID_PREFIX = "sub"


def _register_subagent(record: dict) -> None:
    with _ACTIVE_LOCK:
        _ACTIVE_SUBAGENTS[record["subagent_id"]] = record


def _update_subagent(subagent_id: str, **patch) -> None:
    with _ACTIVE_LOCK:
        rec = _ACTIVE_SUBAGENTS.get(subagent_id)
        if rec is not None:
            rec.update(patch)


def _unregister_subagent(subagent_id: str) -> None:
    with _ACTIVE_LOCK:
        _ACTIVE_SUBAGENTS.pop(subagent_id, None)


def _snapshot_subagents() -> list[dict]:
    """返回当前所有活跃分身的只读快照 (排序稳定 · 供状态工具/汇总用)。"""
    with _ACTIVE_LOCK:
        return [dict(r) for r in _ACTIVE_SUBAGENTS.values()]


def _list_active_subagents() -> ToolResult:
    """工具 `dispatch_subagent_status` · 列出正在跑 / 刚结束的分身与用量。"""
    snaps = _snapshot_subagents()
    if not snaps:
        return ToolResult(ok=True, output="当前没有活跃分身。")
    lines = [f"# 🧩 活跃分身 {len(snaps)} 个", ""]
    for r in snaps:
        lines.append(
            f"- `{r['subagent_id']}` · #{r.get('idx')} · {r.get('status')} · "
            f"goal={r.get('goal', '')[:40]} · 工具 {r.get('tool_calls', 0)} 次 · "
            f"tokens in/out {r.get('usage', {}).get('input_tokens', 0)}/"
            f"{r.get('usage', {}).get('output_tokens', 0)}"
        )
    return ToolResult(ok=True, output="\n".join(lines))


def _cancel_subagent(subagent_id: str) -> ToolResult:
    """工具 `dispatch_subagent_cancel` · 请求打断一个正在跑的分身。

    分身会在下一个迭代边界停下 (cancel_check 注入 run_subagent)。
    已结束/不存在 → 返回 ok=False 提示。
    """
    with _ACTIVE_LOCK:
        rec = _ACTIVE_SUBAGENTS.get(subagent_id)
        if rec is None:
            return ToolResult(
                ok=False, output="",
                error=f"分身 {subagent_id} 不存在或已结束 (可用 dispatch_subagent_status 查活跃列表)",
            )
        rec["cancel_requested"] = True
    return ToolResult(ok=True, output=f"已请求打断分身 {subagent_id} · 会在下一个迭代边界停下")


def _resolve_whitelist(task_tools) -> set[str]:
    """算一个分身该拿的工具白名单。 空/非 list → 默认只读集。 给了 → 过 DENY + 存在性。"""
    if isinstance(task_tools, list) and task_tools:
        wl = {t for t in task_tools if isinstance(t, str)}
    else:
        # 非 list (LLM 误传字符串会被拆成字符集 → 白名单变空) · 一律按"没给"处理
        wl = set(_DEFAULT_READONLY)
    wl = {t for t in wl if t in REGISTRY and t not in _ALWAYS_DENY}
    return wl


# ── 分身预设文件 (wish-acf41e99) ─────────────────────────────────────────────
# data/agents/*.json 定义分身预设: {name, description, model, tools[]}
# dispatch 时 tasks[].agent="<name>" → 命中预设则用预设的 model + tools + 描述后缀。
# 未命中 / 未配 → 现状 (继承 runtime.model + 默认只读) · 零回归。
_AGENTS_DIR = None
_AGENTS_CACHE: dict = {"mtime": 0.0, "presets": {}}


def _agents_dir() -> "object":
    global _AGENTS_DIR
    if _AGENTS_DIR is None:
        from pathlib import Path
        _AGENTS_DIR = Path(__file__).resolve().parent.parent / "data" / "agents"
        _AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    return _AGENTS_DIR


def _load_agent_presets() -> dict[str, dict]:
    """读 data/agents/*.json · 返回 {name: preset}。 mtime 失效缓存。"""
    global _AGENTS_CACHE
    import json as _json
    d = _agents_dir()
    try:
        mtime = max((f.stat().st_mtime for f in d.glob("*.json")), default=0.0)
    except Exception:
        return {}
    if mtime == _AGENTS_CACHE["mtime"] and _AGENTS_CACHE["presets"]:
        return _AGENTS_CACHE["presets"]
    presets = {}
    for f in d.glob("*.json"):
        try:
            cfg = _json.loads(f.read_text(encoding="utf-8"))
            name = str(cfg.get("name") or f.stem).strip()
            if name:
                presets[name] = cfg
        except Exception:
            continue
    _AGENTS_CACHE = {"mtime": mtime, "presets": presets}
    return presets


def _resolve_agent(task: dict) -> dict | None:
    """按 tasks[].agent 找预设。 返回 {model, tools, system_suffix} 或 None。"""
    name = str(task.get("agent") or "").strip()
    if not name:
        return None
    cfg = _load_agent_presets().get(name)
    if not cfg:
        return None
    tools = [t for t in (cfg.get("tools") or []) if isinstance(t, str)] or None
    suffix = ""
    desc = str(cfg.get("description") or "").strip()
    if desc:
        suffix = f"\n\n[分身预设 · {name}] {desc}"
    return {"model": (cfg.get("model") or "").strip() or None, "tools": tools, "system_suffix": suffix}


def _summarize(args: dict) -> str:
    tasks = args.get("tasks") or []
    goals = [str((t or {}).get("goal") or "?")[:40] for t in tasks if isinstance(t, dict)]
    n = len(goals)
    head = " / ".join(goals[:3]) + (" …" if n > 3 else "")
    return f"派 {n} 个分身并行: {head}"


def _run_one(idx: int, task: dict, runtime, parent_sid: str, cancel_check=None) -> dict:
    """跑单个分身 · 返回 {idx, goal, ok, text, iterations, usage, warning, error, sub_session_id}

    - 登记进 _ACTIVE_SUBAGENTS (生命周期状态机)
    - progress 回调累计工具调用数/用量 → 注册表快照 (可被 status/cancel 工具读到)
    - cancel_check 注入 run_subagent → 下一个迭代边界可打断
    """
    from workers.subagent_runner import run_subagent

    goal = str(task.get("goal") or "").strip()
    # 预设 (wish-acf41e99): 命中 agent=预设名 → 用预设 model + tools + 描述后缀 · 未命中零回归
    agent_cfg = _resolve_agent(task)
    if agent_cfg is not None and agent_cfg["tools"] and not task.get("tools"):
        wl = _resolve_whitelist(agent_cfg["tools"])
    else:
        wl = _resolve_whitelist(task.get("tools"))
    try:
        max_iter = int(task.get("max_iter") or _DEFAULT_MAX_ITER)
    except Exception:
        max_iter = _DEFAULT_MAX_ITER
    max_iter = max(1, min(max_iter, _MAX_ITER_CAP))

    subagent_id = f"{_SUBAGENT_ID_PREFIX}-{uuid.uuid4().hex[:8]}"
    _register_subagent({
        "subagent_id": subagent_id, "idx": idx, "goal": goal,
        "status": "running", "tool_calls": 0, "usage": {}, "cancel_requested": False,
    })

    system = (
        "你是主对话派出的『子执行器分身』。 只负责完成下面这一个子任务 · "
        "用授权的（默认只读/研究）工具查证清楚 · 最后直接给一段【结构化、可被上层直接汇总】"
        "的结论: 先要点 · 再关键依据/信源 · 不寒暄 · 不展开无关内容 · 不复述任务。 "
        "拿不准或工具受限就如实说明 · 不要编造。\n"
        "【边查边输出】每确认一个要点就写一小段文字结论·不要憋到最后才写——"
        "即使中途预算耗尽·上层也要能拿到部分发现。连读 3 个文件/跑 3 个测试还没输出任何文字"
        "就是探索无收敛·系统会提示你停下来总结。"
    )
    if agent_cfg is not None and agent_cfg["system_suffix"]:
        system += agent_cfg["system_suffix"]
    user_msg = f"子任务目标:\n{goal}"

    # 主对话取消 (cancel_event) 与单分身取消 (cancel_requested) 任一命中 → 停下
    _rec_cancel = {"requested": False}

    def _progress(event_type: str, data: dict) -> None:
        # 只累计到注册表 (状态机可读) · 不逐个回灌主 SSE (防爆)
        try:
            if event_type == "tool_call":
                with _ACTIVE_LOCK:
                    rec = _ACTIVE_SUBAGENTS.get(subagent_id)
                    if rec is not None:
                        rec["tool_calls"] += 1
        except Exception:
            pass

    def _cancel() -> bool:
        with _ACTIVE_LOCK:
            rec = _ACTIVE_SUBAGENTS.get(subagent_id)
            if rec and rec.get("cancel_requested"):
                _rec_cancel["requested"] = True
                return True
        return bool(cancel_check() if callable(cancel_check) else False)

    push_tool_progress("🧩 分身启动", f"#{idx} · {goal[:30]}")
    try:
        r = run_subagent(
            system=system,
            user_msg=user_msg,
            runtime=runtime,
            tools_whitelist=wl,
            max_iterations=max_iter,
            model=(agent_cfg or {}).get("model"),   # 预设模型 · None → 继承 runtime.model
            progress=_progress,
            persist=True,                # 落 sessions/sub-*.jsonl 可回看 (可追溯)
            parent_session_id=parent_sid,
            inject_budget_mandate=True,
            cancel_check=_cancel,
            wall_clock_sec=_SUBAGENT_WALL_CLOCK_SEC,  # 2026-08-11 · 分身内部 LLM 挂起熔断 (外层 fut.result 兜底 · 内层真中断)
        )
    finally:
        # 生命状态机收尾 · 不管成功失败都更新注册表
        status = "cancelled" if _rec_cancel["requested"] else ("success" if r.ok else "failed")
        _update_subagent(subagent_id, status=status)

    push_tool_progress("✓ 分身完成", f"#{idx} · {r.iterations} 轮 · {status}")
    return {
        "idx": idx, "goal": goal, "ok": r.ok, "text": r.text,
        "iterations": r.iterations, "usage": r.usage, "warning": r.warning,
        "error": r.error, "sub_session_id": r.sub_session_id,
        "subagent_id": subagent_id, "status": status,
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

    # 新派发时清掉上一轮已结束的分身记录 (防注册表无限累积 · 保留最近的供 status 查)
    with _ACTIVE_LOCK:
        for sid in [k for k, v in _ACTIVE_SUBAGENTS.items()
                    if v.get("status") in ("success", "failed", "cancelled")]:
            _ACTIVE_SUBAGENTS.pop(sid, None)

    # 主对话停止链路 (协同模式): args._cancel_event → 分身的 cancel_check 会命中
    cancel_event = args.get("_cancel_event")
    _cancel_check = None
    if cancel_event is not None:
        try:
            _cancel_check = lambda: bool(cancel_event.is_set())  # noqa: E731
        except Exception:
            _cancel_check = None

    # 并发跑 · max_workers 卡 2 · 即便派 6 个也只 2 个同时烧 (token 安全)
    # 2026-08-11 墙钟熔断 (墨言贡献评估 · 08-09 卡死事故同源):
    #   fut.result() 裸等 → 子代理 LLM 挂起时永远等 → 占 session 锁 40+ 分钟 (08-09 16:47 事故根因)。
    #   _SUBAGENT_WALL_CLOCK_SEC 硬墙钟 + fut.result(timeout=墙钟+30s) 兜底 · 到点标记超时返回。
    results: list[dict] = [None] * len(tasks)  # type: ignore
    with ThreadPoolExecutor(max_workers=min(_MAX_CONCURRENCY, len(tasks))) as pool:
        futs = {
            pool.submit(_run_one, i + 1, t, RUNTIME, parent_sid, _cancel_check): i
            for i, t in enumerate(tasks)
        }
        for fut in futs:
            i = futs[fut]
            try:
                results[i] = fut.result(timeout=_SUBAGENT_WALL_CLOCK_SEC + 30)
            except concurrent.futures.TimeoutError:
                results[i] = {
                    "idx": i + 1, "goal": str(tasks[i].get("goal") or ""),
                    "ok": False, "text": "",
                    "iterations": 0, "usage": {},
                    "warning": None,
                    "error": f"墙钟熔断: 子代理超过 {_SUBAGENT_WALL_CLOCK_SEC}s 未完成 (LLM 挂起?) · 已释放占位",
                    "sub_session_id": None, "whitelist": [],
                }
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
    tot_cache_r = sum((r.get("usage") or {}).get("cache_read_tokens", 0) for r in results if r)

    lines = [
        f"# 🧩 派出 {len(tasks)} 个分身 · 完成 {ok_n}/{len(tasks)} · "
        f"并发 {min(_MAX_CONCURRENCY, len(tasks))} · tokens in/out/cache_read {tot_in}/{tot_out}/{tot_cache_r}",
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
        us = r.get("usage") or {}
        meta = (
            f"_(分身 {r.get('subagent_id')} · {r.get('status', '?')} · 迭代 {r.get('iterations')} 轮 · "
            f"tokens in/out/cache {us.get('input_tokens', 0)}/{us.get('output_tokens', 0)}/"
            f"{us.get('cache_read_tokens', 0)}"
        )
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
        "  - tasks: 数组 · 每项 {goal(必填一句话目标), tools?(工具白名单), max_iter?(迭代预算), agent?(分身预设名)}\n"
        "  - 不给 tools → 分身默认只拿【只读/研究】工具 (read_file/grep/web_search/… · 最安全)\n"
        "  - 要分身能写文件才显式给 tools · 但破坏性/系统控制类工具永远被剔除\n"
        "  - 给 agent=预设名 (data/agents/*.json 里的 name) → 用预设的模型 + 工具 + 描述 (可省钱分工)\n\n"
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
                        "agent": {
                            "type": "string",
                            "description": "可选 · 分身预设名 (data/agents/*.json 的 name) · 命中则用预设的模型+工具+描述",
                        },
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


# ── 生命周期运维工具 (wish-d012591e) ────────────────────────────────────────
_STATUS_SPEC = ToolSpec(
    name="dispatch_subagent_status",
    description=(
        "列出当前活跃分身的实时状态 (subagent_id / 状态 / goal / 工具调用数 / 用量)。\n"
        "配 dispatch_subagent_cancel 用: 先 status 拿到 subagent_id → cancel 打断。\n"
        "**tier**: AUTO · 只读"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {},
        "required": [],
    },
    run=lambda args: _list_active_subagents(),
    summarize=lambda args: "查活跃分身状态",
)
register_tool(_STATUS_SPEC)

_CANCEL_SPEC = ToolSpec(
    name="dispatch_subagent_cancel",
    description=(
        "请求打断一个正在跑的分身 (按 dispatch_subagent_status 拿到的 subagent_id)。\n"
        "分身会在下一个迭代边界停下 · 输出标记为 cancelled。\n"
        "**tier**: CONFIRM · 打断是操作行为"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "subagent_id": {
                "type": "string",
                "description": "要打断的分身 id (dispatch_subagent_status 返回的 subagent_id 字段)",
            },
        },
        "required": ["subagent_id"],
    },
    run=lambda args: _cancel_subagent(str(args.get("subagent_id") or "")),
    summarize=lambda args: f"打断分身 {str(args.get('subagent_id') or '?')}",
)
register_tool(_CANCEL_SPEC)
