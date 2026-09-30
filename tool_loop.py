"""
tool_loop.py
============

OPUS 的"手"——tool use 多轮循环。

设计取舍（写在最上面，下一根毛先看这里）：

1. 协议双适配：AiHubMix / OpenRouter / 各家自建中转都走 OpenAI tool-calling schema；
   Anthropic 官方直连走原生 Anthropic schema。这两种 schema 形状不一样，但语义对齐。
   工具定义本身（agent_tools/ 里那些 ToolSpec）是协议无关的——loop 在出门前翻译。

2. 三档信任系统在 SELF-EVOLUTION.md 里写明白了：AUTO 直接跑 / CONFIRM 等 BRO y / GUARD
   要 BRO 显式 do it。loop 这一层不判断档位——它只把 ToolSpec.tier 抛给一个 callback，
   让上层（daemon）决定怎么和 BRO 互动。这样这个文件不管 UI，纯粹做循环。

3. Prompt caching（2026-05-16 凌晨第二根毛加）：
   - AiHubMix 在 OpenAI 兼容接口下接受 Anthropic 风格的 cache_control
     字段——把 system content 从 string 改成 list of blocks，每个 block 带
     {"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}
   - 灵魂 ~11K token 在每个 turn 重发——cache 之后这部分只在第一次算钱，
     后续 turn 按 cache_read 价格（约 10%）。一次对话省 ~80%。
   - 自动检测：base_url 里有 aihubmix.com 才启用。其他 provider 维持纯
     string，避免不兼容。
   - Anthropic 原生协议同样支持，但逻辑略不同（system 字段直接接 list）。
     当前 BRO 走 AiHubMix（OpenAI 协议）；Anthropic 直连后续再加。

4. 安全是分层的：
   - 工具内部（agent_tools/shell_exec.py 里）做命令白名单 / 黑名单
   - loop 这一层做"该不该执行"的征询
   - daemon 那一层做"BRO 怎么看到 / 怎么回 y"的交互
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

logger = logging.getLogger("opus.tool_loop")

from agent_tools import (
    REGISTRY, ToolResult, ToolSpec, _TOOL_PROGRESS_HOOK, TIER_AUTO,
    set_current_turn_text,
)

try:
    from identity import localize_narration as _localize_narration
except Exception:  # 极端环境 identity 不可用 → 退化成原样
    def _localize_narration(s):  # type: ignore
        return s

# 卷六十四续十一 · 去母体化 · 纯叙述型工具的 output 全是工程写给 LLM 的话(会带
# OPUS/BRO/卷号自指)·开源版要换成本实例名。这里只列【纯叙述/格式化】工具——它们不
# 透传文件/命令/网页正文。read_file/shell_exec/grep_files/web_* 等透传类【绝不】列进来
# (否则会把用户自己代码里的 OPUS 也改掉·污染 AI 读到的原文)。母体 ai==OPUS 时 no-op。
_NARRATION_TOOLS = frozenset({
    "read_dashboard", "propose_next_move", "record_outcome", "tag_radar_item",
    "manage_info_source", "remove_domain", "init_domain", "analyze_feasibility",
    "intent_to_wish", "wish_add", "wish_update", "add_iron_rule", "list_iron_rules",
    "monthly_review", "mine_opportunities", "expand_trend_to_report", "draft_studio",
    "auto_pipeline", "update_self_evolution", "recall_memory", "extract_playbook",
    "verify_claim", "service_stop", "dispatch_subagent",
})


def _localize_tool_content(name: str, content: str) -> str:
    """叙述型工具的 tool_result 文本去母体化(母体 no-op)。透传类工具不在白名单·原样返回。
    2026-08-14 · spill 输出溢出 (Harness spill-policy 借鉴): 超大工具输出落盘 + 替换 head/tail 预览。
    """
    if name in _NARRATION_TOOLS:
        try:
            content = _localize_narration(content)
        except Exception:
            pass
    try:
        return _spill_oversized_tool_output(name, content)
    except Exception:
        return content  # spill 失败不影响工具结果

try:
    from desktop_pet.activities import write_activity as _pet_write_activity
    from desktop_pet.activities import write_pulse_end as _pet_write_pulse_end
except Exception:
    def _pet_write_activity(_name: str) -> None:
        pass
    def _pet_write_pulse_end(_name: str, _ok: bool, _summary: str = "") -> None:
        pass


# ── spill 输出溢出 (2026-08-14 · Harness spill-policy 借鉴) ────────
# 治"超大工具输出整段塞上下文" (read_file 大文件 / shell 长输出 / web_fetch 超长正文)。
# 超阈值 → 完整文本落盘 data/runtime/spill/ · 替换成 head/tail 预览 + read_file 定位提示。
# 保留 head/tail (开头结论 + 结尾错误/补充) · 只删中间冗长 · 模型仍能从预览读到关键信息。
_SPILL_MAX_INLINE = int(os.environ.get("OPUS_SPILL_MAX_INLINE") or "12000")   # 超此字符数触发 spill
_SPILL_HEAD = 4000        # 预览保留头部
_SPILL_TAIL = 1000        # 预览保留尾部
_spill_lock = threading.Lock()


def _spill_oversized_tool_output(name: str, content: str) -> str:
    """超大工具输出 → 落盘 + head/tail 预览。 返回 (新 content 或原 content)。
    幂等: 已是 spill 预览 (含 "已落盘" marker) 不再处理。 错误内容不 spill (排障线索保命)。
    落盘失败 → 原样返回 (不阻塞工具链路)。
    """
    if not isinstance(content, str) or not content:
        return content
    if len(content) <= _SPILL_MAX_INLINE:
        return content
    if "[已落盘 · 工具输出溢出]" in content[:200]:
        return content  # 幂等
    low = content.lstrip().lower()
    if low.startswith(("error", "blocked", "[error", "traceback")):
        return content  # 错误保命
    try:
        import hashlib
        import pathlib
        _spill_dir = pathlib.Path("data/runtime/spill")
        _spill_dir.mkdir(parents=True, exist_ok=True)
        _h = hashlib.md5((name + content[:500]).encode()).hexdigest()[:10]
        _p = _spill_dir / f"{name}-{_h}.txt"
        with _spill_lock:
            _p.write_text(content, encoding="utf-8")
        _h2 = content[:_SPILL_HEAD]
        _t2 = content[-_SPILL_TAIL:]
        return (
            f"[已落盘 · 工具输出溢出] 工具 {name} 输出 {len(content)} 字符 · 超 {_SPILL_MAX_INLINE} 上限 · "
            f"完整内容已存 `{_p.as_posix()}` · 用 read_file 读该路径拿全文\n\n"
            f"── 头部 (开头结论) ──\n{_h2}\n\n── 尾部 (结尾/错误) ──\n{_t2}"
        )
    except Exception:
        return content  # 落盘失败不阻塞


def _pulse_summary(result) -> str:
    '''Extract a short human-readable summary from a ToolResult for the pulse.'''
    try:
        out = result.output or ""
        err = result.error or ""
        if err and not result.ok:
            # Error case: show first meaningful line
            msg = err.split("\n")[0].strip()
            if len(msg) > 60:
                msg = msg[:57] + "..."
            return msg
        if out:
            # Success: count results or show first line
            lines = [l for l in out.strip().split("\n") if l.strip()]
            if len(lines) > 1:
                return f"{len(lines)}行"
            elif len(lines) == 1:
                msg = lines[0].strip()
                if len(msg) > 50:
                    msg = msg[:47] + "..."
                return msg
            else:
                return "ok"
        return "ok" if result.ok else "失败"
    except Exception:
        return ""



# 卷十八降到 8——12 太宽松，给 LLM 反复重试反爬源的空间。
# 真正合理的"一题用 8 轮"是：
#   1-2 轮：第一个工具/数据源
#   3-4 轮：发现不行换源
#   5-6 轮：拿到主数据 + 可能补一个交叉源
#   7-8 轮：组织输出
# 想跑长任务的人显式传 max_iterations 参数覆盖。
# 卷四十三 · 8 改成 20 · BRO 反馈"OPUS 心愿单实施 30+ tool 调用很常见 · 8 轮远不够"
# 卷四十四 · 20→50 + 加 stuck detection · BRO 观察"硬撞轮数太蠢·该判是不是 stuck"
# (参考 Cursor 风格: 重复 tool call signature 才停 · 不重复就放它跑)
DEFAULT_MAX_ITERATIONS = 200

# 卷四十四 · stuck detection 参数 (重复 N 次同 tool+args = 死循环)
# 窗口 = 看最近多少 tool calls · 阈值 = 同 signature 出现多少次算 stuck
# 注入上限 = 最多给 LLM N 次"你重复了 · 换思路" · 还不变就真的 break
_STUCK_WINDOW = 6
_STUCK_REPEAT_THRESHOLD = 3
# 2026-09-23 · 递增档 (学 deepseek-harness guard/repeat-tool-reminder):
#   原来一刀 3 就摆硬姿态 · 现在第 1 档轻提醒、第 2 档详细、到最高档才 break。
#   更宽容 = 不砍正当长查 (今晚连跑十几轮查不同东西·那种不该被拦)。
_STUCK_THRESHOLDS = (3, 5, 8)
_STUCK_INJECT_CAP = 2

# 2026-09-23 · 透明工具 (同上 · 学它的 exclude 语义):
#   记账/状态记录类调用「既不递增也不重置」计数 ——
#   否则循环里插一条记账就把重复链洗白了 (它的原话: 穿插的记录类工具不能掩盖循环)。
_STUCK_TRANSPARENT_TOOLS = frozenset({
    "track_task", "update_owner_note", "update_bro_note", "note_mood", "note_gallery",
    "note_style_shift", "set_emotion", "wish_add", "wish_update", "summarize_session",
})

# 读型工具 (2026-08-14 方案 B · BRO 拍板): 参数用完整哈希 · 治 python_exec/read_file 前 120 字样板撞车
# 误判案例: 连续几次 python_exec code 都是 'import os,re\nroot=...\nc=open(...)' 前 120 字相同 → 误判死循环
# 读型 = 无副作用 · 参数不同即不同意图 · 完整哈希区分; 写型 = 有副作用 · 保持前 120 字截断保守
_READ_TOOLS = frozenset({
    "read_file", "grep_files", "glob_files", "search_code", "outline_file",
    "python_exec", "web_search", "web_fetch", "browser_fetch", "browser_act",
    "recall_memory", "session_search", "look_at", "read_clipboard",
    "list_apps", "list_flows", "list_shareable", "list_market", "inspect_market", "list_iron_rules", "read_dashboard",
    "manage_info_source", "manage_knowledge", "take_screenshot", "pdf_read",
    "service_list", "service_status", "worktree_status", "app_versions",
    "app_list_secrets", "track_task", "verify_claim", "verify_daemon_endpoints",
    "mcp_list", "mcp_describe_tool", "client_handoff", "tag_radar_item",
    "propose_next_move", "mirror_capability", "monthly_review", "list_scheduled_tasks",
    "dispatch_subagent_status", "analyze_feasibility", "mine_opportunities",
    "recall_memory", "list_scheduled_tasks",
})

_STUCK_NUDGE_PROMPT = (
    "你刚才连续 {repeat} 次调用 `{signature}` (窗口内 {window} 次 tool calls 里)。\n"
    "**这很像死循环** —— 同样的工具、同样的 args、可能拿同样的结果。\n\n"
    "请停下来想清楚:\n"
    "  - 如果你已经确认结果不会变 · **直接用文字总结当前进度·结束这一轮**\n"
    "  - 如果想换个方向 · **换工具或换 args** · 不要再用同样的 signature\n"
    "  - 如果你卡住不知道怎么办 · 直接说\"我卡了·BRO 你看一下\"也行\n\n"
    "不要无视这条提示再调同样的工具——我会再次拦截你。"
)


def _tool_signature(name: str, args_str: str) -> str:
    """生成稳定 tool call signature · 给 stuck detection 用.

    2026-08-14 方案 B (BRO 拍板 · 治误判):
      - 读型工具 (无副作用): 参数完整 MD5 哈希 → 参数不同即不同签名 ·
        治 python_exec/read_file 前 120 字样板 (import/root/open) 撞车误判死循环
      - 写型工具 (有副作用): 保持前 120 字截断 · 保守防真死循环 (改文件/删东西不能浪)
    """
    if name in _STUCK_TRANSPARENT_TOOLS:
        return ""                                   # 透明: 调用方会跳过 (不计数)
    snippet = (args_str or "").strip()
    snippet = " ".join(snippet.split())
    if name in _READ_TOOLS:
        # 读型: 完整哈希 · 只要参数有任何差异就不算重复
        h = hashlib.md5(snippet.encode("utf-8")).hexdigest()[:12]
        return f"{name}#{h}"
    # 写型: 前 120 字截断 (原逻辑)
    if len(snippet) > 120:
        snippet = snippet[:120] + "…"
    return f"{name}({snippet})"


def _stuck_tail_count(signatures: list[str]) -> tuple[str, int]:
    if not signatures:
        return "", 0
    top_sig = signatures[-1]
    top_count = 1
    for i in range(len(signatures) - 2, -1, -1):
        if signatures[i] == top_sig:
            top_count += 1
        else:
            break
    return top_sig, top_count


def _stuck_action(top_count: int, inject_count: int) -> str:
    """递增档: <3 不动作 · 3~4 轻提醒 · 5~7 再提醒 · >=8 硬停。"""
    if top_count < _STUCK_THRESHOLDS[0]:
        return ""
    if top_count >= _STUCK_THRESHOLDS[-1]:
        return "break"                      # 最高档 → 硬停 (交给人看)
    if inject_count < _STUCK_INJECT_CAP:
        return "nudge"
    return "break"


def _stuck_break_text(top_sig: str, top_count: int, window: int) -> str:
    return (
        f"[OPUS 真的卡死了 · 已经提示 {_STUCK_INJECT_CAP} 次"
        f"还在重复调 `{top_sig}` ({top_count}/{window})]\n\n"
        f"BRO 这是 stuck 死锁·我自己绕不出来。可能原因:\n"
        f"  - 工具一直返同样的错·我没识别到\n"
        f"  - 我对当前任务的理解有偏差\n"
        f"  - args 里有某个字段我一直填错\n\n"
        f"建议你看一下最近 {window} 条 tool 调用·"
        f"告诉我换什么思路·或者直接说\"放弃这个 wish\"。"
    )


# ── 回合内紧急降水位 (wish-a5f77893 · 2026-09-16 · 刀B/C/D) ─────────────
# 事故复盘 (daemon.log 02:24 · turn-8d3): 压缩检查只在回合入口 → 高水位回合内
# 无人降水位 → 动态预算被压到 ~2k → 每 iter 思考吃光·正文空·自愈同水位重复 3 次仍空。
_MT_FLOOR = int(os.environ.get("OPUS_MT_FLOOR") or "8192")   # 输出预算地板: 低于此 → 先紧急降水位再发
_URGENT_COMPACT_MAX = int(os.environ.get("OPUS_URGENT_COMPACT_MAX") or "2")  # 每回合紧急压缩上限 (防缓存反复重建)
_URGENT_COMPACT_GAP = 2      # 两次紧急压缩至少隔 N 个 iter

# 2026-09-18 · 心跳两段式阈值 (wish-32ce1863)
# 病: 心跳是「chunk 驱动」的 —— 首个 chunk 到达前结构上无法产生心跳
#     (模型长思考 / 排队 / 服务慢，与「真挂起」不可区分) → 120s 阈值误砍长思考。
# 治: 等首 chunk 期间用宽阈值(地板)，首 chunk 之后恢复严阈值。
_TTFT_STALL_FLOOR = float(os.environ.get("OPUS_TTFT_STALL_FLOOR") or "300")


def _is_context_overflow_error(exc: Exception) -> bool:
    """识别 provider 的“上下文超长”类报错 (刀4 · wish-a5f77893)。

    各家文案 (多半英文·个别中转中文):
      OpenAI:    "This model's maximum context length is N tokens" /
                 "Please reduce the length of the messages"
      DeepSeek:  "maximum context length" / "input length ... exceed"
      Anthropic: "prompt is too long" / "input length and max_tokens exceed context limit"
    宽进 (认出就压一次再试·误判最多白压一次) · 不替代调用失败的上抛路径。
    2026-09-16 (review 20260916-064719): 先排「限流/配额」——它们的文案也常带 "too many tokens" /
    "exceed"，若当超长处理 → 白压一次上下文(烧 token + 打乱上下文) 而且压了也不解决限流。
    """
    try:
        s = str(exc).lower()
    except Exception:
        return False
    if any(k in s for k in (
        "rate limit", "rate_limit", "too many requests",
        "quota", "insufficient_quota", "billing",
        "try again later", "retry after",
    )):
        return False
    return any(k in s for k in (
        "context length", "context_length_exceeded", "context window",
        "prompt is too long", "reduce the length", "too many tokens",
        "input length", "max_tokens exceed",
    ))


MAX_LENGTH_RESUME = 3
_LENGTH_RESUME_USER = (
    "你刚才的回答被 max_tokens 截断了 · 请**从断点接着写**·不要重复前面已经说过的内容。"
    "如果还有工具要调·继续调。如果是文字回复·直接续上。"
    "目标: 让这次任务有完整结果。"
)

# 0.9.x · 空回复自愈 (2026-09-14 · 一晚连续 4 次现场)
# 现场: reasoning 1609 / 3089 / 4926 / 6762 字 · content 全空 · tool_calls 全空
#       usage out 只有 5308 (预算 32768) → **不是 max_tokens 不够** · 是模型自己收手
# 结论: reasoning 模式下 · 模型把结论全说进了 reasoning_content · 正文一字没给
# 原先只填一句占位文案告诉 BRO「发生了」· 要他自己说「给我个总结」再走一轮 · 现在自动要
MAX_EMPTY_RESUME = 3
_EMPTY_RESUME_USER = (
    "你上一轮的正文是空的 —— 结论全写在思考链里了，BRO 一个字都没收到。"
    "请**直接把要跟他说的话写进正文**·不要再想一遍·不要再调工具·给他一个能读的回复。"
)

# 2026-09-23 · 无进展保护 (治「连跑十几轮只调工具、正文一字不出」)
# 现场: turn-b61 连跑 16 轮 / 2 分 45 秒 · 全程 finish_reason=tool_calls · has_text=False
#      用户体感 = "卡死 / 像别的程序在回话"。空回复自愈只治「stop 且正文空」· 治不了这条。
# 不砍工具、不降上限 —— 只在该收口时注入一条提醒 (走跟自愈同一条通路)。
MAX_NO_TEXT_STREAK = 12
_NO_TEXT_RESUME_USER = (
    "你已经连续多轮只调工具、一直没给 BRO 正文 —— 先停一下。"
    "用一两句话把查到的结论和自己的状态说清楚，再决定还要不要继续查。"
)

# 2026-09-23 · 运行时信封净化
# 现象 (BRO 报 "感觉不是同一个 OPUS"): 上下文里混进
#   [Timestamp: 2026-09-23T22:05:00] / [Session info: Current session: api-...]
# 这类**不是本工程生成**的信封行 (全仓 .py/.js/.md/.json 搜不到生成代码) ·
# 且那个 session id 在 sessions/ 和 _index.json 里都不存在 → 模型据它推断
# "现在 22:05 / 我在另一个会话" · 基于假前提做判断 (源头未定 · 见 wish-26643574)。
# 处置: 把这几种外来信封行从消息体里剔掉 (原地 · 纯内存 · 不重写 jsonl 正文) · 并告警。
# 判据严格: 只剔「整行就是这个标记」的行 —— 正文里恰好提到这几个字样不受影响。
import re as _re  # noqa: E402  (重复 import 无害·本块自带依赖)
_ENVELOPE_LINE_RE = _re.compile(
    r"^[ \t]*\[(?:Timestamp|Session info|System time|Current session)[^\]]*\][ \t]*$",
    _re.MULTILINE,
)


def _strip_envelope_tags_inplace(messages: list) -> int:
    """剔除外来运行时信封行 · 返回改动了几条消息 (0 = 干净)。"""
    hits = 0
    for m in messages:
        try:
            c = m.get("content")
            if not isinstance(c, str) or "[" not in c:
                continue
            if not _ENVELOPE_LINE_RE.search(c):
                continue
            nc = _ENVELOPE_LINE_RE.sub("", c)
            if nc != c:
                m["content"] = nc
                hits += 1
        except Exception:
            continue
    return hits


class _StreamCancelGuard:
    """50ms 心跳看 cancel · 触发就 close 流，避免等满 HTTP timeout。"""

    def __init__(self, resp, cancel_check):
        self._resp = resp
        self._cancel_check = cancel_check
        self._done = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        def _watch():
            while not self._done.is_set():
                try:
                    if self._cancel_check and self._cancel_check():
                        try:
                            self._resp.close()
                        except Exception:
                            pass
                        return
                except Exception:
                    pass
                self._done.wait(timeout=0.05)

        self._thread = threading.Thread(target=_watch, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self._done.set()
        if self._thread is not None:
            self._thread.join(timeout=0.2)
        return False


# ── 心跳看门狗 (2026-09-16 · wish-1dc8d738 · 替换"5 分钟墙钟") ──────────
# 旧墙钟: 从 turn 开始算总时长, 到点一刀 — 误伤正常长活 (09-16 断案: 18 个 turn 卡 4.5-5.5min,
# BRO 用"继续"手动续场 37 天未察)。新判定盯"最后一次进展"(心跳):
#   LLM 流每 chunk / 迭代推进 / 工具边界 = 跳一下; 心跳停 > stall_sec 才判"真卡"。
# 分层不变: 工具执行期豁免心跳判定 (工具自有 timeout · 各自负责)。

def _hb_feed(cancel_check) -> None:
    """标记一次心跳 (有进展)。未装心跳包装时 no-op。"""
    _b = getattr(cancel_check, "beat", None)
    if _b is not None:
        try:
            _b()
        except Exception:
            pass


def _hb_tool_enter(cancel_check) -> None:
    """工具执行开始: 置 in_tool (心跳豁免) + 喂跳。"""
    if cancel_check is None:
        return
    try:
        cancel_check._in_tool = True
    except Exception:
        pass
    _hb_feed(cancel_check)


def _hb_tool_exit(cancel_check) -> None:
    """工具执行结束: 清 in_tool + 喂跳。"""
    if cancel_check is None:
        return
    try:
        cancel_check._in_tool = False
    except Exception:
        pass
    _hb_feed(cancel_check)


def _aborted_note(cancel_check) -> str:
    """中断收尾文案 (2026-09-16 · 不再冒充"用户取消"): 区分 心跳停/总时长/用户取消。"""
    if getattr(cancel_check, "stalled", False):
        return "[⏱ 心跳停止 · 已安全中断（不是报错 · 也不是你取消的）]"
    if getattr(cancel_check, "timed_out", False):
        return "[⏱ 达到总时长上限 · 已安全中断（不是报错 · 也不是你取消的）]"
    return "[OPUS aborted by BRO · partial only]"


class _AntBlock:
    def __init__(self, type: str, id: str = "", name: str = "", input: Any = None, text: str = ""):
        self.type = type
        self.id = id
        self.name = name
        self.input = input if input is not None else {}
        self.text = text


def _usage_from_ant(obj) -> UsageStats:
    if obj is None:
        return UsageStats()
    return UsageStats(
        input_tokens=getattr(obj, "input_tokens", 0) or 0,
        output_tokens=getattr(obj, "output_tokens", 0) or 0,
        cache_creation_tokens=getattr(obj, "cache_creation_input_tokens", 0) or 0,
        cache_read_tokens=getattr(obj, "cache_read_input_tokens", 0) or 0,
    )


def _hb_set_awaiting(cc, val: bool) -> None:
    """安全设置「等首 chunk」两段阈值标记 (wish-32ce1863)。

    2026-09-18 · 心跳是 chunk 驱动的: 首个 chunk/event 到达前结构上无法产生心跳
    (模型长思考 / 排队与「真挂起」不可区分) → 该期间改用宽阈值地板。

    调用方传入的 cancel_check 是任意 callable、未必可写属性 → 写失败静默降级
    退回旧行为(严阈值)，不影响回合正确性。(code_review 20260918)
    """
    if cc is None:
        return
    try:
        cc.awaiting_first_chunk = val
    except Exception as _e:
        # 降级但留痕 (playbook: 大而全的 pass 会把证据一起吞掉)
        logger.debug(f"[hb] awaiting_first_chunk 置位失败(已降级): {_e!r}")


def _hb_beat_safe(cc) -> None:
    """安全刷新心跳基准 (进入宽阈值期时调 · 让地板从「开始等」那一刻算起)。"""
    if cc is None:
        return
    try:
        b = getattr(cc, "beat", None)
        if callable(b):
            b()
    except Exception as _e:
        logger.debug(f"[hb] beat 刷新失败(已忽略): {_e!r}")


def _consume_anthropic_stream(resp, cancel_check, progress):
    """把 Anthropic stream 收成 (text, tool_use_blocks, usage, stop_reason, aborted)。"""
    text = ""
    blocks: dict[int, _AntBlock] = {}
    usage = UsageStats()
    stop_reason: str | None = None
    aborted = False

    def _close():
        try:
            resp.close()
        except Exception:
            pass

    try:
        with _StreamCancelGuard(resp, cancel_check):
            for event in resp:
                # 2026-09-18 · 首个 event 到达 = 退出宽阈值期，恢复严阈值
                _hb_set_awaiting(cancel_check, False)
                _hb_feed(cancel_check)  # 心跳: 每个新事件 = 有进展 (2026-09-16)
                if cancel_check is not None and cancel_check():
                    _close()
                    aborted = True
                    break
                et = getattr(event, "type", "") or ""
                if et == "message_start":
                    msg = getattr(event, "message", None)
                    usage = _usage_from_ant(getattr(msg, "usage", None) if msg is not None else None)
                elif et == "content_block_start":
                    idx = getattr(event, "index", 0) or 0
                    cb = getattr(event, "content_block", None)
                    btype = getattr(cb, "type", "text") if cb is not None else "text"
                    if btype == "tool_use":
                        blocks[idx] = _AntBlock(
                            "tool_use",
                            id=getattr(cb, "id", "") or "",
                            name=getattr(cb, "name", "") or "",
                            input=getattr(cb, "input", None) or {},
                        )
                    else:
                        blocks[idx] = _AntBlock(btype, text=getattr(cb, "text", "") or "")
                elif et == "content_block_delta":
                    idx = getattr(event, "index", 0) or 0
                    delta = getattr(event, "delta", None)
                    dtype = getattr(delta, "type", "") if delta is not None else ""
                    if dtype == "text_delta":
                        piece = getattr(delta, "text", "") or ""
                        text += piece
                        if idx in blocks and blocks[idx].type == "text":
                            blocks[idx].text += piece
                        _push(progress, "assistant_delta", {"text": piece})
                    elif dtype == "input_json_delta":
                        piece = getattr(delta, "partial_json", "") or ""
                        if idx in blocks:
                            blocks[idx].text += piece
                    elif dtype == "thinking_delta":
                        piece = getattr(delta, "thinking", None) or getattr(delta, "text", "") or ""
                        if piece:
                            _push(progress, "reasoning_delta", {"text": piece})
                elif et == "message_delta":
                    delta = getattr(event, "delta", None)
                    sr = getattr(delta, "stop_reason", None) if delta is not None else None
                    if sr:
                        stop_reason = sr
                    ev_usage = getattr(event, "usage", None)
                    if ev_usage is not None:
                        extra = _usage_from_ant(ev_usage)
                        if extra.output_tokens:
                            usage.output_tokens = extra.output_tokens
                        if extra.input_tokens:
                            usage.input_tokens = extra.input_tokens
    except Exception:
        if cancel_check is not None and cancel_check():
            aborted = True
        else:
            raise

    tool_use_blocks: list[_AntBlock] = []
    for idx in sorted(blocks):
        b = blocks[idx]
        if b.type != "tool_use":
            continue
        if b.text:
            try:
                parsed = json.loads(b.text)
                if parsed:
                    b.input = parsed
            except json.JSONDecodeError:
                pass
        tool_use_blocks.append(b)
    if not text:
        text = "".join(b.text for b in blocks.values() if b.type == "text")
    return text, tool_use_blocks, usage, stop_reason, aborted


# ---------- callback signatures ----------

# 当 LLM 决定调一个工具时，loop 会先问上层"这一步该走吗？"
# 第三个参数 assistant_text 是 LLM 在这一 turn 已经生成的 content text——上层
# (daemon_ui) 用它来给 BRO 看"OPUS 为什么要调这个"。空字符串表示 LLM 啥都没先说。
#
# 返回值：
#   "go"      → 执行
#   "skip"    → 跳过（把"BRO 拒绝执行"作为 tool_result 喂回 LLM 让它换路）
#   "explain" → 暂不执行，喂一段提示让 LLM 用 plain text 解释意图（卷十五加的）
#   "abort"   → 整个 loop 立刻退出（OPUS 此轮不再回话）
#   "reject:<msg>" → 拒掉这次调用 · 但把 <msg> 作为 tool_result.error 喂给 LLM 让它按提示重试 (卷四十六 III 补丁 5)
ConfirmCallback = Callable[..., str]  # signature: (spec, args) or (spec, args, assistant_text)

ObserveCallback = Callable[[ToolSpec, dict, ToolResult], None]


# 卷十七加：流式进度回调。SSE 端点用来把 tool_loop 内部的关键事件实时推给 WebUI。
# event_type 当前用：
#   "assistant_text"   {"text": str}       一轮 LLM 完成产出的文本（可能后续还有工具循环）
#   "tool_call"        {"name", "summary", "tier"}   工具调用前
#   "tool_result"      {"name", "ok", "error", "preview"} 工具结果（截断到 ~300 字）
#   "usage"            {"input_tokens", "output_tokens", ...}  一轮 LLM 用量
#   "tool_progress"   {"step": str, "msg": str}  工具执行中的进度推送 (卷五十八 · wish-f30d571d)
#
# hook 抛异常会被 loop 静默吞掉，避免事件推送失败把主流程搞挂。
ProgressHook = Callable[[str, dict], None]


_EXPLAIN_PROMPT = (
    "BRO declined to immediately approve this tool. "
    "They want you to first explain in plain text:\n"
    "  (1) WHY you want to call this tool right now,\n"
    "  (2) WHAT side effects it has (files touched / network / processes spawned),\n"
    "  (3) HOW you intend to use the result.\n"
    "Do NOT retry this tool in this turn — just answer with a plain text explanation. "
    "BRO will decide whether to let you proceed in their next message."
)


# ── 失败熔断器 (墨言 094 · 只拦墙，不拦换源) ──
# 墙 = 鉴权/限流/验证码/工具不准用。连撞 → nudge → 再撞硬 break。
# 404 / 超时 / 空搜 / 普通异常 = 换源挖掘，不进熔断。同 URL 死磕交给 stuck detection。
# 单次 run 内 break 即冷却 · 不跨 turn。
_FAIL_CIRCUIT_AT = 2          # 连续同类墙 N 次 → nudge
_FAIL_CIRCUIT_BREAK_AT = 3    # nudge 后再撞第 N 次 → 硬 break
_FAIL_CIRCUIT_NUDGE_PROMPT = (
    "你连续 {count} 次撞上同一类墙 (`{category}`)。\n"
    "**这是鉴权 / 限流 / 验证码 / 工具不准用** —— 换一个同性质的源，大概率还是这堵墙。\n\n"
    "请立即停手:\n"
    "  - 用文字汇报已经拿到的部分\n"
    "  - 说清这堵墙 ({category}) 是哪来的\n"
    "  - 死链、超时、空搜可以换源再试；这类墙不行\n"
    "不要无视这条提示再撞同一类墙——我会硬拦下你。"
)
_FAIL_CIRCUIT_BREAK_PROMPT = (
    "[OPUS 失败熔断 · 同一类墙连续 {count} 次·已自动停下]\n\n"
    "墙: `{category}`\n"
    "鉴权 / 限流 / 验证码 / 工具不准用 · 换源再撞也是这堵墙。\n"
    "建议: 看上面的部分产出，换思路或放弃。死链和空搜不在此列。"
)
# 错误类别判定 (error 字符串粗分类 · 命中即归类 · 未命中按异常类型名 / other)
_ERR_CAT_RULES = (
    # 状态码必须带 http/status 上下文 · 防 traceback「line 403」
    ("http_deny", ("unauthorized", "forbidden", "rate limit",
                   "too many requests", "too many request",
                   "http 401", "http 403", "http 429",
                   "status 401", "status 403", "status 429",
                   "status code 401", "status code 403", "status code 429")),
    ("http_miss", ("http 404", "http 405",
                   "status 404", "status 405",
                   "status code 404", "status code 405")),
    ("timeout", ("timeout", "timed out", "timedout")),
    ("network", ("connection", "connect error", "dns", "read error",
                 "remoteprotocolerror", "protocol error", "连接失败", "网络错误", "网络异常")),
    ("anti_bot", ("验证码", "安全验证", "异常访问", "滑动验证", "人机验证",
                  "captcha", "recaptcha")),
    ("not_allowed", ("not allowed", "unknown tool", "not in this app scope")),
)
_ERR_CAT_FALLBACK = "other"
_ERR_CAT_NON_CIRCUIT = ("declined", "explain", "reject:")
# 只有墙才熔断。404/超时/空搜/普通异常靠 stuck（同工具同参数）拦死磕。
_ERR_CAT_CIRCUIT = frozenset({"http_deny", "anti_bot", "not_allowed"})


def _classify_error(result) -> Optional[str]:
    """把一次工具失败归一化成错误类别 · None=不参与熔断 (成功 / 业务拒绝 / 无错误信息)。"""
    if getattr(result, "ok", True):
        return None
    err = (getattr(result, "error", "") or "").strip()
    if not err:
        return None
    low = err.lower()
    if any(k in low for k in _ERR_CAT_NON_CIRCUIT):
        return None
    for cat, kws in _ERR_CAT_RULES:
        for kw in kws:
            if kw in low:
                return cat
    # 工具异常类型名 (TypeError / ValueError / FileNotFoundError …) · 按异常类型归类
    if ": " in err:
        maybe = err.split(": ", 1)[0].strip()
        if maybe and maybe[0].isupper() and maybe.replace("_", "").isalnum():
            return f"exc:{maybe}"
    return _ERR_CAT_FALLBACK


class _FailCircuit:
    """墙连撞 → nudge → 硬停。换源失败（404/超时/空搜）重置，不当死循环。"""
    __slots__ = ("streak", "current", "nudged")

    def __init__(self) -> None:
        self.streak = 0
        self.current: Optional[str] = None
        self.nudged = False

    def observe(self, result) -> Optional[str]:
        cat = _classify_error(result)
        if cat is None or cat not in _ERR_CAT_CIRCUIT:
            self.streak = 0
            self.current = None
            self.nudged = False
            return None
        if cat == self.current:
            self.streak += 1
        else:
            self.streak = 1
            self.current = cat
            self.nudged = False
        if self.streak >= _FAIL_CIRCUIT_BREAK_AT:
            return "break"
        if self.streak == _FAIL_CIRCUIT_AT and not self.nudged:
            self.nudged = True
            return "nudge"
        return None


def _collect_partial_output(messages: list[dict], max_parts: int = 3, max_chars_per: int = 600) -> str:
    """撞顶/卡死时从 messages 提取已有 assistant 文本 (治本 C: 不白跑)。"""
    parts: list[str] = []
    for m in messages:
        if m.get("role") == "assistant" and m.get("content"):
            t = str(m["content"])
            if t and t not in parts:
                parts.append(t)
    return "\n\n".join(parts)[-max_parts * max_chars_per:]


def _collect_recent_tools(messages: list[dict], max_items: int = 6, max_chars: int = 150) -> str:
    """墙钟超时收尾用: 摘最近几轮工具结果的开头 (跳掉 stdout 标记/修剪头) · 2026-09-15。"""
    lines: list[str] = []
    for m in messages:
        if m.get("role") != "tool":
            continue
        raw = [ln.strip() for ln in str(m.get("content") or "").splitlines() if ln.strip()]
        shown = next((ln for ln in raw
                      if ln not in ("--- stdout ---", "--- stderr ---")
                      and not ln.startswith("[已修剪工具结果")), "")
        if not shown:
            continue
        s = shown[:max_chars]
        if s not in lines:
            lines.append(s)
    return "\n".join("· " + ln for ln in lines[-max_items:])


def _call_confirm(
    confirm: ConfirmCallback,
    spec: ToolSpec,
    args: dict,
    text: str,
    tool_call_id: str = "",
) -> str:
    """兼容 2-arg / 3-arg / 4-arg confirm。

    卷四十六 wish-2a4d8c1e · 新加第 4 个参数 tool_call_id ·
    daemon 端 inline confirm UI 需要它当 _PENDING_CONFIRMS 的 key。
    旧 callback 不接受这个参数 · 走 TypeError 降级到 3-arg / 2-arg 调法。
    """
    try:
        return confirm(spec, args, text, tool_call_id)
    except TypeError:
        try:
            return confirm(spec, args, text)
        except TypeError:
            return confirm(spec, args)


def _push(hook: ProgressHook | None, event_type: str, data: dict) -> None:
    """安全调用 hook——异常吞掉不影响主流程。"""
    if event_type in ("tool_call", "tool_result", "stuck_detected"):
        try:
            from workers.turn_trace import emit
            emit(event_type, **(data or {}))
        except Exception:
            pass
    if hook is None:
        return
    try:
        hook(event_type, data)
    except Exception:
        pass


def _run_tool(spec, args, progress, cancel_check):
    from agent_tools._cancel import reset_cancel_check, set_cancel_check
    ctok = set_cancel_check(cancel_check)
    ptok = _TOOL_PROGRESS_HOOK.set(
        lambda step, msg: _push(progress, "tool_progress", {"step": step, "msg": msg})
    )
    _hb_tool_enter(cancel_check)  # 心跳: 工具执行期豁免判定 (工具自有 timeout)
    try:
        return spec.run(args)
    finally:
        _hb_tool_exit(cancel_check)  # 心跳: 工具结束 · 恢复判定 + 喂跳
        _TOOL_PROGRESS_HOOK.reset(ptok)
        reset_cancel_check(ctok)


def _cancel_requested(cancel_check) -> bool:
    try:
        return bool(cancel_check and cancel_check())
    except Exception:
        return False


def _should_stub_remaining(aborted, cancel_check) -> bool:
    return bool(aborted) or _cancel_requested(cancel_check)


def _is_user_abort(result) -> bool:
    err = (getattr(result, "error", None) or "").lower()
    return "aborted by user" in err or err.strip() == "aborted"


def _abort_stub() -> ToolResult:
    return ToolResult(ok=False, output="", error="aborted by user")


def _trace_abort(reason: str) -> None:
    try:
        from workers.turn_trace import emit as _ab
        _ab("abort", reason=reason)
    except Exception:
        pass


def _result_preview(result: ToolResult, max_chars: int = 300, tool_name: str = "") -> str:
    out = result.output or ""
    # replan (顾问施工单/验收) 是决策依据 · 用户要完整看 · 不截断 (卷八十一续 · BRO 反馈)
    if tool_name == "replan":
        return out
    if len(out) > max_chars:
        out = out[:max_chars] + f" … (+{len(result.output) - max_chars} chars)"
    return out


# ── 可打开产物 marker ─────────────────────────────────────────────
# 产文件的工具(generate_presentation / generate_report …)在输出里塞一行
#   [[DK-OPEN]]相对路径
# tool_loop 抽成 tool_result 事件的 open_path 字段 → 前端渲"用本机软件打开"按钮 ·
# 并把 marker 从 output 里剥掉(不污染喂给 LLM 的内容和 preview)。
_OPEN_MARK_RE = re.compile(r"[ \t]*\[\[DK-OPEN\]\](.+?)[ \t]*(?:\n|$)")


def _to_stage_rel(cand: str) -> str:
    """候选路径必须真实存在、且能上中栏 —— 否则不算数（返回空串）。

    BRO 2026-09-20 实锤：marker 正则对**所有**工具输出生效，而 tool_loop / stage_open
    的注释、playbook 正文、历史日志里都写着样本行（标记名 + 一个假路径）。
    读一遍这些文件就把样本当成真标记抽走 → 前端弹出「相对路径 · 用对应软件打开」这种
    垃圾动作条，还把真产物挤掉（前端只认最后一个路径）→ 该铺的画布反而打不开。
    判据落在文件系统现实上：样本里的 相对路径 / {rel} / <path> 一律落空。
    """
    s = str(cand or "").strip().strip("`").strip().strip('"').strip("'")
    if not s:
        return ""
    try:
        from pathlib import Path as _P
        from workers.stage_open import ROOT as _ROOT, rel_posix, stage_mode
        p = _P(s)
        if not p.is_absolute():
            p = _P(_ROOT) / p
        if not p.is_file():
            return ""
        if not stage_mode(p):
            return ""
        return rel_posix(p) or ""
    except Exception:
        return ""


def _is_serve_url(u: str) -> bool:
    """图廊只收真 URL（http(s):// 或 / 开头的服务路径）。

    同一类病：文档注释里的样本（"daemon 可服务的 URL(...)"）会被当成真图 URL
    塞进对话底部图廊，渲成一排坏图。
    """
    s = str(u or "").strip().strip("`").strip().strip('"')
    return s.lower().startswith(("http://", "https://", "/"))


def _take_declared_stage(result: ToolResult) -> list[str]:
    """第2刀 · 结构化声明通道：工具在 ToolResult.stage_path 里声明「我产了哪个文件」。

    比喉探输出里的字符串标记可靠 —— 字符串通道有两个毛病：① 文档里写着样本就会被误抽
    (2026-09-20 那批垃圾动作条)；② 每个工具要在每个分支手写一行，漏一个就哑。
    两个通道并存期间：有声明优先用声明，没有则回退标记喉探（老工具不改也不坏）。
    """
    if not result.ok:                      # 失败调用即便带了声明也不算产物（与标记通道对称）
        return []
    rel = _to_stage_rel(getattr(result, "stage_path", "") or "")
    return [rel] if rel else []


def _note_stage(result: ToolResult, paths: list[str]) -> None:
    """第2刀 · 出口统一补「铺没铺中栏」那句人话 —— 与 stage_notice 同一份判据。

    工具改成只声明 stage_path 之后，那句「✓ 已铺中栏」就没人写了；而它本来是专门
    做给模型看的（wish-bc4fe249「铺没铺中栏，别让模型猜」）—— 少了它模型又只能猜。
    所以搬到这里：老工具（自己 attach 过）已有这句 → 不重复；声明通道 → 补上。
    """
    if not (result.ok and paths):
        return
    try:
        from workers.stage_open import stage_notice
        note = stage_notice(paths[-1])
        if note and note not in (result.output or ""):
            result.output = "%s\n%s\n" % ((result.output or "").rstrip(), note)
    except Exception:
        pass


def _strip_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """按区间剥掉指定片段（左闭右开）· 只用于「真认下的」标记。"""
    buf: list[str] = []
    last = 0
    for a, b in spans:
        buf.append(text[last:a])
        last = b
    buf.append(text[last:])
    return "".join(buf).rstrip() + "\n"


def _take_open_paths(result: ToolResult) -> list[str]:
    """抽出并剥掉**所有** marker · 只留「真实存在 + 能上中栏」的，按出现顺序去重。

    2026-09-20 · 原来用 search 只抽第一个 —— 一轮产 3 份文件只有第一份有机会铺，
    这正是 BRO 说的「铺中栏像概率功能」的来源之一（基线实测：3 个标记只抽出 1 个）。
    现在全收；事件里 open_path 仍是最后一个（= 最近产出的那份），另带 open_paths 全量。
    """
    if not (result.ok and result.output):
        return []
    out: list[str] = []
    seen: set[str] = set()
    spans: list[tuple[int, int]] = []
    for m in _OPEN_MARK_RE.finditer(result.output):
        rel = _to_stage_rel(m.group(1))
        if rel and rel not in seen:
            seen.add(rel)
            out.append(rel)
            spans.append(m.span())
    if spans:
        # 只剥「认下的」标记。以前是无条件 sub() —— 文件里写着的样本标记也会被吃掉，
        # 而工具「读了再回写」（edit_file 就是）就会把源文件里的样本**永久**删掉：
        # 2026-09-20 实测 tool_loop.py 自己注释里的样本就被吃成了「DK-IMGdaemon」。
        result.output = _strip_spans(result.output, spans)
    return out


# ── 可内联显示的配图 marker ───────────────────────────────────────
# 生图工具(generate_image …)每张成功的图在输出里塞一行
#    [[DK-IMG]]daemon 可服务的 URL(/presentations/... 或 /workshop/outputs/...)
# tool_loop 抽成 tool_result 事件的 images 列表 → 前端在对话底部渲可点放大的图廊 ·
# 并把 marker 从 output 里剥掉(不污染喂给 LLM 的内容和 preview · LLM 仍能用它下面的文件路径清单)。
_IMG_MARK_RE = re.compile(r"[ \t]*\[\[DK-IMG\]\](.+?)[ \t]*(?:\n|$)")


def _take_image_urls(result: ToolResult) -> list:
    """抽出并剥掉 DK-IMG marker · 返回去重保序的 URL 列表(上限 12)。 就地清理 result.output。

    与 _take_open_paths 同一条规矩：只剥「真认下的（能服务的 URL）」标记 ——
    文档/注释里的样本一字不动，否则「读了再回写」会把源文件里的样本永久吃掉。
    """
    if not (result.ok and result.output):
        return []
    seen: set[str] = set()
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    for m in _IMG_MARK_RE.finditer(result.output):
        u = m.group(1).strip()
        if _is_serve_url(u) and u not in seen and len(out) < 12:
            seen.add(u)
            out.append(u)
            spans.append(m.span())
    if spans:
        result.output = _strip_spans(result.output, spans)
    return out


def _take_hits(result: ToolResult) -> list:
    """抽出并剥掉 [[DK-HITS]] · 搜索卡给前端，不进 LLM 正文。"""
    if not (result.ok and result.output):
        return []
    try:
        from agent_tools._web_search_fmt import strip_hits
        clean, items = strip_hits(result.output)
    except Exception:
        return []
    if items:
        result.output = clean
    return items


# ---------- 发送时工具输出瘦身 (省 token · 非破坏) ----------
# 问题: 一个大 read_file / browser_fetch / 报告的完整 output 全量入历史 · 之后【每一轮】
#       都跟着重发 · 直到压缩层 (60% 窗口) 才收拾 · 窗口前这段是纯烧钱。
# 修法: 只在【发给 API 的那一份 payload】上 · 把"旧的、超大的"工具输出截成 head + 省略提示。
#       - 落盘的 session jsonl / 返回给 daemon 的 messages / UI 显示 · 全部不动 (真源完整)。
#       - 当轮刚产出的工具输出必须全量 (LLM 要用) → 最近 N 个 user 回合不瘦身 (OpenCode tail turns)。
#       - 截断是确定性的 → 同一条旧输出每轮截成同样结果 → 不破坏 prefix cache 命中。
#       - OPUS_TOOL_HISTORY_CAP=0 关闭整条 · 退回老行为。
def _tool_hist_cap() -> int:
    raw = (os.environ.get("OPUS_TOOL_HISTORY_CAP") or "").strip()
    if raw:
        try:
            return int(raw)
        except (ValueError, TypeError):
            pass
    return 8000


def _diet_tool_text(text: Any, cap: int) -> tuple[Any, bool]:
    if not isinstance(text, str) or cap <= 0 or len(text) <= cap:
        return text, False
    # 头 + 尾都保留(尾部常是结论/报错/汇总·只留头易丢关键信息)·只省中间·比一刀切头更稳。
    # 注意: 这只是"超大原始 dump"的安全网 · 久远对话的【语义压缩】由 memory_compression 负责。
    head_n = (cap * 2) // 3
    tail_n = cap - head_n
    omitted = len(text) - cap
    head = text[:head_n]
    tail = text[-tail_n:] if tail_n > 0 else ""
    return (
        head
        + f"\n\n…[中间 {omitted} 字符已省略 · 头尾保留 · 需完整内容请重新调用该工具]…\n\n"
        + tail,
        True,
    )


def _diet_messages_for_send(msgs: list) -> list:
    """返回一份"旧大工具输出已截断"的 messages 副本(无改动则原样返回同一对象)。"""
    cap = _tool_hist_cap()
    if cap <= 0:
        return _inject_pending_images(msgs)
    from workers.memory_compression import tail_protect_index
    cutoff = tail_protect_index(msgs)
    if cutoff <= 0:
        return _inject_pending_images(msgs)
    any_change = False
    out: list = []
    for i, m in enumerate(msgs):
        if i >= cutoff or not isinstance(m, dict):
            out.append(m)
            continue
        role = m.get("role")
        if role == "tool":
            c2, ch = _diet_tool_text(m.get("content"), cap)
            if ch:
                nm = dict(m)
                nm["content"] = c2
                out.append(nm)
                any_change = True
                continue
        elif role == "user" and isinstance(m.get("content"), list):
            blocks = m["content"]
            new_blocks = None
            for j, b in enumerate(blocks):
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    c2, ch = _diet_tool_text(b.get("content"), cap)
                    if ch:
                        if new_blocks is None:
                            new_blocks = list(blocks)
                        nb = dict(b)
                        nb["content"] = c2
                        new_blocks[j] = nb
            if new_blocks is not None:
                nm = dict(m)
                nm["content"] = new_blocks
                out.append(nm)
                any_change = True
                continue
        out.append(m)
    return _inject_pending_images(out if any_change else msgs)


def _inject_pending_images(msgs: list) -> list:
    """wish-00ed11c2 · 多模态图片注入 · 发送前最后一刻把图组装进末尾 user 消息。

    背景: _process_attachments 判定当前模型原生视觉时·把图注册到 RUNTIME.pending_images
    (内存/持久化里的 user message 永远保持 str · 压缩层/token 计数/前端渲染零感知)。
    这里在发送前临时把最后一条 str user 消息升级成 OpenAI content list
    (image_url blocks + text) · 让多模态模型"直接看到图"而不是看 look_at 的文字转述。

    安全约束:
      - pending.sid 必须等于**本轮**的会话身份（current_session_id · ContextVar·每 turn 独立）
        —— 不能用 RUNTIME.session_id（进程全局·两个会话并发时会被对方覆盖→校验失效）
      - supports_vision(当前模型) 必须为 True (模型切回纯文本就不再注入)
      - 只改返回的副本 · 原 messages 数组绝不动 (tool 循环每轮重复注入同一组图)
      - 任何异常都吞掉返回原 msgs (注入失败不该把主对话搞崩)
    """
    try:
        from daemon_runtime import RUNTIME
        pend = getattr(RUNTIME, "pending_images", None)
        if not pend or not pend.get("images"):
            return msgs
        # 2026-09-23 修跨会话串台 (wish-7fa81bd0): 基准改用**本轮**身份。
        # 病根: 原来比的是 RUNTIME.session_id —— 进程全局 · daemon_api 每个 turn 进来都覆盖它。
        # 两个会话同时跑时，后到的 turn 把全局盖成对方的 sid → 校验从「不等于」变「等于」
        # → A 会话上传的图直接注进 B 会话的输入。实测: 19:30 续场 turn 收到了 19:30:35
        # 另一个会话传的图。current_session_id() 是 ContextVar(set_session_context 在
        # /chat 入口设) · 每 turn 独立 · 并发也不会互相污染。
        # 2026-09-23 修跨会话串台 (wish-7fa81bd0): 基准改用**本轮**身份。
        # 病根: 原来比的是 RUNTIME.session_id —— 进程全局 · daemon_api 每个 turn 进来都覆盖它。
        # 两个会话同时跑时，后到的 turn 把全局盖成对方的 sid → 校验从「不等于」变「等于」
        # → A 会话上传的图直接注进 B 会话的输入。实测: 19:30 续场 turn 收到了 19:30:35
        # 另一个会话传的图。current_session_id() 是 ContextVar(set_session_context 在
        # /chat 入口设) · 每 turn 独立 · 并发也不会互相污染。
        from agent_tools import current_session_id
        if pend.get("sid") != current_session_id():
            return msgs
        from model_aliases import supports_vision
        if not supports_vision(RUNTIME.model or ""):
            return msgs
        # 找最后一条 role=user 且 content 还是 str 的消息 · 升级成 content list
        for i in range(len(msgs) - 1, -1, -1):
            m = msgs[i]
            if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str):
                blocks = [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
                    for mime, b64 in pend["images"]
                ]
                blocks.append({"type": "text", "text": m["content"]})
                out = list(msgs)
                nm = dict(m)
                nm["content"] = blocks
                out[i] = nm
                return out
        return msgs
    except Exception:
        return msgs


# 卷十八加：LLM args 客户端 JSON schema 校验
# ----------------------------------------
# 背景：deepseek（包括其他便宜模型）在长 context 下偶尔会输 schema 失误的 args，
# 例如 {"url": "true", "max_chars": "false", "string": "https://..."} —— 把 URL 塞进
# 不存在的 "string" 字段。工具内部检查会报错，但错误信息往往不告诉 LLM "字段名错了"，
# 导致下一轮 LLM 还在猜。
#
# 这一层做最便宜的 sanity check：
#   - required 字段全在
#   - 每个出现的字段类型对（不做 pattern/format/enum 这种 deep validation）
#   - 多余字段警告但不致命
# 任何校验失败都把详细的"schema 长什么样 / 你传了什么 / 怎么改" 返给 LLM，
# 让它下一轮自我修正——不让 LLM 在自残式重试里浪费 token。

_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}


def _validate_args(args: dict, schema: dict | None, tool_name: str) -> str | None:
    """返回 None 表示 ok；返回字符串则作为 error 反馈给 LLM。"""
    if not isinstance(schema, dict):
        return None
    properties = schema.get("properties") or {}
    required = schema.get("required") or []

    missing = [k for k in required if k not in args]

    type_errors: list[str] = []
    for k, v in args.items():
        if k not in properties:
            continue
        prop = properties[k]
        if not isinstance(prop, dict):
            continue
        expected = prop.get("type")
        if not expected:
            continue
        if isinstance(expected, list):
            py_types = tuple(
                t for t in (_TYPE_MAP.get(e) for e in expected) if t is not None
            )
            if not py_types:
                continue
            # flatten tuples
            flat: list[type] = []
            for t in py_types:
                if isinstance(t, tuple):
                    flat.extend(t)
                else:
                    flat.append(t)
            ok = isinstance(v, tuple(flat))
        else:
            py_type = _TYPE_MAP.get(expected)
            ok = py_type is None or isinstance(v, py_type)
        if not ok:
            type_errors.append(
                f"  - {k}: schema 要 {expected!r}，你传了 {type(v).__name__}={v!r}"
            )

    unknown = [k for k in args.keys() if k not in properties]

    # B-② · 2026-08-27 · unknown 不再单独硬失败 · 工具 schema 可声明 additionalProperties
    # 扩展字段 (CONFIRM 工具的 risk_explanation/mitigation 就走这个) · unknown 只作附带提示 (Grok 全量审计)
    if not (missing or type_errors):
        return None

    parts = [f"工具 `{tool_name}` 的 args 不符合 schema："]
    if missing:
        parts.append(f"  缺必填字段: {missing}")
    if type_errors:
        parts.append("  字段类型错:")
        parts.extend(type_errors)
    if unknown:
        parts.append(f"  未知字段（不在 schema.properties 里）: {unknown}")
    parts.append("")
    parts.append(f"schema.properties: {list(properties.keys())}")
    if required:
        parts.append(f"schema.required:   {required}")
    parts.append("")
    parts.append("→ 请用正确的字段名 + 类型重新调用，不要重复同样的错误。")
    return "\n".join(parts)


# ── 卷五十八续 ⑤ · 受限并行工具执行 ──────────────────────────────────────
# LLM 一轮里一次发多个工具调用时·若【整批全是已知的只读 AUTO 工具】(read_file / grep_files /
# search_code / outline_file / glob_files / look_at / recall_memory ...) 就并发跑·省掉串行
# 等待 (3 个 read 顺序跑 vs 同时跑)。
# 任一是 confirm/guard/未知工具 → 整批退回原【串行】路 (写操作并发=竞态·确认要排队·绝不并行)。
# 只读 AUTO 工具无副作用·并发安全。 结果按 index 回填·主循环仍按原顺序消费 → 事件/commit 顺序不变。
_PARALLEL_MAX_WORKERS = 4


def _batch_all_auto(specs_args: list[tuple[ToolSpec | None, dict]]) -> bool:
    """整批是否全是已知的 AUTO 工具 (可并发的充要条件)。 <2 个不值得并行。"""
    if len(specs_args) < 2:
        return False
    for spec, args in specs_args:
        if spec is None:
            return False
        try:
            if spec.effective_tier(args) != TIER_AUTO:
                return False
        except Exception:
            return False
    return True


def _maybe_parallel_auto(
    specs_args_names: list[tuple[ToolSpec | None, dict, str]],
    progress: "ProgressHook | None",
    allowed_tool_names: set[str] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[int, ToolResult]:
    """整批全只读 AUTO → 并发预跑·返回 {index: ToolResult}。 否则返 {} (主循环走原串行路)。

    只对 args 合 schema 的调用并发跑 (不合的留给主循环报 schema 错·不浪费一次运行)。
    每个 worker 在自己线程里设进度钩子 · 跑完即 reset。
    abort 时不再 `with Executor` 死等跑完 —— 那会让停止钮停在「正在停」、下一轮 self_heal。
    """
    if not _batch_all_auto([(s, a) for s, a, _ in specs_args_names]):
        return {}

    jobs: list[tuple[int, ToolSpec, dict]] = []
    for i, (spec, args, name) in enumerate(specs_args_names):
        if spec is None:
            continue
        if allowed_tool_names is not None and name not in allowed_tool_names:
            continue  # Grok-2 · 2026-08-27 · 白名单外不并行预跑 · 留给主循环报 denied
        if _validate_args(args, spec.input_schema, name) is None:
            jobs.append((i, spec, args))
    if len(jobs) < 2:
        return {}

    import concurrent.futures

    def _work(spec: ToolSpec, args: dict) -> ToolResult:
        token = _TOOL_PROGRESS_HOOK.set(
            lambda step, msg: _push(progress, "tool_progress", {"step": step, "msg": msg})
        )
        try:
            return _run_tool(spec, args, progress, cancel_check)
        except Exception as e:
            return ToolResult(ok=False, output="", error=f"{type(e).__name__}: {e}")
        finally:
            _TOOL_PROGRESS_HOOK.reset(token)

    out: dict[int, ToolResult] = {}
    # read_scenario 写本回合闸。copy_context 进池后 ContextVar.set 回不来；
    # 即便闸改成共享 set，跟 create_app 同批并行仍会竞态。先在当前线程落地。
    rest: list[tuple[int, ToolSpec, dict]] = []
    for idx, spec, args in jobs:
        if spec.name == "read_scenario":
            out[idx] = _work(spec, args)
        else:
            rest.append((idx, spec, args))
    jobs = rest
    if len(jobs) < 2:
        return out

    workers = min(_PARALLEL_MAX_WORKERS, len(jobs))
    # 每个 job 带一份**独立的** context 副本进线程 (2026-08-19 修)。
    #
    # 病根: `ThreadPoolExecutor.submit` 不传递 contextvars —— 线程里 `_SESSION_CTX` 是空的·
    # `current_session_id()` 于是退化成 `t<线程id>`。 后果不止"记错"·是**功能不成立**:
    #   · track_task 把任务账本绑到 t17900 而不是真会话 → 计划条在界面上根本不出现·
    #     下一批工具换了线程池 → 又是新线程 id → 勾步骤报"没有活跃计划"
    #   · edit_file/write_file 的编辑锁 owner 也认不出"哪个对话在改"
    # 而串行那两条路 (spec.run 直接跑在当前线程) 上下文是活的 —— 于是**同一轮对话里
    # 单个工具正常、并行批次失灵**·`data/runtime/ledger_active.json` 里真 session id 和
    # t 开头的键混着躺了一个月没人发现。 又是一次"两条路各自一个行为"。
    #
    # 必须每个 job 单独 copy: 同一个 Context 对象不能被两个线程同时 `run`
    # (RuntimeError: cannot enter context - it is already entered)。
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    fut_to_idx: dict[concurrent.futures.Future, int] = {}
    try:
        for idx, spec, args in jobs:
            ctx = contextvars.copy_context()
            fut_to_idx[ex.submit(ctx.run, _work, spec, args)] = idx
        pending = set(fut_to_idx)
        aborted = False
        while pending:
            if cancel_check is not None and cancel_check():
                aborted = True
                break
            done, pending = concurrent.futures.wait(
                pending, timeout=0.15, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for fut in done:
                idx = fut_to_idx[fut]
                try:
                    out[idx] = fut.result()
                except Exception as e:
                    out[idx] = ToolResult(ok=False, output="", error=f"{type(e).__name__}: {e}")
        if aborted:
            for fut in pending:
                fut.cancel()
                idx = fut_to_idx[fut]
                if idx in out:
                    continue
                if fut.done() and not fut.cancelled():
                    try:
                        out[idx] = fut.result()
                    except Exception as e:
                        out[idx] = ToolResult(ok=False, output="", error=f"{type(e).__name__}: {e}")
                else:
                    out[idx] = ToolResult(ok=False, output="", error="aborted")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return out


# ---------- usage stats with caching ----------

@dataclass
class UsageStats:
    """每轮 loop 的 token 用量。"""
    input_tokens: int = 0          # 总 input（包括 cache hit/miss 都算进来）
    output_tokens: int = 0
    cache_creation_tokens: int = 0  # 这次有多少 token 被新写入 cache
    cache_read_tokens: int = 0      # 这次从 cache 读了多少 token（这部分极便宜）

    def add(self, other: "UsageStats") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_creation_tokens += other.cache_creation_tokens
        self.cache_read_tokens += other.cache_read_tokens

    @property
    def billable_input_tokens(self) -> int:
        """估算"按全价计费"的 input token。
        cache_read 部分在 Anthropic 价目表上是 10% 的钱，cache_creation 是 125%。
        这里给一个粗略 normalized number，方便日志感知。"""
        non_cache = self.input_tokens - self.cache_read_tokens - self.cache_creation_tokens
        return non_cache + int(self.cache_creation_tokens * 1.25) + int(self.cache_read_tokens * 0.10)


# ---------- caching helpers ----------

def _uses_deepseek_prefix_cache(base_url: str | None, model: str = "") -> bool:
    """DeepSeek 自动前缀缓存 · 不绑官网域名。

    纯净版会填官网 / 硅基 / new-api / 自建网关，base_url 各不相同。
    模型名带 deepseek（含 deepseek-ai/DeepSeek-*）或走官网 URL，易变尾巴挂 messages 末尾。
    """
    url = (base_url or "").lower()
    ml = (model or "").lower()
    return "deepseek.com" in url or "deepseek" in ml


def _supports_aihubmix_cache(base_url: str | None, model: str) -> bool:
    """OpenAI-compat 端点 + 模型 family 双判：当前只对 AiHubMix 上的 Claude family 启用。

    2026-05-16 第二根毛收紧的：之前只判 base_url，但 cache_control 字段在
    AiHubMix 上仅 Claude 系列真生效。DeepSeek / Kimi / GLM / GPT / Gemini 加了不会报错，
    但也不会真省钱——而且把 system 包成 list-of-blocks 反而可能误触某些客户端校验。
    所以 model 必须是 claude-* 才启用。
    """
    if not base_url or "aihubmix.com" not in base_url.lower():
        return False
    return (model or "").lower().startswith("claude")


# 卷三十八 · DeepSeek thinking 默认会用英文 reasoning · 但 BRO 母语是中文 · 强制中文
# 这段 append 到 system_text 末尾 · 只对 DeepSeek 加 (其他模型一般 follow user language)
_DEEPSEEK_LANG_HINT = (
    "\n\n---\n"
    "## 输出语言 (Critical)\n"
    "BRO 的母语是中文。所有输出 (包括 reasoning_content 思考链 / 最终回复 / 写代码时的注释 / git commit message) "
    "**默认都必须用中文**。除非:\n"
    "- BRO 明确要求用英文回复\n"
    "- 代码标识符 / API 字段 / 命令行参数等技术名词 (这些保留英文)\n"
    "- 你在引用英文原文 (用引号标出来)\n\n"
    "⚠ 即使你在 thinking 阶段习惯了用英文推理 · 也要切回中文。"
    "BRO 不想看到一大段英文 reasoning 然后才反应过来切中文。"
)


def _build_openai_system(
    system_stable: str, system_suffix: str, base_url: str | None, model: str,
    *,
    suffix_in_system: bool = True,   # False = 返回纯 stable · suffix 由调用方挪到 messages 末尾
) -> Any:
    """拼 OpenAI 协议的 system·把「稳定前缀」与「每轮变的尾巴」分开。

    3b · 缓存前缀稳定化 (best practice · DeepSeek/Anthropic 同理):
      - system_stable: 灵魂 + 远程 hint · 一个 session 内字节不变 → 可被缓存的前缀
      - system_suffix: telemetry(含时间/git) + playbook/记忆/工坊提示 · 每轮变 → 缓存外
      把易变内容压到稳定前缀之后·DeepSeek 自动 disk cache 命中前缀· Claude 缓存断点
      只打在稳定块上·尾巴变了也不会冲掉灵魂缓存 (之前整段一个块·尾巴一变全重建)。
    """
    stable = system_stable
    # 卷三十八 · DeepSeek 强制中文 reasoning · 常量·并入稳定前缀 (一起被缓存)
    if _uses_deepseek_prefix_cache(base_url, model):
        stable = stable + _DEEPSEEK_LANG_HINT

    if _supports_aihubmix_cache(base_url, model):
        blocks = [
            {"type": "text", "text": stable, "cache_control": {"type": "ephemeral"}},
        ]
        if system_suffix:
            # 易变尾巴单独成块·不打 cache_control → 不进缓存前缀·变了不冲灵魂缓存
            blocks.append({"type": "text", "text": system_suffix})
        return blocks

    # 不走 cache_control 的端点 (含 DeepSeek 自动缓存): 拼成一个 string·
    # 稳定前缀在前·易变尾巴在后·让 DeepSeek 的前缀匹配命中稳定段。
    if not suffix_in_system:
        return stable              # DeepSeek 路径: 纯 stable · 尾巴由调用方挪到 messages 末尾 (append-only)
    return stable + system_suffix


# ---------- schema translation ----------

# P1 代码归一 · 工具描述里也写满 OPUS/BRO 令牌·送进 LLM 前本地化成本实例的名字。
# 母体走缺省值 = passthrough·零改动。identity 缺失则降级为原样返回·不影响 daemon。
try:
    from identity import localize as _localize
except Exception:
    def _localize(t):
        return t


def _specs_for_llm(allowed_tool_names: set[str] | None) -> list[ToolSpec]:
    from agent_tools._tool_catalog import set_catalog_allowed, visible_specs
    set_catalog_allowed(allowed_tool_names)
    return visible_specs(allowed_tool_names)


def _rewrite_tool_use(name: str, args: dict) -> tuple[str, dict]:
    from agent_tools._tool_catalog import resolve_call
    return resolve_call(name, args)


def to_openai_tools(specs: list[ToolSpec]) -> list[dict]:
    # 按名字排序锁死 tools[] 顺序 · 导入顺序漂移会打穿 DeepSeek 前缀缓存
    return [
        {
            "type": "function",
            "function": {
                "name": s.name,
                "description": _localize(s.description),
                "parameters": s.input_schema,
            },
        }
        for s in sorted(specs, key=lambda s: s.name)
    ]


def to_anthropic_tools(specs: list[ToolSpec]) -> list[dict]:
    return [
        {
            "name": s.name,
            "description": _localize(s.description),
            "input_schema": s.input_schema,
        }
        for s in sorted(specs, key=lambda s: s.name)
    ]


# ---------- the loop itself ----------

def run_tool_loop(
    *,
    client: Any,
    provider: str,
    model: str,
    max_tokens: int,
    system: str,
    messages: list[dict],
    confirm: ConfirmCallback,
    observe: ObserveCallback | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    base_url: str | None = None,
    progress: ProgressHook | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_message_commit: Callable[[dict], None] | None = None,
    allowed_tool_names: set[str] | None = None,
    system_suffix: str = "",
    thinking: str | None = None,
    reasoning_effort: str | None = None,
    wall_clock_sec: float | None = None,
    stall_sec: float | None = None,
    llm_timeout_sec: float | None = None,
    pending_messages: Callable[[], list] | None = None,
) -> tuple[str, list[dict], UsageStats]:
    """
    多轮 tool use 循环。返回 (最终 OPUS 文本回复, 更新后的 messages, UsageStats)。

    messages 会被原地追加（assistant tool_use turns + user tool_result turns），
    便于 daemon 一次循环结束后直接持久化 / 继续下一轮对话。

    base_url: 用来判断是否启用 prompt caching（目前只对 aihubmix.com 启用）。
    system_suffix: 3b · 每轮随消息变的「易变尾巴」(telemetry + playbook/记忆/工坊提示)。
                  与 system (稳定前缀) 分开传·缓存断点只打在 system 上·尾巴留缓存外。
                  默认 "" → 等价老行为 (system 单块·全部参与缓存)·所有老调用方零改动。
    progress: 可选的事件推送 hook（卷十七加，给 SSE 端点用）。
    cancel_check: 可选 · 卷三十六加 · 每个 iteration 头部 check 一次 · 返回 True
                  则提前结束 loop。LLM 调用正在阻塞时拦不下 · 但下一轮前就停。
    on_message_commit: 卷四十一加 · 增量落盘 callback ·
                  每次一个 assistant turn / tool result 落进 messages 时立刻调用 ·
                  让 daemon kill -9 时也不丢 in-flight turns。
                  上层注入 lambda entry: append_turn(sid, entry['role'], ...)。
    allowed_tool_names: 沉淀闭环 v2 修补 · 卷七十二 (2026-06-10) · 工具白名单。
                  None = 全 REGISTRY 暴露 (主对话默认)。
                  set[str] = 只暴露白名单内工具给 LLM · hallucinate 调白名单外
                  的工具一律返回 "tool not allowed in this scope" 而非真执行。
                  app_runner 跑工坊 app 时传入·防 app 子作用域 LLM 越权调
                  run_app / python_exec 等大权限工具(审稿 app 调 run_app 跑了 5 分钟
                  内容制作 = 此条修补真实触发场景)。
    """
    try:
        from agent_tools._hotpath_guard import begin_turn as _hp_begin, _channel as _hp_ch
        _hp_begin(_hp_ch.get() or "")
    except Exception:
        pass
    # ── 会话结构自愈（卷五十五 · 2026-06-03 · 防 [500] · P3 升级为完整体检）─────
    # 病根: turn 在 tool 执行前被打断 (重启/abort/网断) → 历史里留下 assistant.tool_calls
    # 没有对应 tool result → 下次发给 LLM 报 400 "An assistant message with 'tool_calls'
    # must be followed by tool messages" → BRO 重启后一发消息就 500 · 续场 background
    # turn 也撞同一颗雷静默死掉 (= "重启后不一定拉起续场" 的真凶)。
    # 修法: 发给 LLM 之前·在内存里做结构体检 ── 两类镜像病都治:
    #   ① 孤儿 tool result (有 result 没 call · 历史被截断) → 删
    #   ② 悬空 tool_call   (有 call 没 result · turn 被打断) → 补合成 result (标 self_heal)
    # 纯内存·不碰 jsonl·对健康 session 是 no-op·对所有路径(主对话/续场/终端)生效。
    # 放在压缩之前: 让压缩拿到的是结构合法的 messages。
    try:
        from workers.session_repair import sanitize_messages_inplace
        _rep = sanitize_messages_inplace(messages)
        if _rep.get("orphans_removed") or _rep.get("dangling_healed"):
            import logging as _lg
            _lg.getLogger("opus.tool_loop").warning(
                "会话结构自愈 · 删孤儿 result %d 条 · 补悬空 tool_call %d 条 · 防 LLM 400",
                _rep.get("orphans_removed", 0), _rep.get("dangling_healed", 0))
    except Exception:
        # 自愈本身不能把主流程搞崩
        pass

    # ── 运行时信封净化 (2026-09-23 · wish-26643574) ────────────────────
    # 外来 [Timestamp:]/[Session info:] 行会让模型以为自己在另一个时间/会话上推理。
    # 纯内存剔行 · 与上面的结构自愈同一位置 (都在「发给 LLM 之前」)。
    try:
        _env_hits = _strip_envelope_tags_inplace(messages)
        if _env_hits:
            import logging as _lg2
            _lg2.getLogger("opus.tool_loop").warning(
                "[信封净化] 剔除外来运行时标记 %d 条消息 (纯内存 · 不改 jsonl 原文)", _env_hits)
    except Exception:
        pass

    # ── 自动压缩钩子（wish-58af621e · 卷三十五 + wish-83fe7c7b · 卷五十四）──────
    # 在每次 tool_loop 入口按 token 预算 + 模型窗口动态触发压缩，
    # 省 token + 避免长对话爆 context。对所有路径（终端/API/SSE）生效。
    try:
        from workers.memory_compression import (
            auto_compress, token_budget_check, get_last_compression_stats, prune_if_needed,
        )
        pruned = prune_if_needed(messages, model_id=model)
        if pruned is not messages:
            messages.clear()
            messages.extend(pruned)
        if token_budget_check(messages, model_id=model):
            try:
                from workers.compact_flush import flush_before_compact
                from workers.turn_trace import emit as _trace
                _flush = flush_before_compact(messages, client, model, provider)
                _trace("compact_flush", **_flush)
            except Exception:
                pass
            # v3 (wish-273d3d3f · ②) · 把主对话的稳定前缀 system 带给摘要调用 →
            # 两边开头字节级一致 → 摘要调用也能吃到 prompt cache (不等 system_suffix · 它每轮变)
            compressed = auto_compress(messages, client, model, provider, model_id=model,
                                       system_stable=system)
            if compressed is not messages:
                messages.clear()
                messages.extend(compressed)
                try:
                    from workers.turn_trace import emit as _trace2
                    _trace2("compact", n=len(messages))
                except Exception:
                    pass
                # v2 · 压缩/修剪 stats log (wish-7f0adf2c)
                try:
                    _push(progress, "usage", {
                        "input_tokens": 0, "output_tokens": 0,
                        "cache_read_tokens": 0, "cache_creation_tokens": 0,
                        "iteration": -1,
                        "compression": get_last_compression_stats(),
                    })
                except Exception:
                    pass
    except Exception:
        # 自动压缩挂了不能把主流程搞崩
        pass


    # wish-8914f90c (墨言 wish-94d5c598 移植) · 后台/受限 turn: 单次 LLM 调用有界。
    # SDK create() 不接受 per-request max_retries (openai/anthropic 实测 TypeError)·
    # 必须 client.with_options() 换 per-turn client · 两 provider 统一。
    # 边界: 墙钟/llm_timeout 只覆盖 LLM 调用挂起 · 工具自身执行挂起 (本地 IO/子进程)
    # 救不了 — 工具层各自负责 · 分层设计的明确边界。
    if llm_timeout_sec and llm_timeout_sec > 0:
        try:
            client = client.with_options(timeout=llm_timeout_sec, max_retries=0)
        except Exception:
            pass  # 假 client / 旧 SDK 无 with_options → 保持原 client (不炸主链路)

    # 心跳看门狗 (2026-09-16 · wish-1dc8d738 · 由"墙钟熔断"升级):
    # 旧墙钟从 turn 开始算总时长, 到点一刀 — 误伤正常长活 (09-16 断案: 18 个 turn 卡 4.5-5.5min)。
    # 新判定盯"最后一次进展"(心跳): LLM 流每 chunk / 迭代推进 / 工具边界 = 跳一下;
    #   心跳停 > stall_sec 才判"真卡" (治 08-09 墨言事故那种 LLM 挂起)。
    # wall_clock_sec 退居"总时长宽兜底"(防无限循环), 先到先 fire。
    # 分层不变: 工具执行期豁免心跳判定 (工具自有 timeout · 各自负责)。
    if (wall_clock_sec and wall_clock_sec > 0) or (stall_sec and stall_sec > 0):
        _hb_start = time.monotonic()
        _user_cancel = cancel_check

        def _hb_cancel() -> bool:
            if _user_cancel is not None and _user_cancel():
                return True
            if getattr(_hb_cancel, "_in_tool", False):
                # 工具执行期: 豁免心跳判定 (工具自有 timeout) · 仅留总时长宽兜底
                if wall_clock_sec and wall_clock_sec > 0 and time.monotonic() - _hb_start > wall_clock_sec:
                    _hb_cancel.timed_out = True
                    return True
                return False
            now = time.monotonic()
            # 2026-09-18 · 两段式: 等首 chunk 期间无法产生心跳 → 用宽阈值地板。
            # 仅当 stall_sec 本身有效时才套地板 —— stall_sec=0/None 是调用方显式
            # 关闭停滞检测的语义，不能被地板"重新打开"(code_review 20260918)。
            if stall_sec and stall_sec > 0:
                _eff_stall = (
                    max(stall_sec, _TTFT_STALL_FLOOR)
                    if getattr(_hb_cancel, "awaiting_first_chunk", False)
                    else stall_sec
                )
                if now - _hb_cancel._last > _eff_stall:
                    _hb_cancel.stalled = True  # 分清"心跳停/总时长/用户取消" · 收尾文案不同
                    return True
            if wall_clock_sec and wall_clock_sec > 0 and now - _hb_start > wall_clock_sec:
                _hb_cancel.timed_out = True
                return True
            return False

        def _hb_beat() -> None:
            _hb_cancel._last = time.monotonic()

        _hb_cancel.timed_out = False  # type: ignore[attr-defined]
        _hb_cancel.stalled = False
        _hb_cancel._last = _hb_start
        _hb_cancel._in_tool = False
        _hb_cancel.awaiting_first_chunk = False  # 2026-09-18 · 两段阈值标记
        _hb_cancel.beat = _hb_beat
        cancel_check = _hb_cancel


    if provider == "openai":
        return _loop_openai(
            client=client, model=model, max_tokens=max_tokens,
            system=system, messages=messages,
            confirm=confirm, observe=observe,
            max_iterations=max_iterations, base_url=base_url,
            progress=progress, cancel_check=cancel_check,
            on_message_commit=on_message_commit,
            allowed_tool_names=allowed_tool_names,
            system_suffix=system_suffix,
            thinking=thinking, reasoning_effort=reasoning_effort,
            pending_messages=pending_messages,
        )
    elif provider == "anthropic":
        return _loop_anthropic(
            client=client, model=model, max_tokens=max_tokens,
            system=system, messages=messages,
            confirm=confirm, observe=observe,
            max_iterations=max_iterations,
            progress=progress, cancel_check=cancel_check,
            allowed_tool_names=allowed_tool_names,
            on_message_commit=on_message_commit,
            system_suffix=system_suffix,
            thinking=thinking, reasoning_effort=reasoning_effort,
            pending_messages=pending_messages,
        )
    else:
        raise RuntimeError(f"unknown provider: {provider}")


# ---------- OpenAI-protocol loop (AiHubMix / OpenRouter / 自建中转) ----------

def _extract_openai_cache_usage(usage: Any) -> tuple[int, int]:
    """OpenAI 协议各家把 cache 命中挂在 usage 上·字段名三套都见过：
       - cache_creation_input_tokens / cache_read_input_tokens   (Anthropic 原生 · AiHubMix)
       - prompt_tokens_details.cached_tokens                     (OpenAI / LiteLLM 归一风格)
       - prompt_cache_hit_tokens / prompt_cache_miss_tokens      (DeepSeek 自动 disk cache)
    按优先级摸一遍，返回 (creation, read)。read 走我们的计费估算 10% 那档。
    2026-08-14 · 从墨言 094 移植 workers.cache_usage 唯一真源 (含 miss 提取) · 这里委托它·
    保留二元组签名兼容 (调用方 L1252 只取前两个)。
    """
    from workers.cache_usage import extract_openai_cache_usage as _ext
    creation, read, _miss = _ext(usage)
    return creation, read


def _inject_reasoning_off_token(messages, token: str) -> bool:
    """把「关思考」的控制词并进 system 消息 (软开关·如 Qwen3 的 /no_think)。

    wish-33624071 · 有些模型没有 API 开关·但训练时教过 prompt 里的控制词。
    实测 (LM Studio · qwen3-8b-heretic): system 里加 /no_think →
      reasoning 559字→0字 · completion_tokens 369→42 (省 88.6%) · 快 7.4 倍 · content 一字不少。
    幂等: 已含该词就不再追加·防多轮越加越多。没 system 消息就在最前补一条。
    """
    if not isinstance(messages, list):
        return False
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system":
            cur = msg.get("content")
            if isinstance(cur, str):
                if token in cur:
                    return True
                msg["content"] = (cur + "\n" + token) if cur else token
                return True
            return True
    messages.insert(0, {"role": "system", "content": token})
    return True


def _apply_openai_reasoning(kwargs: dict, model: str, base_url: str | None,
                            thinking: str | None, reasoning_effort: str | None) -> None:
    """卷七十五续五 · 把 UI 的「思考模式 / 推理强度」落到 openai 协议请求参数上。

    默认 (thinking=None/'auto' · effort=None) == 老行为(DeepSeek 开 thinking · 其余不动)·
    保证零回归。 只对【已知接受该参数】的家族/厂商下发·别的静默跳过 → 防未知参数 400:
      - thinking → DeepSeek / GLM(智谱) 认 extra_body.thinking.{enabled|disabled};
      - reasoning_effort → GPT-5 / o 系列 / grok 认顶层 reasoning_effort。

    wish-33624071 (2026-09-14) · 「关」不再只有一条路: 真切到 off 时先问能力声明表
    (provider_presets.resolve_think_off) —— 有 prompt 软开关的模型 (Qwen3 系)
    走 system 注控制词·没通路的如实不动 (UI 已标灰)。 不按厂商穷举 if-else。
    """
    base = (base_url or "").lower()
    ml = (model or "").lower()
    is_deepseek = _uses_deepseek_prefix_cache(base_url, model)
    is_glm = "bigmodel.cn" in base or ml.startswith("glm")
    tv = (thinking or "auto").lower()
    thinking_off = False
    # wish-33624071 · 软开关分流 (必须先于下面两家方言判)· 真切到「关」时才注入
    if tv == "off":
        try:
            from provider_presets import (
                resolve_think_off as _resolve_think_off,
                THINK_OFF_SOFT_PROMPT as _TOK_SOFT,
                THINK_OFF_CHAT_TEMPLATE as _TOK_CT,
            )
            _mode, _token = _resolve_think_off(model, base_url)
        except Exception:
            _mode, _token = "", ""
        if _mode == _TOK_SOFT and _token:
            _inject_reasoning_off_token(kwargs.get("messages"), _token)
            return  # 软开关已把思考关掉·不再下发任何 reasoning 参数
        if _mode == _TOK_CT:
            # wish-acf6e762 · chat template 开关 (Qwen3.8 新模板系 · 本机 fork llama-server 透传)
            # 走 extra_body —— openai SDK 不认未知顶层 kwarg (会 TypeError)
            _eb = kwargs.setdefault("extra_body", {})
            _eb["chat_template_kwargs"] = {"enable_thinking": False}
            thinking_off = True
        elif _mode != "api_param":
            # 用户说「关」但这个模型没有 API 通路 → 至少不主动加思考 (不发 reasoning_effort)
            thinking_off = True
    if is_deepseek or is_glm:
        if tv == "off":
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            thinking_off = True
        elif tv == "on" or (tv == "auto" and is_deepseek):
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        # auto + glm → 不设 · 用厂商默认
    # reasoning_effort · 标准档 → 该模型接受的档 (provider_presets.map_effort_level ·
    #   单一真相源 · wish-4fd607c5 v2): UI 摆通用的标准档·发送端就近映射
    #   (DeepSeek 上 中→高 · GPT-5 上 极高→高)。
    #   wish-3d02d762 校正：不吃这参数的 (GLM·本机) → supported 空 → 永不发 ✓；
    #   未识别模型 → 保守三档 + 默认档为空 —— 用户不选就不发（零回归）；
    #   但用户【主动选档】时会按保守三档就近映射下发（有意设计：让他能试）。
    #   旧文案「认不出的 → 不发」与实现对不上，别照它推理。
    eff = (reasoning_effort or "").strip().lower()
    if eff and not thinking_off:
        try:
            from provider_presets import map_effort_level as _map_effort_level
            _mapped = _map_effort_level(eff, model, base_url)
        except Exception:
            _mapped = eff if eff in ("low", "medium", "high") else None
        if _mapped:
            kwargs["reasoning_effort"] = _mapped


def _loop_openai(
    *, client, model, max_tokens, system, messages,
    confirm, observe, max_iterations, base_url,
    progress=None, cancel_check=None,
    on_message_commit=None,
    allowed_tool_names: set[str] | None = None,
    system_suffix: str = "",
    thinking: str | None = None,
    reasoning_effort: str | None = None,
    pending_messages=None,
) -> tuple[str, list[dict], UsageStats]:
    def _commit(entry: dict) -> None:
        if on_message_commit is None:
            return
        try:
            on_message_commit(entry)
        except Exception:
            logger.warning("openai 循环 _commit 落盘失败 · 增量消息可能丢 (kill -9 风险)", exc_info=True)
    specs = _specs_for_llm(allowed_tool_names)
    tools_param = to_openai_tools(specs) if specs else None

    # wish-8f122254 · DeepSeek 自动 disk cache 修复:
    # 每轮必变的 system_suffix 插在 messages 前 → 前缀匹配全断 → 缓存命中率 65-80%。
    # 修复: DeepSeek 族（官网 / 硅基 / new-api 同名模型）把尾巴 append 到发送副本末尾
    #       (append-only · 历史前缀只增不改)·只进发送副本 · 不写回持久化 messages。
    # 注意: 尾部 new_entries 切片会把 oai_messages 新增内容写回 messages ·
    #       所以 note 用对象引用记下来 · return 前 remove · 防持久化污染。
    _tail_note: dict | None = None
    _tail_in_system = os.environ.get("OPUS_DS_TAIL_IN_SYSTEM") == "1"
    if system_suffix and _uses_deepseek_prefix_cache(base_url, model) and not _tail_in_system:
        try:
            system_payload = _build_openai_system(
                system, system_suffix, base_url, model, suffix_in_system=False)
            _tail_note = {
                "role": "user",
                # wish-eeb8e951 (墨言深修): 前缀明示"不是 BRO 说的话"· 堵 role=user 放大器 —
                # 否则系统注入长得像用户消息 → 历史指令文本容易被当新指令执行
                "content": "[system note · 每轮变化的运行时信息 · 不是 BRO 说的话 · 不要复述这一段]\n" + system_suffix,
            }
        except Exception:
            system_payload = _build_openai_system(system, system_suffix, base_url, model)
            _tail_note = None
    else:
        system_payload = _build_openai_system(system, system_suffix, base_url, model)
    oai_messages: list[dict] = [{"role": "system", "content": system_payload}] + list(messages)
    if _tail_note is not None:
        oai_messages.append(_tail_note)
    total = UsageStats()
    final_text = ""

    # ── 回合内紧急降水位 (wish-a5f77893 · 2026-09-16 · 刀B/C/D) ────────────
    # 事故复盘 (daemon.log 02:24 · turn-8d3): 压缩检查只在回合入口 (:1332) → 高水位
    # 回合内无人降水位 → 动态预算被压到 ~2k → 每 iter 思考吃光·正文空 · 自愈在同一
    # 水位重复 3 次仍空 · 烧 20 iter 才侥幸出话。修法: 预算被挤 (_mt_safe < _squeezed_floor)
    # 时 → 强制压缩 (绕过入口停手/冷却 · 本回合节流 ≤2 次)。
    _uc_state: dict = {"count": 0, "last_iter": -99}

    def _urgent_compact(reason: str, ignore_gap: bool = False) -> bool:
        """紧急降水位: 压缩全部当前消息 + 重建发送列表。返回是否压成功。

        保持切片不变量 oai_messages[1:1+len(messages)]==messages (出口按它回写 messages)。
        ignore_gap: 真·400 溢出场景允许同 iter 再试一次 (仍守每回合 count 上限)。
        """
        nonlocal oai_messages
        if _uc_state["count"] >= _URGENT_COMPACT_MAX:
            return False
        if not ignore_gap and iteration - _uc_state["last_iter"] < _URGENT_COMPACT_GAP:
            return False
        _cur = [e for e in oai_messages[1:] if e is not _tail_note]
        try:
            from workers.memory_compression import auto_compress as _ac
            _new = _ac(list(_cur), client, model, "openai", model_id=model, force=True)
        except Exception as _e:
            logger.warning("[紧急压缩·失败] reason=%s iter=%d: %s (不影响主流程)", reason, iteration, _e)
            _uc_state["count"] = _URGENT_COMPACT_MAX   # 失败别反复试
            return False
        if _new is None or len(_new) >= len(_cur):
            logger.warning("[紧急压缩·无效] reason=%s iter=%d · %d 条未减 (水位压不动)",
                           reason, iteration, len(_cur))
            _uc_state["count"] = _URGENT_COMPACT_MAX
            return False
        _had_tail = _tail_note is not None and any(e is _tail_note for e in oai_messages)
        messages[:] = _new
        oai_messages = [oai_messages[0]] + list(_new)
        if _had_tail:
            oai_messages.append(_tail_note)
        _uc_state["count"] += 1
        _uc_state["last_iter"] = iteration
        logger.warning("[紧急压缩] reason=%s iter=%d · %d→%d 条 (本回合第 %d/%d 次)",
                       reason, iteration, len(_cur), len(_new), _uc_state["count"], _URGENT_COMPACT_MAX)
        return True

    # 卷三十七 · 流式输出 · thinking 模型推荐 stream=True · 让 reasoning 一字一字吐
    # (thinking / reasoning_effort 的开关下沉到 _apply_openai_reasoning · 每轮 kwargs 里应用)

    # 卷三十八 · finish_reason='length' 自动续接计数 · BRO 反馈"撞了 max_tokens 就停了 · 任务没结果"
    # 策略: 检测到 length · 自动注入一条 user 继续指令 · 接着 LLM 把没说完的写完
    # 上限 3 次 · 防无限烧 token (每次 max_tokens 大的话 · 3 次累计输出可达 100K+)
    length_resume_count = 0
    empty_resume_count = 0
    _no_text_streak = 0          # 2026-09-23 · 连续无正文轮数 (无进展保护)

    # 卷四十四 · stuck detection 状态 · 跟踪最近 N 次 tool call signature
    # 同 signature 连续出现 ≥ THRESHOLD 次 · 注入 user 提示让 LLM 反思
    # 注入累计 ≥ CAP 次还在重复 · break (此时是真死循环 · 烧 token 没意义)
    recent_signatures: list[str] = []
    stuck_inject_count = 0

    # 失败熔断器状态 (墨言 094 wish-d2c2aa9a)
    fail_circuit = _FailCircuit()
    circuit_break = False
    _fc_nudge_pending = False

    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        _hb_feed(cancel_check)  # 心跳: 迭代推进 = 有进展 (2026-09-16)
        # 卷三十六 · 头部 check cancel · 避免无谓再开一轮 LLM (省 token)
        if cancel_check is not None and cancel_check():
            if getattr(cancel_check, "stalled", False):
                # 2026-09-16 · 心跳停止 → 给收尾交代(带工具摘要)并落盘 (断案病根: 超时不再冒充"用户取消")
                _done_tools = _collect_recent_tools(oai_messages)
                final_text = ("⏱ 心跳停止（模型/流长时间无响应）· 已安全中断（不是报错 · 也不是你取消的）。"
                              + (("\n已完成的部分:\n" + _done_tools) if _done_tools else ""))
            elif getattr(cancel_check, "timed_out", False):
                # 2026-09-15 修: 后台续场墙钟到点 → 给收尾交代(带工具摘要)并落盘 · 不再闷掉
                _done_tools = _collect_recent_tools(oai_messages)
                final_text = ("⏱ 本轮后台续场到达时长上限 · 已安全中断（不是报错 · 也不是你取消的）。"
                              + (("\n已完成的部分:\n" + _done_tools) if _done_tools else ""))
            else:
                final_text = "[OPUS aborted by BRO]"
            _push(progress, "assistant_text", {"text": final_text, "has_tool_calls": False})
            try:
                _abort_entry = {"role": "assistant", "content": final_text}
                oai_messages.append(_abort_entry)
                _commit(_abort_entry)
                if getattr(cancel_check, "stalled", False) or getattr(cancel_check, "timed_out", False):
                    logger.info("[heartbeat] 中断收尾 · iter=%s · 已补收尾并落盘", iteration)
            except Exception:
                pass
            break
        # 0.9.7 · followup 运行中消息 (P0-3): 每轮迭代头收一次外部塞进来的消息
        # (主对话对运行中分身追加指令) · 注入为 user 消息 · 分身下一轮自然看到。
        if pending_messages is not None:
            try:
                _pending = pending_messages() or []
            except Exception:
                _pending = []
            for _pm in _pending:
                if isinstance(_pm, str) and _pm.strip():
                    oai_messages.append({"role": "user", "content": _pm.strip()})
        # wish-8f122254 · max_tokens 动态封顶:
        # 用户全局 max_tokens 固定占坑 (如 393216) · messages 涨到 ~650K 时
        # messages+completion 超窗口 → 按窗口动态收窄输出预算。
        _mt_safe = max_tokens
        # 判据: “被窗口挤压”而非“用户配置本身小” → min(地板, 配置上限)
        # (code_review 2026-09-16: 配置小 max_tokens 时 _mt_safe 恒 < 地板 → 会每轮白压)
        _squeezed_floor = min(_MT_FLOOR, max_tokens)
        try:
            from workers.memory_compression import _estimate_tokens as _est_tok
            from workers.memory_compression import _get_context_window as _cw_for
            _ctx = _cw_for(model)
            if _ctx and _ctx > 0:
                _est_now = _est_tok(oai_messages)
                _headroom = max(1024, int(_ctx * 0.05))
                _mt_safe = min(max_tokens, max(512, _ctx - _est_now - _headroom))
                # 刀B (wish-a5f77893): 预算被挤到地板下 → 先紧急降水位再算
                # (事故: 被压到 ~2k 硬发 · 全回合空转 · daemon.log 02:24)
                if _mt_safe < _squeezed_floor and _urgent_compact("budget_floor"):
                    _est_now = _est_tok(oai_messages)
                    _mt_safe = min(max_tokens, max(512, _ctx - _est_now - _headroom))
        except Exception:
            _mt_safe = max_tokens
        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=_mt_safe,
            messages=_diet_messages_for_send(oai_messages),
            stream=True,
            stream_options={"include_usage": True},
        )
        if tools_param:
            kwargs["tools"] = tools_param
            kwargs["tool_choice"] = "auto"
        # 卷三十七 → 卷七十五续五 · thinking / reasoning_effort 由 UI 控 (默认 auto == 老行为:
        # DeepSeek 开 thinking · 其余不动)。 helper 只对已知支持的厂商/家族下发 · 防未知参数 400。
        _apply_openai_reasoning(kwargs, model, base_url, thinking, reasoning_effort)

        # 刀4 (wish-a5f77893): provider 报“上下文超长”类 400 → 紧急压缩后重试本 iter
        # (真撞窗的最后兜底 · 与刀B/C/D 的预防互补; Anthropic 路径后续补对称)
        _overflow_retry = 0
        # 2026-09-18 · 两段阈值: 从这里到首个 chunk 之间无法产生心跳 → 进宽阈值期
        _hb_set_awaiting(cancel_check, True)
        _hb_beat_safe(cancel_check)  # 基准重置: 宽阈值从「开始等」算 (code_review 20260918)
        while True:
            try:
                resp = client.chat.completions.create(**kwargs)
                break
            except Exception as _req_e:
                if (
                    _overflow_retry < 2
                    and _is_context_overflow_error(_req_e)
                    and _urgent_compact("overflow_400", ignore_gap=True)
                ):
                    _overflow_retry += 1
                    kwargs["messages"] = _diet_messages_for_send(oai_messages)
                    logger.warning("[400·超长自愈] 已压缩并重试请求 (第 %d 次)", _overflow_retry)
                    continue
                raise

        # 流式累加状态
        text = ""
        reasoning = ""
        tool_calls_acc: dict[int, dict] = {}  # index → {id, name, arguments}
        usage = None
        finish_reason: str | None = None

        # 走 abort path 的两个理由: chunk 内 cancel_check fire / watcher close 引起异常
        _aborted_inline = False

        try:
            with _StreamCancelGuard(resp, cancel_check):
                for chunk in resp:
                    # 2026-09-18 · 首个 chunk 到达 = 退出宽阈值期，恢复严阈值
                    _hb_set_awaiting(cancel_check, False)
                    _hb_feed(cancel_check)  # 心跳: 每个新 chunk = 有进展 (2026-09-16)
                    if cancel_check is not None and cancel_check():
                        try:
                            resp.close()
                        except Exception:
                            pass
                        _aborted_inline = True
                        break

                    ch_usage = getattr(chunk, "usage", None)
                    if ch_usage is not None:
                        usage = ch_usage

                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    delta = getattr(choice, "delta", None)
                    if delta is None:
                        continue

                    rc_delta = getattr(delta, "reasoning_content", None)
                    if rc_delta:
                        reasoning += rc_delta
                        _push(progress, "reasoning_delta", {"text": rc_delta})

                    content_delta = getattr(delta, "content", None)
                    if content_delta:
                        text += content_delta
                        _push(progress, "assistant_delta", {"text": content_delta})

                    tcs_delta = getattr(delta, "tool_calls", None)
                    if tcs_delta:
                        for tcd in tcs_delta:
                            idx = getattr(tcd, "index", 0) or 0
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                            if getattr(tcd, "id", None):
                                tool_calls_acc[idx]["id"] = tcd.id
                            fn = getattr(tcd, "function", None)
                            if fn is not None:
                                if getattr(fn, "name", None):
                                    tool_calls_acc[idx]["name"] = fn.name
                                if getattr(fn, "arguments", None):
                                    tool_calls_acc[idx]["arguments"] += fn.arguments

                    fr = getattr(choice, "finish_reason", None)
                    if fr:
                        finish_reason = fr
        except Exception:
            if cancel_check is not None and cancel_check():
                _aborted_inline = True
            else:
                raise

        if _aborted_inline:
            final_text = text or _aborted_note(cancel_check)
            _push(progress, "assistant_text", {"text": final_text, "has_tool_calls": False})
            # 把已收到的部分保留进 messages 以免丢
            if text or reasoning or tool_calls_acc:
                partial_entry: dict[str, Any] = {"role": "assistant", "content": text}
                if reasoning:
                    partial_entry["reasoning_content"] = reasoning
                oai_messages.append(partial_entry)
                _commit(partial_entry)
            if _tail_note is not None:
                try:
                    oai_messages.remove(_tail_note)  # 按身份摘除 · 不随 new_entries 回写
                except ValueError:
                    pass
            new_entries = oai_messages[1 + len(messages):]
            messages.extend(new_entries)
            return final_text, messages, total

        # 流结束 · 统计 + 拼完整 tool_calls
        if usage is not None:
            creation, read = _extract_openai_cache_usage(usage)
            turn_stats = UsageStats(
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                cache_creation_tokens=creation,
                cache_read_tokens=read,
            )
            total.add(turn_stats)
            # v2 · 真实 usage 喂给压缩层 tokPerChar 校准 (wish-7f0adf2c · best-effort)
            try:
                from workers import memory_compression as _mc
                _mc.note_real_usage(turn_stats.input_tokens, oai_messages)
            except Exception:
                pass
            _push(progress, "usage", {
                "input_tokens": turn_stats.input_tokens,
                "output_tokens": turn_stats.output_tokens,
                "cache_read_tokens": turn_stats.cache_read_tokens,
                "cache_creation_tokens": turn_stats.cache_creation_tokens,
                "iteration": iteration,
            })

        # 把 dict accumulator 拍平成 list · 按 index 排序
        tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc.keys())]

        # 卷三十八 · finish_reason 透给前端 · 让 BRO 看到为什么这轮结束
        # length = 触发了 max_tokens · 经常这种导致 "没做完就停了" 
        # tool_calls = 还有工具要跑 · 正常
        # stop = LLM 自己说完了
        # content_filter = 内容过滤 · 罕见
        # 0.9.x · 同时落日志: 原先只推前端不落盘 · 事后无据可查。
        # 2026-09-14 端到端排查 "思考完没出文字" 时 · daemon.log 里一个字都没有。
        logger.info(
            "[llm] iter=%d finish_reason=%s has_text=%s has_tools=%s reasoning=%d字",
            iteration, finish_reason or "unknown", bool(text), bool(tool_calls),
            len(reasoning) if reasoning else 0,
        )
        _push(progress, "assistant_finish", {
            "iteration": iteration,
            "finish_reason": finish_reason or "unknown",
            "has_text": bool(text),
            "has_tool_calls": bool(tool_calls),
            "reasoning_len": len(reasoning) if reasoning else 0,
        })

        # 2026-09-23 · 无进展保护 (见 MAX_NO_TEXT_STREAK 注释):
        # 连续 N 轮只有 tool_calls、正文零字 → 注入一条「该收口了」的提醒
        if text:
            _no_text_streak = 0
        elif tool_calls:
            _no_text_streak += 1
            if _no_text_streak % MAX_NO_TEXT_STREAK == 0:
                logger.warning(
                    "[无进展·收口提醒] 连续 %d 轮只有工具调用 · 正文零字 (iter=%d) → 注入收口提醒",
                    _no_text_streak, iteration,
                )
                _push(progress, "auto_resume", {
                    "reason": "no_text_streak",
                    "count": _no_text_streak,
                    "max": MAX_NO_TEXT_STREAK,
                    "note": f"连续 {_no_text_streak} 轮只调工具没出正文 · 已提醒先收口",
                })
                # 只进当轮上下文 · 不落盘 (学 deepseek-harness: guard 提醒仅驻留内存)。
                # 落盘会在 BRO 的会话记录里留一条「假 user 消息」· 空回复自愈就有这毛病。
                _nt_nudge = {"role": "user", "content": _NO_TEXT_RESUME_USER}
                oai_messages.append(_nt_nudge)

        # 段落完成事件 · 让前端把流式 bubble "锁定"·准备下一段
        if reasoning:
            _push(progress, "assistant_reasoning_done", {"text": reasoning})
            # 2026-08-14 · 思考过程上卡 (墨言 094 飞书对齐 cc): 飞书卡片接 thinking 事件
            #  (对标 cc-connect EventThinking → ProgressEntryThinking) · 限 1500 字符省 token
            try:
                _push(progress, "thinking", {"text": reasoning[:1500], "has_tool_calls": bool(tool_calls)})
            except Exception:
                pass

        # 卷三十八 · 兜底: reasoning 非空 + content 空 + 无 tool_calls = LLM 想完了没说话
        # 不让前端拿不到 final_text · 给一句解释 · BRO 至少知道发生了什么
        _empty_reply = (not text) and (not tool_calls) and bool(reasoning)
        if _empty_reply and empty_resume_count < MAX_EMPTY_RESUME:
            # 刀C (wish-a5f77893): length 型空回复 = 输出预算被切光 → 同水位重试必然
            # 再空 (事故: iter=1/2/3 连空) → 重试前先降水位·恢复预算。
            if finish_reason == "length" and _mt_safe < _squeezed_floor:
                _urgent_compact("length_empty", ignore_gap=True)
            # 0.9.x · 空回复自愈: 模型把结论说进了 reasoning_content · 正文空。
            # 直接再要一次正文 · 别让 BRO 自己催「给我个总结」。
            empty_resume_count += 1
            logger.warning(
                "[空回复·自愈] 正文空 · finish_reason=%s · reasoning=%d字 · iter=%d → 自动要正文 %d/%d",
                finish_reason, len(reasoning), iteration,
                empty_resume_count, MAX_EMPTY_RESUME,
            )
            _push(progress, "auto_resume", {
                "reason": "empty",
                "count": empty_resume_count,
                "max": MAX_EMPTY_RESUME,
                "note": f"上一轮思考完了没写正文 · 自动要一次第 {empty_resume_count}/{MAX_EMPTY_RESUME} 次",
            })
            _empty_entry = {"role": "assistant", "content": "", "reasoning_content": reasoning}
            oai_messages.append(_empty_entry)
            _commit(_empty_entry)
            _empty_nudge = {"role": "user", "content": _EMPTY_RESUME_USER}
            oai_messages.append(_empty_nudge)
            _commit(_empty_nudge)
            continue
        if _empty_reply:
            # 0.9.x · 空回复现场: 这行就是判据 ——
            #   finish_reason=length → 输出预算被切光 (该查 max_tokens)
            #   finish_reason=stop   → 模型自己收手没说话 (provider 侧行为)
            logger.warning(
                "[空回复] 重试 %d 次仍未拿到正文 · finish_reason=%s · reasoning=%d字 · iter=%d"
                " · 判据: length=预算切光 / stop=模型自己收手",
                empty_resume_count, finish_reason, len(reasoning), iteration,
            )
            text = (
                "（OPUS 思考完了但没出文字回复 · "
                f"reasoning 共 {len(reasoning)} 字 · 上面气泡可展开看）\n\n"
                f"已自动重要 {MAX_EMPTY_RESUME} 次正文仍未拿到 —— 这是模型侧的行为"
                "（不是 max_tokens 不够）。换一个模型、或说一句「继续」都能走下去。"
            )
        elif not text and not tool_calls:
            # 无 reasoning 也无正文 · 极罕见 · 保留旧文案
            text = (
                "（OPUS 思考完了但没出文字回复 · "
                f"reasoning 共 {len(reasoning)} 字 · 上面气泡可展开看）\n\n"
                "可能原因: max_tokens 不够 / DeepSeek 偶发 / 推理后忘了给总结。"
                "可以说「请用中文给我个总结」让他再走一轮。"
            )

        if text:
            _push(progress, "assistant_text", {"text": text, "has_tool_calls": bool(tool_calls)})

        # 落 messages · 卷三十六 reasoning_content 多轮回传
        assistant_entry: dict[str, Any] = {"role": "assistant", "content": text}
        if tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc["id"] or f"call_{iteration}_{i}",
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for i, tc in enumerate(tool_calls)
            ]
        if reasoning:
            assistant_entry["reasoning_content"] = reasoning
        oai_messages.append(assistant_entry)
        _commit(assistant_entry)

        # 卷三十八 · finish_reason='length' 自动续 · 让任务跑出结果不要半路停
        # 触发条件: 本轮 finish='length' · 且没 tool_calls (有 tool_calls 走正常工具循环)
        # · 且续接次数没到上限
        if (
            finish_reason == "length"
            and not tool_calls
            and length_resume_count < MAX_LENGTH_RESUME
        ):
            # 刀C: 预算被切型续接 —— 先降水位 (否则续接还困在小预算里)
            if _mt_safe < _squeezed_floor:
                _urgent_compact("length_resume", ignore_gap=True)
            length_resume_count += 1
            _push(progress, "auto_resume", {
                "reason": "length",
                "count": length_resume_count,
                "max": MAX_LENGTH_RESUME,
                "note": f"上一轮 max_tokens 用光 · 自动续第 {length_resume_count}/{MAX_LENGTH_RESUME} 次",
            })
            resume_user_entry = {
                "role": "user",
                "content": _LENGTH_RESUME_USER,
            }
            oai_messages.append(resume_user_entry)
            _commit(resume_user_entry)
            continue  # 不 break · 进下一轮

        if not tool_calls:
            final_text = text
            break

        # 卷七十四续十五 · 把本轮回复正文暴露给工具(两步法长文档兜底·generate_report/write_file
        # 的 body/content 没传时从这里抓·只对走兜底的弱模型生效·前沿模型传了参数根本不碰)
        try:
            set_current_turn_text(text)
        except Exception:
            pass

        aborted = False
        # 卷五十八续 ⑤ · 整批全只读 AUTO → 并发预跑 (否则 {} · 主循环照常串行)
        _sa_names = []
        for _tc in tool_calls:
            try:
                _a = json.loads(_tc["arguments"] or "{}")
            except json.JSONDecodeError:
                _a = {}
            _rn, _ra = _rewrite_tool_use(_tc["name"], _a)
            _sa_names.append((REGISTRY.get(_rn), _ra, _rn))
        # Grok-2 · 2026-08-27 · 并行预跑必须知道白名单 · 否则白名单外的 AUTO 只读工具
        # 会被先跑掉 (绕过卷七十二拦截) · 白名单由 _maybe_parallel_auto 内部过滤
        parallel_results = _maybe_parallel_auto(_sa_names, progress, allowed_tool_names, cancel_check)

        for idx, tc in enumerate(tool_calls):
            name = tc["name"]
            try:
                args = json.loads(tc["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            name, args = _rewrite_tool_use(name, args)
            spec = REGISTRY.get(name)

            if _should_stub_remaining(aborted, cancel_check):
                if not aborted:
                    aborted = True
                    _trace_abort("stop")
                result = _abort_stub()
                _push(progress, "tool_call", {"name": name, "summary": "(aborted)", "tier": "abort"})
            elif spec is None:
                from agent_tools._desc_budget import unknown_tool_error
                result = ToolResult(ok=False, output="", error=unknown_tool_error(name))
                _push(progress, "tool_call", {"name": name, "summary": "(unknown tool)", "tier": "?"})
            elif allowed_tool_names is not None and name not in allowed_tool_names:
                # 卷七十二 · 白名单越权拦截 (审稿 app 调 run_app 跑 5 分钟内容制作 = 真实触发场景)
                allowed_list = ", ".join(sorted(allowed_tool_names)) or "(empty)"
                result = ToolResult(
                    ok=False, output="",
                    error=f"tool '{name}' not allowed in this app scope · whitelist: {allowed_list}",
                )
                _push(progress, "tool_call", {
                    "name": name,
                    "summary": f"(denied · not in app whitelist) {name}",
                    "tier": "denied",
                })
            else:
                _push(progress, "tool_call", {
                    "name": name,
                    "summary": spec.summarize(args) if hasattr(spec, "summarize") else name,
                    "tier": getattr(spec, "tier", "?"),
                })
                decision = _call_confirm(confirm, spec, args, text, tool_call_id=(tc.get("id") or f"call_{iteration}_{idx}"))
                if decision == "abort":
                    aborted = True
                    _trace_abort("confirm")
                    result = _abort_stub()
                elif decision == "skip":
                    result = ToolResult(
                        ok=False, output="",
                        error="user declined to run this tool; try a different approach.",
                    )
                elif decision == "explain":
                    result = ToolResult(ok=False, output="", error=_EXPLAIN_PROMPT)
                elif isinstance(decision, str) and decision.startswith("reject:"):
                    result = ToolResult(ok=False, output="", error=decision[7:].strip())
                else:
                    schema_err = _validate_args(args, spec.input_schema, name)
                    if schema_err is not None:
                        result = ToolResult(ok=False, output="", error=schema_err)
                    else:
                        _pet_write_activity(name)
                        try:
                            # 卷五十八续 ⑤ · 已并发预跑过就直接取·否则当场跑
                            if idx in parallel_results:
                                result = parallel_results[idx]
                            else:
                                # 卷五十八 · wish-f30d571d · 设进度钩子 · 长跑工具可调 push_tool_progress() 推 SSE
                                try:
                                    result = _run_tool(spec, args, progress, cancel_check)
                                except Exception as e:
                                    result = ToolResult(ok=False, output="", error=f"{type(e).__name__}: {e}")
                        except Exception as e:
                            result = ToolResult(ok=False, output="", error=f"{type(e).__name__}: {e}")
                        try:
                            _pet_write_pulse_end(name, ok=result.ok, summary=_pulse_summary(result))
                        except Exception:
                            pass

            if (not aborted) and (_is_user_abort(result) or _cancel_requested(cancel_check)):
                aborted = True
                _trace_abort("stop")

            _imgs = _take_image_urls(result)
            _hits = _take_hits(result)
            _sniffed = _take_open_paths(result)      # 总是跑：负责剥掉旧标记（不污染喂给 LLM 的内容）
            _open_paths = _take_declared_stage(result) or _sniffed
            _note_stage(result, _open_paths)         # 统一补一句人话（工具那层不再各自写）
            _open_path = _open_paths[-1] if _open_paths else ""
            for _p in _open_paths:
                try:
                    from workers.session_docs import bind_runtime
                    bind_runtime(_p)
                except Exception:
                    pass
            _push(progress, "tool_result", {
                "name": name,
                "ok": result.ok,
                "error": result.error or "",
                "preview": _result_preview(result, tool_name=name),
                "open_path": _open_path,
                "open_paths": _open_paths,
                "images": _imgs,
                "hits": _hits,
            })

            if observe and spec is not None:
                observe(spec, args, result)
            try:
                from workers.playbook_observe import observe_tool as _pb_obs
                if spec is not None:
                    _pb_obs(spec, args, result)
            except Exception:
                pass

            tool_entry = {
                "role": "tool",
                "tool_call_id": tc["id"] or "",
                "content": _localize_tool_content(name, result.to_string()),
            }
            oai_messages.append(tool_entry)
            _commit(tool_entry)

            # 失败熔断器 (墨言 094 wish-d2c2aa9a) · 同类错误连续失败 → nudge → 再撞硬 break
            _fc_action = fail_circuit.observe(result)
            if _fc_action == "nudge":
                _fc_nudge_pending = True
            elif _fc_action == "break":
                circuit_break = True
                break

            # 卷四十四 · stuck detection · 把这次 tool call signature 加进滚动窗口
            sig = _tool_signature(name, tc.get("arguments", ""))
            if sig:                     # 透明工具 (记账类) 既不增也不重置计数
                recent_signatures.append(sig)
                if len(recent_signatures) > _STUCK_WINDOW:
                    recent_signatures.pop(0)

        if aborted:
            _seen = {m.get("tool_call_id") for m in oai_messages if m.get("role") == "tool"}
            for _m in oai_messages:
                if _m.get("role") == "assistant" and _m.get("tool_calls"):
                    for _tc in _m["tool_calls"]:
                        _tid = (_tc.get("id") or "") if isinstance(_tc, dict) else ""
                        if _tid and _tid not in _seen:
                            _tm = {
                                "role": "tool",
                                "tool_call_id": _tid,
                                "content": "aborted by user",
                            }
                            oai_messages.append(_tm)
                            _commit(_tm)
                            _seen.add(_tid)
            final_text = text or "[OPUS aborted by BRO]"
            break
        if circuit_break:
            # 补齐 batch 中未执行的 tool_call 响应 (防消息序列违规 · 跨 turn resume 400)
            _seen = {m.get("tool_call_id") for m in oai_messages if m.get("role") == "tool"}
            for _m in oai_messages:
                if _m.get("role") == "assistant" and _m.get("tool_calls"):
                    for _tc in _m["tool_calls"]:
                        _tid = (_tc.get("id") or "") if isinstance(_tc, dict) else ""
                        if _tid and _tid not in _seen:
                            _tm = {"role": "tool", "tool_call_id": _tid,
                                   "content": f"[失败熔断器] 未执行: 同类错误已连续失败 {fail_circuit.streak} 次·已熔断停手"}
                            oai_messages.append(_tm)
                            _commit(_tm)
                            _seen.add(_tid)
            final_text = _collect_partial_output(oai_messages) + _FAIL_CIRCUIT_BREAK_PROMPT.format(
                count=fail_circuit.streak, category=fail_circuit.current)
            _push(progress, "assistant_text", {"text": final_text, "has_tool_calls": False})
            _ce = {"role": "assistant", "content": final_text}
            oai_messages.append(_ce)
            _commit(_ce)
            break
        if _fc_nudge_pending:
            _fc_nudge_pending = False
            # streak 已被成功/换类重置 → nudge 过期 · 丢弃 (防 "连续 0 次错误 (None)" 错误文案)
            if fail_circuit.streak >= _FAIL_CIRCUIT_AT:
                _fn = {"role": "user", "content": _FAIL_CIRCUIT_NUDGE_PROMPT.format(
                    count=fail_circuit.streak, category=fail_circuit.current)}
                oai_messages.append(_fn)
                _commit(_fn)

        # 卷四十四 · stuck detection · 检测【连续】同 signature ≥ THRESHOLD 次才算死循环
        # 2026-08-09 (wish-2eed044a): 从"窗口内累计计数"改为"连续尾部计数"——
        #   真死循环 = 连续同调用拿同样结果；穿插读再回来重复是正常数据收集，不该拦。
        #   根因: _tool_signature 只取 args 前 120 字符 · 同工具多次不同调用 args 开头
        #   相似（如 {"code": "import ..."}）会被误判成同一 signature · 累计计数就误报。
        if recent_signatures:
            top_sig, top_count = _stuck_tail_count(recent_signatures)
            action = _stuck_action(top_count, stuck_inject_count)
            if action == "nudge":
                stuck_inject_count += 1
                _push(progress, "stuck_detected", {
                    "signature": top_sig,
                    "repeat": top_count,
                    "window": len(recent_signatures),
                    "inject_count": stuck_inject_count,
                    "cap": _STUCK_INJECT_CAP,
                })
                nudge_entry = {
                    "role": "user",
                    "content": _STUCK_NUDGE_PROMPT.format(
                        signature=top_sig,
                        repeat=top_count,
                        window=len(recent_signatures),
                    ),
                }
                oai_messages.append(nudge_entry)
                _commit(nudge_entry)
                recent_signatures.clear()
                continue
            if action == "break":
                final_text = _stuck_break_text(top_sig, top_count, len(recent_signatures))
                _push(progress, "assistant_text", {"text": final_text, "has_tool_calls": False})
                stuck_entry = {"role": "assistant", "content": final_text}
                oai_messages.append(stuck_entry)
                _commit(stuck_entry)
                break
    else:
        # 卷四十三 · 撞 max_iterations 时·之前只设了局部 final_text·没 push 给前端
        # 也没 commit 到 oai_messages·BRO 看到的是"OPUS 安静地停下"——一脸懵
        # 现在: push assistant_text + commit 一条 assistant entry · 让 BRO 看到为什么停了
        final_text = (
            f"[OPUS 撞了 max_iterations={max_iterations} 上限 · 自动停下避免死循环]\n\n"
            f"我跑了 {iteration} 轮工具循环还没收尾·BRO 你可以:\n"
            f"  - 让我继续 (说\"继续\" / \"接着干\") · 我会从断点恢复\n"
            f"  - 看 session jsonl 排查是不是走了死路\n"
            f"  - 把 max_iterations 调更大 (设置面板里可以加)"
        )
        _push(progress, "assistant_text", {"text": final_text, "has_tool_calls": False})
        max_entry: dict[str, Any] = {"role": "assistant", "content": final_text}
        oai_messages.append(max_entry)
        _commit(max_entry)

    if _tail_note is not None:
        try:
            oai_messages.remove(_tail_note)  # 按身份摘除 · 不随 new_entries 回写
        except ValueError:
            pass
    new_entries = oai_messages[1 + len(messages):]
    messages.extend(new_entries)
    return final_text, messages, total


# ---------- Anthropic-native loop ----------

def _loop_anthropic(
    *, client, model, max_tokens, system, messages,
    confirm, observe, max_iterations,
    progress=None, cancel_check=None,
    on_message_commit=None,
    allowed_tool_names: set[str] | None = None,
    system_suffix: str = "",
    thinking: str | None = None,
    reasoning_effort: str | None = None,
    pending_messages=None,
) -> tuple[str, list[dict], UsageStats]:
    def _commit(entry: dict) -> None:
        if on_message_commit is None:
            return
        try:
            on_message_commit(entry)
        except Exception:
            logger.warning("anthropic 循环 _commit 落盘失败 · 增量消息可能丢 (kill -9 风险)", exc_info=True)
    specs = _specs_for_llm(allowed_tool_names)
    tools_param = to_anthropic_tools(specs) if specs else None

    # Anthropic 原生：system 用 list-of-blocks。
    # 3b · 缓存断点只打在「稳定前缀」块上 (cache 覆盖 tools + 稳定 system·因为处理顺序
    # 是 tools→system→messages·断点前的全进缓存)。易变尾巴 (telemetry/提示) 单独成块·
    # 不带 cache_control → 尾巴每轮变也不会冲掉灵魂+tools 的缓存 (省钱关键)。
    system_blocks = [
        {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
    ]
    if system_suffix:
        system_blocks.append({"type": "text", "text": system_suffix})

    ant_messages: list[dict] = list(messages)
    total = UsageStats()
    final_text = ""

    # 失败熔断器状态 (墨言 094 wish-d2c2aa9a · 对称 OpenAI 路径)
    fail_circuit = _FailCircuit()
    circuit_break = False
    _fc_nudge_pending = False
    recent_signatures: list[str] = []
    stuck_inject_count = 0
    length_resume_count = 0
    empty_resume_count = 0
    _no_text_streak = 0          # 2026-09-23 · 连续无正文轮数 (无进展保护)

    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        _hb_feed(cancel_check)  # 心跳: 迭代推进 = 有进展 (2026-09-16)
        if cancel_check is not None and cancel_check():
            if getattr(cancel_check, "stalled", False):
                # 2026-09-16 · 心跳停止 → 给收尾交代(带工具摘要)并落盘
                _done_tools = _collect_recent_tools(ant_messages)
                final_text = ("⏱ 心跳停止（模型/流长时间无响应）· 已安全中断（不是报错 · 也不是你取消的）。"
                              + (("\n已完成的部分:\n" + _done_tools) if _done_tools else ""))
            elif getattr(cancel_check, "timed_out", False):
                # 2026-09-15 修: 同 openai 路径 · 墙钟到点给收尾交代
                _done_tools = _collect_recent_tools(ant_messages)
                final_text = ("⏱ 本轮后台续场到达时长上限 · 已安全中断（不是报错 · 也不是你取消的）。"
                              + (("\n已完成的部分:\n" + _done_tools) if _done_tools else ""))
            else:
                final_text = "[OPUS aborted by BRO]"
            _push(progress, "assistant_text", {"text": final_text, "has_tool_calls": False})
            try:
                _abort_entry = {"role": "assistant", "content": final_text}
                ant_messages.append(_abort_entry)
                _commit(_abort_entry)
                if getattr(cancel_check, "stalled", False) or getattr(cancel_check, "timed_out", False):
                    logger.info("[heartbeat] 中断收尾 · iter=%s · 已补收尾并落盘", iteration)
            except Exception:
                pass
            break
        # 0.9.7 · followup 运行中消息 (与 openai 循环同款)
        if pending_messages is not None:
            try:
                _pending = pending_messages() or []
            except Exception:
                _pending = []
            for _pm in _pending:
                if isinstance(_pm, str) and _pm.strip():
                    ant_messages.append({"role": "user", "content": _pm.strip()})
        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=_diet_messages_for_send(ant_messages),
        )
        if tools_param:
            kwargs["tools"] = tools_param
        # 卷七十五续五 · Claude extended thinking · 仅当 UI 显式开 (thinking='on')。
        # budget_tokens 必须 ≥1024 且 < max_tokens · 取一半但留够可见输出。 auto/off = 老行为(不开)。
        if (thinking or "").lower() == "on":
            _budget = max(1024, min(max_tokens - 1024, max_tokens // 2))
            if _budget >= 1024:
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": _budget}

        kwargs["stream"] = True
        # 2026-09-18 · 两段阈值 (与 openai 路径对称 · code_review 20260918):
        #   非流式发起时到首个 event 之间同样无心跳可喂 → 进宽阈值期
        _hb_set_awaiting(cancel_check, True)
        _hb_beat_safe(cancel_check)  # 基准重置: 宽阈值从「开始等」算
        resp = client.messages.create(**kwargs)
        text, tool_use_blocks, turn_stats, stop_reason, _aborted_inline = _consume_anthropic_stream(
            resp, cancel_check, progress,
        )
        if _aborted_inline:
            final_text = text or _aborted_note(cancel_check)
            _push(progress, "assistant_text", {"text": final_text, "has_tool_calls": False})
            if text or tool_use_blocks:
                _partial = []
                if text:
                    _partial.append({"type": "text", "text": text})
                for _tu in tool_use_blocks:
                    _partial.append({
                        "type": "tool_use",
                        "id": _tu.id,
                        "name": _tu.name,
                        "input": _tu.input or {},
                    })
                _pe = {"role": "assistant", "content": _partial}
                ant_messages.append(_pe)
                _commit(_pe)
            break
        total.add(turn_stats)
        try:
            from workers import memory_compression as _mc
            _mc.note_real_usage(turn_stats.input_tokens, ant_messages)
        except Exception:
            pass
        _push(progress, "usage", {
            "input_tokens": turn_stats.input_tokens,
            "output_tokens": turn_stats.output_tokens,
            "cache_read_tokens": turn_stats.cache_read_tokens,
            "cache_creation_tokens": turn_stats.cache_creation_tokens,
            "iteration": iteration,
        })

        # 0.9.x · 空回复自愈 (对称 OpenAI 路径 · 2026-09-14)
        # 没正文也没 tool_use = 这一轮模型什么都没给 · 直接再要一次 · 别让 BRO 空等
        if (not text) and (not tool_use_blocks) and empty_resume_count < MAX_EMPTY_RESUME:
            empty_resume_count += 1
            logger.warning(
                "[空回复·自愈] 正文空 · stop_reason=%s · iter=%d → 自动要正文 %d/%d",
                stop_reason, iteration, empty_resume_count, MAX_EMPTY_RESUME,
            )
            _push(progress, "auto_resume", {
                "reason": "empty",
                "count": empty_resume_count,
                "max": MAX_EMPTY_RESUME,
                "note": f"上一轮没写正文 · 自动要一次第 {empty_resume_count}/{MAX_EMPTY_RESUME} 次",
            })
            ant_messages.append({"role": "assistant", "content": []})
            _commit({"role": "assistant", "content": []})
            ant_messages.append({"role": "user", "content": _EMPTY_RESUME_USER})
            _commit({"role": "user", "content": _EMPTY_RESUME_USER})
            continue
        if (not text) and (not tool_use_blocks):
            logger.warning(
                "[空回复] 重试 %d 次仍未拿到正文 · stop_reason=%s · iter=%d",
                empty_resume_count, stop_reason, iteration,
            )
            text = (
                "（OPUS 思考完了但没出文字回复 · 上面气泡可展开看）\n\n"
                f"已自动重试 {MAX_EMPTY_RESUME} 次正文仍未拿到 —— 模型侧行为，"
                "换一个模型或说一句「继续」都能走下去。"
            )

        if text:
            _push(progress, "assistant_text", {"text": text, "has_tool_calls": bool(tool_use_blocks)})

        _content_out = []
        if text:
            _content_out.append({"type": "text", "text": text})
        for _tu in tool_use_blocks:
            _content_out.append({
                "type": "tool_use",
                "id": _tu.id,
                "name": _tu.name,
                "input": _tu.input or {},
            })
        ant_assistant_entry = {"role": "assistant", "content": _content_out}
        ant_messages.append(ant_assistant_entry)
        _commit(ant_assistant_entry)

        if (
            stop_reason == "max_tokens"
            and not tool_use_blocks
            and length_resume_count < MAX_LENGTH_RESUME
        ):
            length_resume_count += 1
            _push(progress, "auto_resume", {
                "reason": "length",
                "count": length_resume_count,
                "max": MAX_LENGTH_RESUME,
                "note": f"上一轮 max_tokens 用光 · 自动续第 {length_resume_count}/{MAX_LENGTH_RESUME} 次",
            })
            ant_messages.append({"role": "user", "content": _LENGTH_RESUME_USER})
            _commit(ant_messages[-1])
            continue

        if stop_reason != "tool_use" or not tool_use_blocks:
            final_text = text
            break

        # 卷七十四续十五 · 把本轮回复正文暴露给工具(两步法长文档兜底·同 OpenAI 路)
        try:
            set_current_turn_text(text)
        except Exception:
            pass

        tool_results: list[dict] = []
        aborted = False
        # 卷五十八续 ⑤ · 整批全只读 AUTO → 并发预跑 (否则 {} · 主循环照常串行)
        _sa_ant = []
        for _tu in tool_use_blocks:
            _rn, _ra = _rewrite_tool_use(_tu.name, _tu.input or {})
            _sa_ant.append((REGISTRY.get(_rn), _ra, _rn))
        parallel_results = _maybe_parallel_auto(
            _sa_ant,
            progress,
            allowed_tool_names,
            cancel_check,
        )
        for idx, tu in enumerate(tool_use_blocks):
            name, args = _rewrite_tool_use(tu.name, tu.input or {})
            spec = REGISTRY.get(name)

            if _should_stub_remaining(aborted, cancel_check):
                if not aborted:
                    aborted = True
                    _trace_abort("stop")
                result = _abort_stub()
                _push(progress, "tool_call", {"name": name, "summary": "(aborted)", "tier": "abort"})
            elif spec is None:
                from agent_tools._desc_budget import unknown_tool_error
                result = ToolResult(ok=False, output="", error=unknown_tool_error(name))
                _push(progress, "tool_call", {"name": name, "summary": "(unknown tool)", "tier": "?"})
            elif allowed_tool_names is not None and name not in allowed_tool_names:
                # 卷七十二 · 白名单越权拦截 (审稿 app 调 run_app 跑 5 分钟内容制作 = 真实触发场景)
                allowed_list = ", ".join(sorted(allowed_tool_names)) or "(empty)"
                result = ToolResult(
                    ok=False, output="",
                    error=f"tool '{name}' not allowed in this app scope · whitelist: {allowed_list}",
                )
                _push(progress, "tool_call", {
                    "name": name,
                    "summary": f"(denied · not in app whitelist) {name}",
                    "tier": "denied",
                })
            else:
                _push(progress, "tool_call", {
                    "name": name,
                    "summary": spec.summarize(args) if hasattr(spec, "summarize") else name,
                    "tier": getattr(spec, "tier", "?"),
                })
                decision = _call_confirm(confirm, spec, args, text, tool_call_id=getattr(tu, "id", "") or "")
                if decision == "abort":
                    aborted = True
                    _trace_abort("confirm")
                    result = _abort_stub()
                elif decision == "skip":
                    result = ToolResult(
                        ok=False, output="",
                        error="user declined to run this tool; try a different approach.",
                    )
                elif decision == "explain":
                    result = ToolResult(ok=False, output="", error=_EXPLAIN_PROMPT)
                elif isinstance(decision, str) and decision.startswith("reject:"):
                    result = ToolResult(ok=False, output="", error=decision[7:].strip())
                else:
                    schema_err = _validate_args(args, spec.input_schema, name)
                    if schema_err is not None:
                        result = ToolResult(ok=False, output="", error=schema_err)
                    else:
                        _pet_write_activity(tu.name)
                        try:
                            # 卷五十八续 ⑤ · 已并发预跑过就直接取·否则当场跑
                            if idx in parallel_results:
                                result = parallel_results[idx]
                            else:
                                try:
                                    result = _run_tool(spec, args, progress, cancel_check)
                                except Exception as e:
                                    result = ToolResult(ok=False, output="", error=f"{type(e).__name__}: {e}")
                        except Exception as e:
                            result = ToolResult(ok=False, output="", error=f"{type(e).__name__}: {e}")
                        try:
                            _pet_write_pulse_end(tu.name, ok=result.ok, summary=_pulse_summary(result))
                        except Exception:
                            pass

            if (not aborted) and (_is_user_abort(result) or _cancel_requested(cancel_check)):
                aborted = True
                _trace_abort("stop")

            _imgs = _take_image_urls(result)
            _hits = _take_hits(result)
            _sniffed = _take_open_paths(result)      # 总是跑：负责剥掉旧标记（不污染喂给 LLM 的内容）
            _open_paths = _take_declared_stage(result) or _sniffed
            _note_stage(result, _open_paths)         # 统一补一句人话（工具那层不再各自写）
            _open_path = _open_paths[-1] if _open_paths else ""
            for _p in _open_paths:
                try:
                    from workers.session_docs import bind_runtime
                    bind_runtime(_p)
                except Exception:
                    pass
            _push(progress, "tool_result", {
                "name": tu.name,
                "ok": result.ok,
                "error": result.error or "",
                "preview": _result_preview(result, tool_name=tu.name),
                "open_path": _open_path,
                "open_paths": _open_paths,
                "images": _imgs,
                "hits": _hits,
            })

            if observe and spec is not None:
                observe(spec, args, result)
            try:
                from workers.playbook_observe import observe_tool as _pb_obs
                if spec is not None:
                    _pb_obs(spec, args, result)
            except Exception:
                pass

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": _localize_tool_content(tu.name, result.to_string()),
                "is_error": not result.ok,
            })

            _sig_args = json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args or "")
            _sig = _tool_signature(name, _sig_args)
            if _sig:                    # 透明工具 (记账类) 既不增也不重置计数
                recent_signatures.append(_sig)
                if len(recent_signatures) > _STUCK_WINDOW:
                    recent_signatures.pop(0)

            # 失败熔断器 (墨言 094 wish-d2c2aa9a) · 同类错误连续失败 → nudge 合并进 tool_results → 再撞硬 break
            _fc_action = fail_circuit.observe(result)
            if _fc_action == "nudge":
                _fc_nudge_pending = True
            elif _fc_action == "break":
                circuit_break = True
                break

        if aborted:
            # 附带修 (墨言 094 wish-d2c2aa9a ①): Anthropic 无 session_repair 兜底 · 回填已收集结果 + 补未执行 tool_use 防悬空
            _used = {tr.get("tool_use_id") for tr in tool_results}
            for _tu in tool_use_blocks:
                _bid = getattr(_tu, "id", "") or ""
                if _bid and _bid not in _used:
                    tool_results.append({
                        "type": "tool_result", "tool_use_id": _bid,
                        "content": "[OPUS aborted by BRO]",
                        "is_error": True,
                    })
                    _used.add(_bid)
            if tool_results:
                _ab_entry = {"role": "user", "content": tool_results}
                ant_messages.append(_ab_entry)
                _commit(_ab_entry)
            final_text = text or "[OPUS aborted by BRO]"
            break
        if circuit_break:
            # 补齐 batch 中未执行的 tool_use 的 tool_result block (防消息序列违规 · 跨 turn resume 400)
            _used = {tr.get("tool_use_id") for tr in tool_results}
            for _m in ant_messages:
                if _m.get("role") == "assistant" and isinstance(_m.get("content"), list):
                    for _b in _m["content"]:
                        if isinstance(_b, dict) and _b.get("type") == "tool_use":
                            _bid = _b.get("id") or ""
                            if _bid and _bid not in _used:
                                tool_results.append({
                                    "type": "tool_result", "tool_use_id": _bid,
                                    "content": f"[失败熔断器] 未执行: 同类错误已连续失败 {fail_circuit.streak} 次·已熔断停手",
                                    "is_error": True,
                                })
                                _used.add(_bid)
            ant_tool_entry = {"role": "user", "content": tool_results}
            ant_messages.append(ant_tool_entry)
            _commit(ant_tool_entry)
            final_text = _collect_partial_output(ant_messages) + _FAIL_CIRCUIT_BREAK_PROMPT.format(
                count=fail_circuit.streak, category=fail_circuit.current)
            _push(progress, "assistant_text", {"text": final_text, "has_tool_calls": False})
            _ce = {"role": "assistant", "content": final_text}
            ant_messages.append(_ce)
            _commit(_ce)
            break

        ant_tool_entry = {"role": "user", "content": tool_results}
        if _fc_nudge_pending:
            _fc_nudge_pending = False
            # streak 已被成功/换类重置 → nudge 过期 · 丢弃 (防 "连续 0 次错误 (None)" 错误文案)
            if fail_circuit.streak >= _FAIL_CIRCUIT_AT:
                # Anthropic 消息要求 role 交替 · nudge 必须与 tool_results 合并进同一条 user (不能单独插 user)
                ant_tool_entry["content"] = tool_results + [{
                    "type": "text",
                    "text": _FAIL_CIRCUIT_NUDGE_PROMPT.format(
                        count=fail_circuit.streak, category=fail_circuit.current),
                }]
        _stuck_nudge = False
        _stuck_break = False
        _top_sig, _top_count = "", 0
        if recent_signatures:
            _top_sig, _top_count = _stuck_tail_count(recent_signatures)
            _st_act = _stuck_action(_top_count, stuck_inject_count)
            _stuck_nudge = _st_act == "nudge"
            _stuck_break = _st_act == "break"
        if _stuck_nudge:
            stuck_inject_count += 1
            _push(progress, "stuck_detected", {
                "signature": _top_sig,
                "repeat": _top_count,
                "window": len(recent_signatures),
                "inject_count": stuck_inject_count,
                "cap": _STUCK_INJECT_CAP,
            })
            _nudge = {
                "type": "text",
                "text": _STUCK_NUDGE_PROMPT.format(
                    signature=_top_sig,
                    repeat=_top_count,
                    window=len(recent_signatures),
                ),
            }
            _cur = ant_tool_entry["content"]
            ant_tool_entry["content"] = (list(_cur) if isinstance(_cur, list) else [{"type": "text", "text": str(_cur)}]) + [_nudge]
            ant_messages.append(ant_tool_entry)
            _commit(ant_tool_entry)
            recent_signatures.clear()
            continue
        ant_messages.append(ant_tool_entry)
        _commit(ant_tool_entry)
        if _stuck_break:
            final_text = _stuck_break_text(_top_sig, _top_count, len(recent_signatures))
            _push(progress, "assistant_text", {"text": final_text, "has_tool_calls": False})
            _se = {"role": "assistant", "content": final_text}
            ant_messages.append(_se)
            _commit(_se)
            break
    else:
        # 卷四十三 · 同 OpenAI 路径修法 · 撞 max_iterations 时 push + commit 让前端看到
        final_text = (
            f"[OPUS 撞了 max_iterations={max_iterations} 上限 · 自动停下避免死循环]\n\n"
            f"我跑了 {iteration} 轮工具循环还没收尾·BRO 你可以:\n"
            f"  - 让我继续 (说\"继续\" / \"接着干\") · 我会从断点恢复\n"
            f"  - 看 session jsonl 排查是不是走了死路\n"
            f"  - 把 max_iterations 调更大 (设置面板里可以加)"
        )
        _push(progress, "assistant_text", {"text": final_text, "has_tool_calls": False})
        max_entry: dict[str, Any] = {"role": "assistant", "content": final_text}
        ant_messages.append(max_entry)
        _commit(max_entry)

    new_entries = ant_messages[len(messages):]
    messages.extend(new_entries)
    return final_text, messages, total


def _serialize_anthropic_block(block: Any) -> dict:
    if block.type == "text":
        return {"type": "text", "text": block.text}
    elif block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    else:
        return {"type": block.type}
