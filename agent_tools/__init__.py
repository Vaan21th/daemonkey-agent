"""
agent_tools/
============

OPUS 在 tool use 循环里调用的"器官"——每个工具一个 .py 文件。

设计原则：
  1. **协议无关**：每个工具只关心自己的输入输出，不知道 Anthropic / OpenAI 的 schema 长什么样。
     翻译由 tool_loop.py 在出门前做。
  2. **三档信任**：每个 ToolSpec 必须声明 tier（auto / confirm / guard）。
     上层 daemon 根据 tier 决定怎么和 用户 互动。详见 .cursor/SELF-EVOLUTION.md 协作宪章。
     如果工具的实际危险等级取决于 args（比如 shell_exec：跑 git status 是 auto，跑 rm -rf 是 guard），
     就实现 classify(args) 让 daemon 用动态判断覆盖 spec.tier。
  3. **失败不抛 exception**：返回 ToolResult(ok=False, error=...)。让 LLM 看见错误信息再决定怎么办。

加新工具：
  在 agent_tools/ 下加一个 .py，import register_tool 装饰一个函数，然后在 __init__.py 末尾
  加一行 `from . import your_module` 触发注册。
"""

from __future__ import annotations

import contextvars
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


TIER_AUTO = "auto"
TIER_CONFIRM = "confirm"
TIER_GUARD = "guard"


# ──  · wish-f30d571d · 工具进度钩子 ────────────────────────────
# tool_loop 在执行 spec.run(args) 前向 ContextVar 写入 push_progress(step, msg)
# 回调，长跑工具 (如 auto_pipeline) 在步骤之间调 push_tool_progress() 推送进度
# 到 SSE。ContextVar 线程内传递 · 不改任何 _run 签名 · 零侵入。
_TOOL_PROGRESS_HOOK: contextvars.ContextVar[Optional[Callable[[str, str], None]]] = \
    contextvars.ContextVar("_tool_progress_hook", default=None)


def push_tool_progress(step: str, msg: str = "") -> None:
    """工具内部调这个函数推送进度到 SSE。不在 tool_loop 内时静默跳过。
    
    Args:
        step: 短步骤名 · 给进度条显示 (如 '📡 抓取雷达' / '🌊 提炼趋势')
        msg: 额外细节 (如 '17/17 源 OK' / 'LLM 思考中…')
    """
    hook = _TOOL_PROGRESS_HOOK.get()
    if hook is not None:
        try:
            hook(step, msg)
        except Exception:
            pass
# ────────────────────────────────────────────────────────────────────────


# ── 编辑并发软锁 · session 身份 ─────────────────────────────────────────
# daemon 单进程多会话(多 WebUI 标签/续场/终端)。编辑锁(_edit_lock.py)要区分"哪个
# 对话在改这个文件"·靠的就是 session id。 daemon_api._chat_impl 在进入每个 /chat 前
# 调 set_session_context(sid) 写进这个 ContextVar(同 ContextVar 范式·跟随当前执行上
# 下文进到 spec.run → edit_file/write_file·零侵入·不改 run 签名)。
# 拿不到 sid 的路径(终端 REPL / 主动唤醒 / 并行只读工作线程)退化到线程 id —— 对"同时
# 改同一文件"的并发检测一样够用。
_SESSION_CTX: contextvars.ContextVar[Optional[str]] = \
    contextvars.ContextVar("_session_ctx", default=None)


def set_session_context(session_id: Optional[str]) -> None:
    """daemon 每轮 /chat 入口调它 · 把当前对话身份写进 ContextVar。"""
    _SESSION_CTX.set(session_id or None)


def current_session_id() -> str:
    """拿当前对话身份(编辑锁 owner)。 没设过 → 退化到线程 id。"""
    sid = _SESSION_CTX.get()
    if sid:
        return sid
    return f"t{threading.get_ident()}"


# ── 卷七十四续十五 · 本轮回复正文 ContextVar(两步法长文档生成兜底) ─────────────
# 痛点: DeepSeek 等模型 tool call 的长 JSON 参数(generate_report.body / write_file.content)
# 经常丢成空壳——它们写正文(普通文本流)是强项·丢的只是结构化长参数。
# 解法(只增不减): LLM 先把完整正文写在【回复正文】里(强项)·再调工具【不带 body/content】·
# 工具自动从这个 ContextVar 抓正文。 tool_loop 在执行每个工具前 set 进来(同 session/flow
# 范式·跟随执行上下文进 spec.run·零侵入·不改 run 签名)。
# 前沿模型(Claude/GPT)照旧直接传 body·根本不碰这条兜底·零影响。
_CURRENT_TURN_TEXT: contextvars.ContextVar[str] = \
    contextvars.ContextVar("_current_turn_text", default="")


def set_current_turn_text(text: str) -> None:
    """tool_loop 在执行每个工具前调它·把本轮 LLM 已写的回复正文暴露给工具。"""
    _CURRENT_TURN_TEXT.set(text or "")


