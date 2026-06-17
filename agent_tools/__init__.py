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


# 触发各工具模块的 register_tool 调用
# 必须放在所有定义之后——子模块 import agent_tools 时要看见 ToolSpec/register_tool
from . import shell_exec       # noqa: E402,F401
from . import python_exec      # noqa: E402,F401  (续 · 消 78.6% inline -c 失败)
from . import read_file        # noqa: E402,F401
from . import write_file       # noqa: E402,F401
from . import edit_file        # noqa: E402,F401  ( · str_replace 局部替换 · 大文件不再整文件覆盖)
from . import outline_file     # noqa: E402,F401  (续 · 文件大纲 · 大文件改前先看骨架定位)
from . import lint_check       # noqa: E402,F401  (续 · lint 诊断 · 抓语法对逻辑错的 bug)
from . import search_code      # noqa: E402,F401  (续 · 语义代码搜索 · 按意思找·不靠猜正则)
from . import glob_files       # noqa: E402,F401  (续 · 按名字/通配找文件 · 补 Cursor Glob)
from . import grep_files       # noqa: E402,F401
# from . import set_model      # 停用 LLM 自主切模型(卷七十四续十四·防"切到当前 key 跑不了的模型→自锁死"·对齐业界·读图由 look_at 独立扛)·用户仍可在设置/终端 /model 手动切
from . import update_bro_note  # noqa: E402,F401
from . import set_emotion      # noqa: E402,F401
from . import web_search       # noqa: E402,F401
from . import web_fetch        # noqa: E402,F401
from . import take_screenshot  # noqa: E402,F401
from . import clipboard        # noqa: E402,F401
from . import open_app         # noqa: E402,F401
from . import browser_fetch    # noqa: E402,F401
from . import summarize_session  # noqa: E402,F401
from . import update_self_evolution  # noqa: E402,F401
from . import pdf_read         # noqa: E402,F401
from . import mcp_call         # noqa: E402,F401
# Daemonkey C1 · 不带项目档案 / Cursor 召唤 (模块文件未复制·见分家清单)
from . import wechat_send       # noqa: E402,F401  (微信渠道·官方 iLink·标配)
# from . import summon_cursor    # noqa: E402,F401
from . import ssh_remote       # noqa: E402,F401  (通用 SSH 运维)
# from . import client_handoff   # noqa: E402,F401  (项目客户档案·C2 剥离)
from . import manage_info_source  # noqa: E402,F401  ( · 工作室信息雷达源管理)
from . import generate_report     # noqa: E402,F401  ( · markdown→docx 文档生产)
from . import draft_studio        # noqa: E402,F401  ( · 内容/设计/开发/文档工坊)
from . import read_dashboard      # noqa: E402,F401  ( · OPUS 对话里读看板)
from . import propose_next_move   # noqa: E402,F401  ( · 基于画像给方向建议)
from . import expand_trend_to_report  # noqa: E402,F401  ( · 趋势→报告 一键链路)
from . import mine_opportunities  # noqa: E402,F401  ( · 掘金机会引擎)
from . import analyze_feasibility  # noqa: E402,F401  ( · 可行性分析)
from . import record_outcome       # noqa: E402,F401  ( · 闭环反馈)
from . import tag_radar_item       # noqa: E402,F401  ( · 雷达条目打标)
from . import init_domain          # noqa: E402,F401  ( · 一句话建领域)
from . import remove_domain        # noqa: E402,F401  (补丁 · 删领域)
from . import toggle_favorite      # noqa: E402,F401  ( · 统一收藏)
from . import auto_pipeline        # noqa: E402,F401  ( · 自主巡航)
from . import wish_add             # noqa: E402,F401  ( · OPUS 自我演化心愿单)
from . import wish_update          # noqa: E402,F401  ( · 心愿状态机)
from . import intent_to_wish       # noqa: E402,F401  ( G · 模糊请求→wish 草稿)
from . import verify_claim         # noqa: E402,F401  (补丁3 · 事实较量/单条 claim 验证)
from . import recall_memory        # noqa: E402,F401  ( · SQLite FTS5 跨会话记忆检索)
from . import mirror_capability    # noqa: E402,F401  ( · 市场能力镜像)
from . import extract_playbook  # noqa: E402,F401  ( · playbook 系统)
from . import create_app           # noqa: E402,F401  ( K stage 2c · 工坊造 app)
from . import update_app           # noqa: E402,F401  (续 12 · wish-165ea1f6 · 改 app 字段 + 补 ui_form_schema)
from . import create_workflow      # noqa: E402,F401  ( K stage 2c · 工坊造 workflow)
from . import app_set_secret       # noqa: E402,F401  ( K stage 2c++ · KEY 安全存 wish-96ee1b52)
from . import app_list_secrets     # noqa: E402,F401  ( K stage 2c++ · 列 secret 字段名)
from . import app_delete_secret    # noqa: E402,F401  ( K stage 2c++ · 删 secret)
from . import add_iron_rule        # noqa: E402,F401  ( K stage 2c++ · 铁律自动双写 wish-a72b2f0a)
from . import list_iron_rules      # noqa: E402,F401  ( K stage 2c++ · 列现有铁律)
from . import delete_app_to_trash  # noqa: E402,F401  ( K stage 2c++ · wish-6fd76512 · app 软删)
from . import restore_app          # noqa: E402,F401  ( K stage 2c++ · wish-6fd76512 · 回收站恢复)
from . import empty_trash          # noqa: E402,F401  ( K stage 2c++ · wish-6fd76512 · 永久删除)
from . import web_search_image     # noqa: E402,F401  ( K stage 2c++ · wish-4f25c4a1 · OPUS 给 用户 找图)
from . import service_start        # noqa: E402,F401  ( K stage 2c++ · wish-8d6b76a6 · 启长跑后台服务 detached)
from . import service_list         # noqa: E402,F401  ( K stage 2c++ · wish-8d6b76a6 · 列所有 service)
from . import service_status       # noqa: E402,F401  ( K stage 2c++ · wish-8d6b76a6 · 查单个 service 活+资源)
from . import service_stop         # noqa: E402,F401  ( K stage 2c++ · wish-8d6b76a6 · 停 service)
from . import monthly_review       # noqa: E402,F401  ( II · wish-bf190d9c · 月度复盘)
from . import read_scenario        # noqa: E402,F401  ( II · wish-af1245d7 · 按需读场景铁律)
from . import session_search       # noqa: E402,F401  ( II · wish-2a92774d · session 聚合搜索)
from . import request_restart      # noqa: E402,F401  ( III · wish-ed5553d5 · daemon 重启工具)
from . import verify_daemon_endpoints  # noqa: E402,F401  ( III · wish-ed5553d5 · daemon 路由冒烟)
from . import look_at              # noqa: E402,F401  ( III · wish-4a6331b2 · OPUS 的"眼睛")
from . import update_core          # noqa: E402,F401  (选择性内核升级 · 只覆盖白名单·不碰灵魂)
from . import manage_app_asset     # noqa: E402,F401  (app 资产登记表 · 用户个性沉淀单一事实源)
from . import run_app              # noqa: E402,F401  (主对话直接执行工坊 app · 先查再搓)
from . import run_flow             # noqa: E402,F401  (沿 steps 工作流执行 · 状态落盘断点续跑)
from . import app_versions         # noqa: E402,F401  (app 历史版本 list/show/diff/rollback)
from . import list_apps            # noqa: E402,F401  (列工坊 app · 补 glob 看不到的盲区)
from . import list_flows           # noqa: E402,F401  (列工坊 flow · 补 glob 看不到的盲区)
from . import trust_flow           # noqa: E402,F401  (0.2.0 · 信任账本手动控制 · 用户一句话信任)
from . import rerun_flow_step      # noqa: E402,F401  (0.2.0 · 单步重跑 · 用户主动要求)
