"""workers/subagent_runner.py
=============================

v0.6.0 · P0 · 通用「子执行器」内核 (提案 docs/PROPOSAL-subagent-flow-v0.5.md)

一句话: 把 app_runner 里「临时 messages + 一次 run_tool_loop + 记账」这段**通用中段**
抽成独立可复用件。 subagent = 一次隔离的 LLM 工具循环:

  - 独立上下文 (自带 system + 一条 user 任务 · 不碰主对话历史)
  - 工具白名单 (allowed_tool_names · 越权调用被 tool_loop 拦)
  - 迭代预算 (max_iterations · 撞顶告警)
  - 跑完即丢 (persist=False) 或落盘可观测 (persist=True → sessions/sub-<id>.jsonl)
  - 结构化结果回传 (SubagentResult · text/usage/iterations/warning)

三个上层复用它:
  1. app_runner.run_app  —— 工坊 app 执行 (P0: 改薄壳调这里 · app 专属逻辑留壳里)
  2. agent_tools/dispatch_subagent —— 主对话派 1~N 个分身并行 (P1)
  3. flow_runner 每步 —— 工作流串行 (P2)

设计边界 (守死 · 防把工坊味带进通用核心):
  - 本文件【不】做: 表单 prompt 拼装 / output_schema 提取 / 产出隔离 mandate /
    工坊 runs 自增 / app 专属 progress 事件 —— 那些是 run_app 的活 · 留在壳里。
  - 本文件【只】做: 组 messages → run_tool_loop → 迭代/usage 记账 → 可选落盘 → 收敛结果。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class SubagentResult:
    ok: bool
    text: str = ""
    outputs: dict = field(default_factory=dict)   # {"output": text} · 便利默认 · run_app 走自己的 output_schema 提取
    usage: dict = field(default_factory=dict)
    iterations: int = 0
    max_iterations: int = 0
    warning: Optional[str] = None
    hit_budget: bool = False
    sub_session_id: Optional[str] = None
    messages: list = field(default_factory=list)  # 跑完的完整 messages (flow/复跑可回看)
    error: Optional[str] = None


def _auto_confirm(spec, args, *more) -> str:
    """子执行器沙盒内默认 auto-approve —— 与 app_runner 同哲学。

    安全靠的是【工具白名单】(allowed_tool_names): 白名单外的工具 tool_loop 直接返
    "not allowed" 根本执行不到。 派分身的上层 (dispatch_subagent) 负责给一个不含
    GUARD 高危工具的收紧白名单。 需要更严时上层可传自定义 confirm。
    """
    return "yes"


def _no_observe(*args, **kwargs) -> None:
    pass


def _budget_mandate(max_iterations: int) -> str:
    """通用调度预算纪律 (治并行分身 token 失控)。

    注意: 这是【通用版】· 不提 output_schema (那是 app 专属)。 run_app 有自己的
    app 版预算 mandate · 所以 run_app 调本模块时传 inject_budget_mandate=False ·
    避免重复注入 / 措辞漂移。
    """
    soft = max(1, max_iterations - 1)
    return (
        f"\n[内核纪律 · 调度预算] 本次最多 {max_iterations} 轮 LLM 调用 (含工具调用 + 推理 · "
        f"上限到达即截断)。 把工具调用集中在前 {soft} 轮 · 最后一轮给出完整结论不再调 tool。 "
        f"token 紧 · 不重复读同一文件 · 不 grep 后又 read 同一内容 · "
        f"可以的话一个 turn 里发多个 tool_call 并行 (tool batching)。"
    )


def _make_commit_writer(sub_session_id: str) -> Callable[[dict], None]:
    """persist=True 时 · 把每个 turn 增量落到 sessions/sub-<id>.jsonl (可观测/可回看)。

    刻意做轻: 不走 daemon_session 那套全套会话基建 (那是主对话/续场的地盘) ·
    子会话只是「附加可观测层」· 一行一个 turn 的 jsonl 足够 P0/P1 回看。
    """
    root = Path(__file__).resolve().parent.parent
    path = root / "sessions" / f"sub-{sub_session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)

    def _commit(entry: dict) -> None:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 落盘失败不能把子任务本身搞崩

    return _commit


def run_subagent(
    *,
    system: str,
    user_msg: str,
    runtime: Any,
    tools_whitelist: Optional[set[str]] = None,
    max_iterations: int = 8,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
    client: Optional[Any] = None,
    confirm: Optional[Callable] = None,
    progress: Optional[Callable[[str, dict], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    inject_budget_mandate: bool = True,
    persist: bool = False,
    parent_session_id: Optional[str] = None,
    wall_clock_sec: Optional[float] = None,
    initial_messages: Optional[list] = None,
    meta_extra: Optional[dict] = None,
) -> SubagentResult:
    """跑一个子执行器 · 返回结构化结果。

    Args:
        system: 完整 system prompt (上层已拼好 · 本函数只按需追加通用预算 mandate)。
        user_msg: 这个子任务的 user 消息 (goal / 表单渲染文本 / 上游产出已折叠进来)。
        runtime: daemon RUNTIME (需要 .client / .provider / .model / .base_url)。
        tools_whitelist: None=全 REGISTRY (慎用) · set=只暴露白名单 (越权被 tool_loop 拦)。
        max_iterations: tool_loop 最多几轮 (子任务不该很多)。
        max_tokens: 输出上限 · None → 走 bg_max_tokens + safe_max_tokens 兜底。
        model: 模型 id · None → runtime.model。
        client: 自定义 LLM client · None → runtime.client (wish-8ffb9d65 · 总监跨 provider 现场建)。
        confirm: 自定义确认回调 · None → 沙盒 auto-approve (_auto_confirm)。
        progress: SSE 进度 hook · 透传给 tool_loop 做工具级事件 (生命周期事件由上层发)。
        cancel_check: 返回 True 则下一轮前停。
        inject_budget_mandate: True → 追加通用预算纪律 (dispatch 用) · False → 上层自带 (run_app 用)。
        persist: True → 落 sessions/sub-<id>.jsonl 可观测。
        parent_session_id: 派发者 session (溯源 · 落进子会话首行 meta)。
        initial_messages: 起始 messages · None → 单条 user_msg (默认)。
            (wish-48566053 · resume 续跑: 恢复的历史消息 + 新 user 指令)
        meta_extra: 额外元数据 (goal / whitelist 等) · 落进 _meta 首行 · 血缘可追溯。

    Returns:
        SubagentResult
    """
    from tool_loop import run_tool_loop

    sub_session_id = uuid.uuid4().hex[:12] if persist else None

    sys_prompt = system or ""
    if inject_budget_mandate:
        sys_prompt = sys_prompt + _budget_mandate(max_iterations)

    if max_tokens is None:
        try:
            from daemon_runtime import bg_max_tokens
            max_tokens = bg_max_tokens()
        except Exception:
            max_tokens = 4096
    used_model = model or getattr(runtime, "model", "")
    try:
        from provider_presets import safe_max_tokens as _smt
        max_tokens = _smt(max_tokens, used_model)
    except Exception:
        pass

    messages: list[dict] = list(initial_messages) if initial_messages else [{"role": "user", "content": user_msg}]
    initial_len = len(messages)

    on_commit = None
    if persist and sub_session_id:
        on_commit = _make_commit_writer(sub_session_id)
        try:
            on_commit({
                "role": "_meta", "sub_session_id": sub_session_id,
                "parent_session_id": parent_session_id,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "model": used_model,  # wish-8ffb9d65 · 总监链路佐证 (查 sub session 知顾问真身)
                "system_preview": (system or "")[:200],
                "system_full": system or "",  # wish-48566053 · resume 需完整 system 重建上下文
                "extra_meta": meta_extra or {},  # goal / whitelist (血缘)
            })
        except Exception:
            pass

    try:
        text, messages, usage = run_tool_loop(
            client=client or runtime.client,
            provider=runtime.provider,
            model=used_model,
            max_tokens=max_tokens,
            system=sys_prompt,
            messages=messages,
            confirm=confirm or _auto_confirm,
            observe=_no_observe,
            max_iterations=max_iterations,
            base_url=getattr(runtime, "base_url", None),
            progress=progress,
            cancel_check=cancel_check,
            on_message_commit=on_commit,
            allowed_tool_names=tools_whitelist,
            wall_clock_sec=wall_clock_sec,
        )
    except Exception as e:
        return SubagentResult(
            ok=False, max_iterations=max_iterations,
            sub_session_id=sub_session_id,
            error=f"{type(e).__name__}: {e}",
        )

    result_usage = {
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "cache_read_tokens": getattr(usage, "cache_read_tokens", 0),
        "cache_creation_tokens": getattr(usage, "cache_creation_tokens", 0),
    }

    iterations = max(1, (len(messages) - initial_len + 1) // 2)
    hit_budget = iterations >= max_iterations
    near_budget = iterations >= max(1, max_iterations - 1) and not hit_budget
    warning = None
    if hit_budget:
        warning = (
            f"撞 max_iterations 上限 ({iterations}/{max_iterations}) · "
            f"子任务没在预算内出完整结论 · 输出可能不完整 · "
            f"考虑提高 max_iterations 或把任务拆更小"
        )
    elif near_budget:
        warning = f"接近预算上限 ({iterations}/{max_iterations}) · 下次注意 token 消耗"

    text = text or ""

    # wish 协同 (墨言子代理包 2026-08-10 · 撞顶保留产出) ·
    # 撞 max_iterations 时 tool_loop 返回的 text 是固定提示"撞了上限"· 分身已产出的中间文字
    # (边查边输出产生的) 被丢弃了。 现在: 从 messages 提取所有 assistant 正文拼进 text ·
    # 让预算耗尽也能拿到部分发现 —— 配合 dispatch 的"边查边输出"是一对: 一个负责写·一个负责捞。
    if hit_budget:
        _salvaged = []
        for _m in messages:
            _c = _m.get("content") if isinstance(_m, dict) else None
            if isinstance(_c, str) and _c.strip():
                # 只捞 assistant 的正文 · 且跳过 tool_loop 撞顶/卡死注入的固定提示块
                if _m.get("role") == "assistant" and not _c.startswith("[OPUS") and not _c.startswith("[SYSTEM"):
                    _salvaged.append(_c.strip())
        if _salvaged:
            _prev = text
            text = (
                "【预算耗尽 · 以下是从已产出内容中保留的部分发现 (可能不完整)】\n\n"
                + "\n\n".join(_salvaged[-3:])  # 最近 3 段 assistant 正文 (一般是中间结论+收尾)
            )
            warning = (
                f"撞 max_iterations 上限 ({iterations}/{max_iterations}) · "
                f"已从分身已产出内容中保留 {len(_salvaged)} 段中间结论 · "
                f"如需完整结论建议提高 max_iterations 或拆更小的子任务"
            )

    return SubagentResult(
        ok=True,
        text=text,
        outputs={"output": text},
        usage=result_usage,
        iterations=iterations,
        max_iterations=max_iterations,
        warning=warning,
        hit_budget=hit_budget,
        sub_session_id=sub_session_id,
        messages=messages,
        error=None,
    )