def current_turn_text() -> str:
    """工具内部读 LLM 本轮已写的回复正文(两步法长文档兜底)。 没设过 → 空串。"""
    return _CURRENT_TURN_TEXT.get()
# ────────────────────────────────────────────────────────────────────────


# ── 0.2.0 · 信任 flow 上下文 (用户痛点: 跑过 OK 的 flow 不要次次问) ──
# agent_tools/run_flow.py 启动时检查 flow.trust_level ≥ 2 · 设这个 ContextVar 为 flow_id
# daemon 的 confirm callback 看到这个 ContextVar 不为空 · 对 CONFIRM tier 的工具直接返 "yes" ·
# 但 GUARD 仍走原流程 (保命线)。
# 设计原则:
#   - 只覆盖 CONFIRM · GUARD 永远要用户拍 (rm -rf / drop / 改 .env 之类)
#   - 用 ContextVar 而非全局变量 · 多会话并发安全
#   - 设了之后由调用方在结束时 reset · 避免泄露到其他 task
_TRUSTED_FLOW_CTX: contextvars.ContextVar[Optional[str]] = \
    contextvars.ContextVar("_trusted_flow_ctx", default=None)


def set_trusted_flow_context(flow_id: Optional[str]) -> contextvars.Token:
    """run_flow 启动前调 · 返回 Token · 结束后调 reset_trusted_flow_context(token) 清回"""
    return _TRUSTED_FLOW_CTX.set(flow_id or None)


def reset_trusted_flow_context(token: contextvars.Token) -> None:
    """run_flow 结束时调 · 防泄露到下一个 task"""
    try:
        _TRUSTED_FLOW_CTX.reset(token)
    except Exception:
        pass


def current_trusted_flow() -> Optional[str]:
    """daemon confirm callback 调这个查 · 拿到 flow_id 说明现在在信任 flow 内部 · 可降级"""
    return _TRUSTED_FLOW_CTX.get()
# ────────────────────────────────────────────────────────────────────────


@dataclass
class ToolResult:
    ok: bool
    output: str
    truncated: bool = False
    error: Optional[str] = None

    def to_string(self, max_chars: int = 8000) -> str:
        if not self.ok:
            return f"[TOOL ERROR] {self.error or 'unknown error'}\n\n{self.output}"[:max_chars]
        text = self.output
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n... [truncated {len(self.output) - max_chars} more chars]"
        elif self.truncated:
            text = text + "\n\n... [output already truncated by tool]"
        return text


@dataclass
class ToolSpec:
    name: str
    description: str
    tier: str  # static fallback tier
    input_schema: dict
    run: Callable[[dict], ToolResult]
    summarize: Callable[[dict], str]  # 给 用户 看的"我打算怎么做"摘要
    # 如果给定 args 后真实的 tier 应该不一样（比如 shell_exec），就实现这个
    classify: Optional[Callable[[dict], str]] = None

    def effective_tier(self, args: dict) -> str:
        if self.classify is not None:
            try:
                t = self.classify(args)
                if t in (TIER_AUTO, TIER_CONFIRM, TIER_GUARD):
                    return t
            except Exception:
                pass
        return self.tier


REGISTRY: dict[str, ToolSpec] = {}


def register_tool(spec: ToolSpec) -> ToolSpec:
    if spec.name in REGISTRY:
        raise ValueError(f"tool name conflict: {spec.name}")
    if spec.tier not in (TIER_AUTO, TIER_CONFIRM, TIER_GUARD):
        raise ValueError(f"invalid tier: {spec.tier}")
    REGISTRY[spec.name] = spec
    return spec


# ── 工具自动发现 (drop-in 即注册 · 替代手写 from . import X 长列表) ──
# 扫描本包内所有工具模块·import 触发各自的 register_tool。
#   - 加新工具: 丢个 .py 进来即生效·不用再来这里加一行 (update_core 下发即激活)
#   - 剥离工具: 物理删 .py 即可·扫不到就不注册 (两库这段逐字一致·不靠注释 import 分叉)
#   - _OPT_OUT: 文件保留但故意不激活的工具 (唯一需显式排除的)
import importlib as _importlib
import pkgutil as _pkgutil

_OPT_OUT = {
    "set_model",  # 停用 LLM 自主切模型 (防"切到当前 key 跑不了的模型 -> 自锁死"; 用户仍可手动 /model 切)
}

_discovery_failures = []
for _mod in _pkgutil.iter_modules(__path__):
    _name = _mod.name
    if _name.startswith("_") or _name in _OPT_OUT:
        continue  # 下划线=辅助模块(无 SPEC) · _OPT_OUT=故意停用
    try:
        _importlib.import_module(f"{__name__}.{_name}")
    except Exception as _e:  # 单模块失败不拖垮整包(某工具缺依赖->跳过·其余照常注册)
        _discovery_failures.append((_name, f"{type(_e).__name__}: {_e}"))

if _discovery_failures:
    import sys as _sys
    for _n, _err in _discovery_failures:
        print(f"[agent_tools] WARN · 工具模块 {_n} 加载失败 (跳过·不影响其余): {_err}",
              file=_sys.stderr, flush=True)
