"""
workers/memory_compression.py
=============================

压缩层核心——自动 session 摘要 + token budget 控制。

设计（wish-58af621e · 卷三十五）：
  这是 Daemonkey 的"自动记忆压缩"基础设施。
  - `token_budget_check()`  · 判断该不该压缩（消息数阈值 + cooldown）
  - `auto_compress()`        · 真正动手压缩，返回新的 messages 列表
  - `extract_key_facts()`    · 从摘要里用规则提取关键事实

  手动触发（summarize_session 工具）和自动钩子（tool_loop 入口）共用这套函数。

  wish-83fe7c7b · 卷五十四 · 2026-06-03:
    决定 1 → 已废弃。触发改为按 token 预算 + 模型窗口动态算。
    决定 2：压缩逻辑从 summarize_session.py 搬过来，不重写
    决定 3：摘要落 sessions/{sid}.summary.json，为 FTS5 长期记忆打底
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("opus.memory_compression")


# ---------- v3 (wish-273d3d3f · ③) · 参数读取 ----------
# DSH 原版是「写错不让启动」(库), 我们是长跑服务 → 翻译成
# 「大声报错 + 拒绝生效 + 回退安全值」: 错误立刻可见可追溯, 而不是悄悄退回默认。
def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        logger.error("[压缩参数] %s=%r 不是整数 · 已回退 %s (改好 .env 后重启生效)",
                     name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        logger.error("[压缩参数] %s=%r 不是数字 · 已回退 %s (改好 .env 后重启生效)",
                     name, raw, default)
        return default


# ---------- 常量 ----------

DEFAULT_KEEP_LAST_N = 8          # 保留最近 N 条不压缩（模型窗口未知时 fallback）
MIN_KEEP_LAST_N = 4              # 自适应 keep_last_n 硬下限
MAX_KEEP_LAST_N = 20             # 自适应 keep_last_n 硬上限
MIN_MESSAGES_TO_COMPRESS = 12    # 总数少于此不压缩（工具手动触发用）
AUTO_COMPRESS_THRESHOLD = 30     # 遗留常量 · 摘要开火不再数条数（认不出窗户走绝对线）
COOLDOWN_TURNS = 5               # 两次自动压缩之间至少隔 N 轮
_TOK_SAFETY_MULT = 1.25          # 估算保守系数 · 防跨 tokenizer 低估 (DeepSeek tokenizer ≠ cl100k_base)
MAX_RENDER_CHARS = 120000         # 摘要 LLM 输入上限 (v2: 60K→120K · 超限保尾弃头)
DEFAULT_WINDOW_RATIO = 0.8       # 默认触发线: 窗口占比 (v3 2026-09-19: 0.7→0.8 · BRO 拍板。少压=少一次压缩后的 KV cache 重建)

# ---------- v2 · Reasonix 移植 (compact.go/prune.go · wish-7f0adf2c) ----------
SUMMARY_TAG_OPEN  = "<compaction-summary>"
SUMMARY_TAG_CLOSE = "</compaction-summary>"
PRUNED_MARKER = "[已修剪工具结果 — "
MIN_FOLD_TOKENS = 400            # 经济性: 可折叠区低于此 token 不值一次摘要调用
TAIL_TOKEN_BUDGET = _env_int("OPUS_COMPACT_TAIL_TOKENS", 16384)
TAIL_MAX_WINDOW_FRAC = 0.5       # 尾部 token 预算不超窗口此比例
PRUNE_MIN_CHARS = _env_int("OPUS_PRUNE_MIN_CHARS", 1024)
PRUNE_RATIO = _env_float("OPUS_COMPACT_PRUNE_RATIO", 0.6)  # 先修剪档
PIN_FIRST_USER_MAX_TOKENS = 1500
PIN_FIRST_USER_WINDOW_FRAC = 0.15
MAX_CONSECUTIVE_COMPACTS = 2     # 连续压缩仍超阈值 → 暂停自动压缩 (防每轮重建缓存)
EMERGENCY_BREAK_TURNS = _env_int("OPUS_COMPACT_EMERGENCY_TURNS", 6)  # wish-a5f77893 刀A: 停手后距上次 ≥N 轮 → 紧急豁免一次 (防永久停手 · 事故 246.8k)
_TOK_PER_CHAR_FALLBACK = 0.35    # CJK 偏多·介于 Go 0.25 与 1.0 之间
DEFAULT_ABS_CAP_TOKENS = 256_000  # 0.8.8 · 压缩绝对线: 大窗口(1M)模型普通会话到不了 70% → 按体验拐点硬触发
TAIL_USER_TURNS = _env_int("OPUS_TAIL_USER_TURNS", 2)  # 最近 N 个 user 回合原文保活 (OpenCode DEFAULT_TAIL_TURNS)
USER_VERBATIM_BUDGET = _env_int("OPUS_USER_VERBATIM_TOKENS", 30000)  # wish-e72cc18a 刀1/2: 用户原话逐字保留预算(最近 N tok) · 更早的转摘要 + 原件归档可召回 · 0=禁用(回到旧的“永不摘要”)
DIGEST_BUDGET_TOKENS = _env_int("OPUS_DIGEST_TOKENS", 20000)  # wish-e72cc18a 刀1/2: 旧压缩摘要(digest)保留预算 · 超出部分交回摘要器吸收(提示词规则9)· 0=禁用(旧“所有 digest 永久保留”)
PRUNE_PROTECT_TOKENS = _env_int("OPUS_PRUNE_PROTECT_TOKENS", 30000)  # wish-a5f77893 刀2: 最近 N tok 内不剪 (对齐 OpenCode PRUNE_PROTECT=40K 思路)
PRUNE_HISTORY_PRESSURE = _env_int("OPUS_PRUNE_HISTORY_TOKENS", 40000)  # 历史过这线先免费剪工具
MIN_PRUNE_SAVED_CHARS = _env_int("OPUS_PRUNE_MIN_SAVED_CHARS", 40000)  # 省不够就不动盘 (护缓存)

# ---------- v3 (wish-98d77aaf) · 保留预算双向钳制 ----------
# 三个保留预算原是纯绝对值(30k/20k/16k) · 实测占比:
#   128K 窗口 → 三项合计 51.9% · 压完几乎没省空间 (小窗爆)
#   1M   窗口 → 三项合计  6.6% · 早期原话被压光 (大窗降智)
#   256K      → 25.9% · 甜区 —— 但这是巧合不是设计
# 改为按窗口双向钳制: 上界防小窗爆 · 下界防大窗降智。
# 数值刻意选在 256K 下与改前【逐位相等】→ 现状零变化。
USER_VERBATIM_MIN_FRAC = _env_float("OPUS_USER_VERBATIM_MIN_FRAC", 0.08)
USER_VERBATIM_MAX_FRAC = _env_float("OPUS_USER_VERBATIM_MAX_FRAC", 0.16)
DIGEST_MIN_FRAC = _env_float("OPUS_DIGEST_MIN_FRAC", 0.05)
DIGEST_MAX_FRAC = _env_float("OPUS_DIGEST_MAX_FRAC", 0.10)
TAIL_MIN_WINDOW_FRAC = _env_float("OPUS_TAIL_MIN_FRAC", 0.02)
_PREFIX_TOK_CACHE: dict = {"n": 0, "t": 0.0}
_warned_threshold_conflict = False   # v3 · THRESHOLD/RATIO 冲突告警只报一次 (本函数每轮都走)

SUMMARY_MODEL_HINT = (
    "把下面的对话历史压缩成结构化简报。规则：\n"
    "1. 按固定小标题组织：`持久事实与约束` / `目标` / `决策与理由` / `文件与代码` / `命令与结果` / `错误与修复` / `待办与下一步` / `用户纠正与反馈`\n"
    "2. 用 bullet 碎片，不写散文；标识符 / 路径 / 数字逐字保留，不改写不省略\n"
    "3. 不知道就不写；无内容的小标题省略；不要编造\n"
    "4. 不写元描述（'用户问了 X' 'OPUS 回答了 Y'），直接写事实\n"
    "5. 控制在 400-700 字\n"
    "6. 用户的目标与其演化：措辞重要时【逐字引用用户原话】（加引号），不得改写成概括\n"
    "7. `用户纠正与反馈` 一段只要出现过纠正就必须写：用户否定过什么、改成了什么、为什么。"
    "这段最重要——不得省略、不得压成一句话\n"
    "8. 用户的要求写成 `用户说：<要点或原话>`，拍板写成 `决定：<内容>`（这是引用，不是元描述）\n"
    "9. 若对话里已有 `<compaction-summary>` 块，它是旧检查点：保留仍为真的事实、丢掉已过期的、合并新信息，不要照抄"
)

# ── 会话级压缩状态 (H-04 修复 · 来自龙头社区提交) ───────────────────────────
# 原先是模块级全局 · daemon 多会话并发 (WebUI/飞书/微信/续场各一线程) 时互相覆盖:
# 线程 A set_session_id(sidA) 后、真正压缩前被线程 B 的 set_session_id(sidB) 覆盖 →
# A 的摘要写进 B 的 summary.json · 最坏时 rewrite_session 把 B 的整本会话文件替换成 A 的消息。
# 改 ContextVar: 状态跟随执行上下文 · 每个 chat worker 线程一份 · 并发会话互不可见。
import contextvars as _cvars

_SESSION_STATE: "_cvars.ContextVar" = _cvars.ContextVar("mc_session_state", default=None)


def _state() -> dict:
    """当前执行上下文的压缩状态 (懒初始化)。"""
    st = _SESSION_STATE.get()
    if st is None:
        st = {
            "current_sid": "",
            "last_compression_turn": -COOLDOWN_TURNS,
            "compression_count": 0,
            "consecutive_compacts": 0,   # v2 · 连续压缩计数 (防每轮重建缓存 · wish-7f0adf2c)
            "last_prune_turn": -COOLDOWN_TURNS,
        }
        _SESSION_STATE.set(st)
        return st
    st.setdefault("last_prune_turn", -COOLDOWN_TURNS)
    return st


# 纯统计计数器 (跨会话混计无害 · 保持模块级)
_pruned_total: int = 0           # v2 · 累计修剪的工具结果数
_archived_files: int = 0         # v2 · 累计归档文件数

# tiktoken 懒加载缓存
_tiktoken_enc = None
_tiktoken_tried = False


# ---------- token 估算 ----------

def _get_tiktoken_encoder():
    """尝试加载 tiktoken cl100k_base 编码器 · 失败返 None（仅试一次）。"""
    global _tiktoken_enc, _tiktoken_tried
    if _tiktoken_tried:
        return _tiktoken_enc
    _tiktoken_tried = True
    try:
        import tiktoken
        _tiktoken_enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _tiktoken_enc = None
    return _tiktoken_enc


def _estimate_tokens(messages: list[dict]) -> int:
    """估算 messages 总 token 数 · 优先 tiktoken · fallback 字符启发式

    分层策略:
      1. tiktoken (cl100k_base) 可用 → 精确算（OpenAI 系通用编码器）
      2. fallback · 保守字符启发式 (卷七十三: 系数上调防低估):
         - 中文字符 ≈ 1.0 token/char (保守)
         - 英文/ASCII ≈ 0.5 token/char (保守)
         - 混合文本 ≈ 2/3 token/char (保守)
      3. 每条 message 加 5 token overhead (role / 分隔符)
      4. 整体 × _TOK_SAFETY_MULT (1.25) · 防跨 tokenizer 低估 (DeepSeek tokenizer ≠ cl100k_base)
    """
    enc = _get_tiktoken_encoder()
    if enc is not None:
        total = 0
        for m in messages:
            if not isinstance(m, dict):
                continue
            content = m.get("content") or ""
            if isinstance(content, str):
                total += len(enc.encode(content))
            elif isinstance(content, list):
                for blk in content:
                    if isinstance(blk, dict):
                        text = blk.get("text") or blk.get("content") or ""
                        if isinstance(text, str):
                            total += len(enc.encode(text))
            for tc in (m.get("tool_calls") or []):
                if isinstance(tc, dict):
                    fn = tc.get("function") or {}
                    args = fn.get("arguments") or ""
                    if isinstance(args, str):
                        total += len(enc.encode(args))
        return int((total + len(messages) * 5) * _TOK_SAFETY_MULT)

    # fallback · 字符启发式
    total_chars_cjk = 0
    total_chars_ascii = 0
    total_chars_other = 0

    for m in messages:
        if not isinstance(m, dict):
            continue
        text_parts: list[str] = []
        content = m.get("content") or ""
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict):
                    t = blk.get("text") or blk.get("content") or ""
                    if isinstance(t, str):
                        text_parts.append(t)
        for tc in (m.get("tool_calls") or []):
            if isinstance(tc, dict):
                fn = tc.get("function") or {}
                a = fn.get("arguments") or ""
                if isinstance(a, str):
                    text_parts.append(a)

        for text in text_parts:
            for ch in text:
                cp = ord(ch)
                if cp >= 0x4E00 and cp <= 0x9FFF:       # CJK 统一汉字
                    total_chars_cjk += 1
                elif cp >= 0x3400 and cp <= 0x4DBF:      # CJK 扩展 A
                    total_chars_cjk += 1
                elif cp >= 0x20000 and cp <= 0x2A6DF:    # CJK 扩展 B
                    total_chars_cjk += 1
                elif cp >= 0xF900 and cp <= 0xFAFF:      # CJK 兼容汉字
                    total_chars_cjk += 1
                elif cp <= 127:
                    total_chars_ascii += 1
                else:
                    total_chars_other += 1

    # 中文 ≈ 1.0 token/char · 英文 ≈ 0.5 token/char · 其他 ≈ 2/3 token/char (卷七十三保守化)
    est = int(total_chars_cjk * 1.0 + total_chars_ascii * 0.5 + total_chars_other * 2 / 3)
    return int((est + len(messages) * 5) * _TOK_SAFETY_MULT)


# ---------- v2 · tokPerChar 校准 (Reasonix compact.go tokPerChar 移植) ----------

_last_real_prompt_tokens: int = 0
_last_real_chars: int = 0


def _msg_chars(m: dict) -> int:
    """统计一条消息发送到 provider 的字符数 (content + tool_calls args · 不含 reasoning)。"""
    if not isinstance(m, dict):
        return 0
    n = 0
    content = m.get("content") or ""
    if isinstance(content, str):
        n += len(content)
    elif isinstance(content, list):
        for blk in content:
            if isinstance(blk, dict):
                t = blk.get("text") or blk.get("content") or ""
                if isinstance(t, str):
                    n += len(t)
    for tc in (m.get("tool_calls") or []):
        if isinstance(tc, dict):
            fn = tc.get("function") or {}
            n += len(fn.get("name") or "") + len(fn.get("arguments") or "")
    return n


def note_real_usage(prompt_tokens: int, messages: list[dict]) -> None:
    """tool_loop 每轮拿到真实 usage 后喂进来 · 校准 tok/char 比例 (Go: tokPerChar)。

    用模型真实 token 计数反推每字符 token 数 · 避免跨 tokenizer 低估。
    荒谬比例 (<=0.05 或 >=2) 拒收。
    """
    global _last_real_prompt_tokens, _last_real_chars
    chars = sum(_msg_chars(m) for m in messages if isinstance(m, dict))
    if prompt_tokens > 0 and chars > 0:
        r = prompt_tokens / chars
        if 0.05 < r < 2:
            _last_real_prompt_tokens, _last_real_chars = prompt_tokens, chars


def _tok_per_char() -> float:
    """有真实 usage 校准 → 用之；否则 fallback 0.35 (CJK 偏多)。"""
    if _last_real_prompt_tokens > 0 and _last_real_chars > 0:
        return _last_real_prompt_tokens / _last_real_chars
    return _TOK_PER_CHAR_FALLBACK


# ---------- helpers ----------

def set_session_id(sid: str) -> None:
    """让压缩层知道当前 session id · 会话级 (ContextVar · 多会话并发互不串台)。"""
    _state()["current_sid"] = sid


def _stringify_message(msg: dict) -> str:
    """把一条 message 转成给摘要 LLM 看的纯文本片段。"""
    role = msg.get("role", "?")
    content = msg.get("content", "")

    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "tool_use":
                name = block.get("name", "?")
                parts.append(f"[tool_use {name}]")
            elif btype == "tool_result":
                inner = block.get("content", "")
                if isinstance(inner, list):
                    inner = " ".join(
                        b.get("text", "") for b in inner if isinstance(b, dict)
                    )
                parts.append(f"[tool_result] {str(inner)[:2000]}")  # v2: 400→2000 · 摘要输入更完整
        text = "\n".join(p for p in parts if p)
    elif isinstance(content, str):
        text = content
    else:
        text = str(content)

    if msg.get("tool_calls"):
        parts_tc = []
        for tc in msg["tool_calls"]:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            name = fn.get("name", "?") if isinstance(fn, dict) else "?"
            args = fn.get("arguments", "") if isinstance(fn, dict) else ""
            if isinstance(args, str):
                args = _summarize_tool_args(args)
            parts_tc.append(f"{name}({args})")
        text = (text + "\n[tool_calls: " + ", ".join(parts_tc) + "]").strip()

    return f"=== {role} ===\n{text}"


def _is_tool_pair_msg(msg: dict) -> bool:
    """是不是 tool_use / tool_result 类的消息——压缩边界要避开它们的中间。"""
    content = msg.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") in ("tool_use", "tool_result"):
                return True
    if msg.get("tool_calls"):
        return True
    if msg.get("role") == "tool":
        return True
    return False


def _safe_split_index(messages: list[dict], target_keep_last: int) -> int:
    """
    找一个安全的"切割点"——保留最后 target_keep_last 条，
    但要避开 tool_use/tool_result 配对（不能把它们劈开）。
    返回切割索引（前 idx 条压缩，后面保留）。
    """
    if len(messages) <= target_keep_last:
        return 0

    idx = len(messages) - target_keep_last
    # 往前推到第一个 user 消息（不在工具调用中间）
    while idx > 0 and (
        _is_tool_pair_msg(messages[idx])
        or messages[idx].get("role") != "user"
    ):
        idx -= 1
    return max(0, idx)


# ---------- v2 · 规划/分区助手 (Reasonix compact.go 移植 · wish-7f0adf2c) ----------

def _is_compaction_summary(m: dict) -> bool:
    """是不是早前压缩产生的 digest 消息 (user role · content 以 <compaction-summary> 开头)。"""
    if not isinstance(m, dict) or m.get("role") != "user":
        return False
    content = m.get("content")
    return isinstance(content, str) and content.lstrip().startswith(SUMMARY_TAG_OPEN)


def _pinnable_user_turn(m: dict, ctx_window: int) -> bool:
    """用户说的一句话能否原样保留 (不被折叠进摘要)。

    判定: user turn 且估算 token ≤ min(PIN_FIRST_USER_MAX_TOKENS, ctx×0.15)。
    用户说过的事实永不摘要——无论在会话哪里说的 (Reasonix partitionFold 精神)。
    """
    if not isinstance(m, dict) or m.get("role") != "user":
        return False
    if _is_compaction_summary(m):
        return True  # 旧 digest 永远保留 (增量 · 治漂移)
    cap = PIN_FIRST_USER_MAX_TOKENS
    if ctx_window > 0:
        cap = min(cap, int(ctx_window * PIN_FIRST_USER_WINDOW_FRAC))
    return int(_msg_chars(m) * _tok_per_char()) <= cap


def tail_protect_index(msgs: list, user_turns: int | None = None) -> int:
    """从尾往头数 N 个真 user 回合 · 返回该回合起点。整段 [i:] 不 diet / 不 prune。

    不足 N 个 user → 0 (整段都是活尾巴)。digest user 不占名额。
    """
    n = TAIL_USER_TURNS if user_turns is None else user_turns
    if n <= 0:
        return len(msgs)
    seen = 0
    for i in range(len(msgs) - 1, -1, -1):
        m = msgs[i]
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        content = m.get("content") or ""
        if isinstance(content, str) and content.lstrip().startswith(SUMMARY_TAG_OPEN):
            continue
        seen += 1
        if seen >= n:
            return i
    return 0


def _token_budget_protect_index(msgs: list, budget: int | None = None) -> int:
    """从尾往头累计 token · 达到预算处返回下标 (刀2 · wish-a5f77893)。

    返回 idx: msgs[idx:] 都在“最近 budget tok”保护区内 (prune 不剪)。
    不足 budget 就耗尽 → 0 (整段都是活尾巴)。估算走 _estimate_tokens · 单条粒度。
    """
    budget = PRUNE_PROTECT_TOKENS if budget is None else budget
    if budget <= 0:
        return len(msgs)
    acc = 0
    idx = len(msgs)
    for i in range(len(msgs) - 1, -1, -1):
        if acc >= budget:
            break
        acc += _estimate_tokens([msgs[i]])
        idx = i
    return idx


def estimate_prefix_tokens() -> int:
    """稳定前缀 (system + tools json) token · 30s 缓存。失败返 0 不挡主路径。"""
    import time as _time
    now = _time.monotonic()
    if _PREFIX_TOK_CACHE["n"] and now - _PREFIX_TOK_CACHE["t"] < 30:
        return int(_PREFIX_TOK_CACHE["n"])
    try:
        import json
        from pathlib import Path
        from soul_loader import load_soul
        root = Path(__file__).resolve().parent.parent
        soul = load_soul(root, with_runtime=True)
        sys_tok = _estimate_tokens([{"role": "system", "content": soul.system_prompt or ""}])
        tools_tok = 0
        try:
            from tool_loop import _specs_for_llm, to_openai_tools
            blob = json.dumps(to_openai_tools(_specs_for_llm(None)), ensure_ascii=False)
            enc = _get_tiktoken_encoder()
            tools_tok = len(enc.encode(blob)) if enc else max(1, int(len(blob) * _tok_per_char()))
        except Exception:
            tools_tok = 0
        n = int(sys_tok + tools_tok)
        _PREFIX_TOK_CACHE["n"] = n
        _PREFIX_TOK_CACHE["t"] = now
        return n
    except Exception:
        return int(_PREFIX_TOK_CACHE["n"] or 0)


def _pinned_prefix_len(msgs: list[dict], ctx_window: int) -> int:
    """从头部数出【永不折叠】的段: 首个可 pin 的 user turn + 紧随的连续旧 digest。

    旧摘要在一定预算内不再进折叠区 (增量 · 治漂移)。

    wish-e72cc18a 刀1/2 修正 (真·压死根因):
      原实现 `if _pinnable_user_turn(m): head = i + 1` 会把【所有连续可 pin 的
      user】都推进保护段。而压缩恰好把 assistant/tool 折走、只留 user——
      于是头 250 条变成连续 user → head 一路推到 285 → 折叠区归零 →
      下次压缩无从下手 → 越压越压不动, 最终撞死在窗口上。
      现改为只认【第一个】user (+ 紧随其后的连续 digest), 保护段有界。
    """
    head = 0
    seen_first_user = False
    for i, m in enumerate(msgs):
        if not _pinnable_user_turn(m, ctx_window):
            if head == 0:
                # 首个 user 就 pin 不住 (单条过大) → 保护段应为空。
                # 不能 continue 往后扫: 那会把 [0, 下一个可 pin 点] 之间全划进保护段。
                if m.get("role") == "user":
                    break
                continue          # 只在开头的 system/工具噪音上继续跳过
            break                 # 保护段到此结束
        if not seen_first_user:
            seen_first_user = True
            head = i + 1          # 首个 user turn → 保护
        elif _is_compaction_summary(m):
            head = i + 1          # 紧随其后的旧 digest → 一起保护
        else:
            break                 # 第二个普通 user → 保护段不再前推
    return head


def _clamp_budget(base: int, ctx_window: int, min_frac: float, max_frac: float) -> int:
    """v3 (wish-98d77aaf) · 绝对 token 预算按窗口双向钳制。

    - 上界 max_frac: 防【小窗口】保留量≈窗口 → 压完没空间
    - 下界 min_frac: 防【大窗口】早期原话被压光 → 降智
    base <= 0 (显式禁用) / ctx_window <= 0 (认不出窗) → 原样返回, 保持旧行为。
    256K 窗口下三个预算的钳制结果与改前逐位相等。
    """
    if base <= 0 or ctx_window <= 0:
        return base
    lo = int(ctx_window * min_frac)
    hi = int(ctx_window * max_frac)
    if hi < lo:          # 配置写反 (min > max) → 不打哑谜, 取下界
        return lo
    return max(lo, min(base, hi))


def _partition_fold(region: list[dict], ctx_window: int,
                    verbatim_budget: int | None = None) -> tuple[list[dict], list[dict]]:
    """把折叠区分成 kept (原样保留) 与 fold (可折叠进摘要)。

    kept = 【最近 verbatim_budget tok 以内的】user 原话 + 全部旧 digest
    fold = 其余 (工具往返 / 大消息 / assistant 过程 / 超预算的更早 user 原话)

    wish-e72cc18a 刀1/2: 原实现“用户每句话永不摘要”无上界 → 长会话地板 60%+
    (实测 b05418: user 原话 92k tok 占 84%)。现给原话加【新鲜度预算】:
    从末尾往前累计, 超出预算的更早原话交给摘要器——摘要提示词已强制
    “关键措辞逐字引用 + 单列纠正”, 且原件仍在 sessions/archive/ 可召回。
    """
    budget = USER_VERBATIM_BUDGET if verbatim_budget is None else int(verbatim_budget)
    # v3 (wish-98d77aaf) · 双向钳制: 小窗防爆 / 大窗防降智 (256K 下值不变)
    budget = _clamp_budget(budget, ctx_window, USER_VERBATIM_MIN_FRAC, USER_VERBATIM_MAX_FRAC)
    # 循环外算一次 · 两个预算各自独立钳制
    _digest_budget = _clamp_budget(DIGEST_BUDGET_TOKENS, ctx_window,
                                   DIGEST_MIN_FRAC, DIGEST_MAX_FRAC)
    allow = [False] * len(region)
    acc = 0
    dacc = 0
    user_closed = False      # 原话通道已用尽
    digest_closed = False    # digest 通道已用尽
    for i in range(len(region) - 1, -1, -1):
        m = region[i]
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        c = _estimate_tokens([m])
        if _is_compaction_summary(m):
            # wish-e72cc18a 刀1/2 补丁: 旧 digest 同样必须有上界。
            # 原实现“所有 digest 永久保留(存量·治漂移)” → 实测 b05418 攒了 34 个 = 53k tok
            # (≈21 个百分点的地板)。现只留最近 DIGEST_BUDGET_TOKENS 以内的,
            # 更早的交给摘要器吸收(提示词规则 9 已明确要求“合并旧检查点·不要照抄”)。
            # 注: 两个预算必须各自独立关阀 —— 曾用 break 导致 digest 一超预算就
            # 截断整个循环, 原话预算形同虚设(扫描实测: 原话 8k→40k 结果完全一样)。
            if digest_closed or (_digest_budget > 0 and dacc + c > _digest_budget):
                digest_closed = True   # 只关 digest 通道·不影响原话通道
                continue
            dacc += c
            allow[i] = True
            continue
        if not _pinnable_user_turn(m, ctx_window):
            continue                 # 本来就 pin 不住 (单条太大)
        if user_closed:
            continue
        if budget > 0:
            # 口径必须与 _compact_threshold / 水位面板一致 → 用 _estimate_tokens。
            # (原用 _msg_chars × _tok_per_char: 冷启动 fallback=0.35 对中文严重低估,
            #  实测 288 条 user 只算成 12k tok, 而 _estimate_tokens 是 92k → 预算形同虚设)
            if acc + c > budget:
                user_closed = True      # 只关原话通道·不影响 digest 通道
                continue
            acc += c
        allow[i] = True
    kept: list[dict] = []
    fold: list[dict] = []
    for i, m in enumerate(region):
        (kept if allow[i] else fold).append(m)
    return kept, fold


def _tail_start(msgs: list[dict], head: int, budget_tokens: int, min_keep: int = 4) -> int:
    """从最新往旧走 · 累积到预算上限 (但至少留 min_keep 条) · 边界对齐掉 tool 消息。

    返回尾部起点 index (含) —— [start, len) 保留原文。
    """
    start = len(msgs)
    acc = 0
    for i in range(len(msgs) - 1, head, -1):
        c = _estimate_tokens([msgs[i]])
        if len(msgs) - i > min_keep and acc + c > budget_tokens:
            break
        acc += c
        start = i
    # 对齐: 尾部不能以孤儿 tool 消息开头 (配对完整性)
    while start > head and start < len(msgs) and _is_tool_pair_msg(msgs[start]):
        start -= 1
    return start


# ---------- 窗口查询 ----------

def _get_context_window(model_id: Optional[str]) -> int:
    """查上下文窗户 · 用户配置优先 · 其次推荐目录 · 都没有返 0。"""
    if not model_id:
        return 0
    try:
        from workers.provider_configs import window_for_model
        n = window_for_model(model_id)
        if n > 0:
            return n
    except Exception:
        pass
    try:
        from provider_presets import context_window_for
        return context_window_for(model_id)
    except Exception:
        return 0


def _compact_threshold(ctx_window: int, prefix: int) -> int:
    """摘要开火线: 有窗户取 min(窗×ratio, 前缀+绝对线) · 没有就前缀+25.6 万。

    前缀已经 ≥ 窗×ratio（视觉 16K 等）· 压历史救不了 400 · 改走绝对线，避免每轮空转摘要。
    """
    abs_line = prefix + _get_abs_cap()
    if ctx_window <= 0:
        return abs_line
    window_line = int(ctx_window * _get_ratio())
    if prefix >= window_line:
        return abs_line
    return min(window_line, abs_line)


def _get_ratio() -> float:
    """读 OPUS_AUTO_COMPACT_RATIO · 默认 0.8 · 非法值报错+回退默认 (v3: 不再静默)。

    省 token 想更狠→0.6 · 想留更多原文→0.85 (合法区间 0.1~0.95)。
    """
    raw = (os.environ.get("OPUS_AUTO_COMPACT_RATIO") or "").strip()
    if not raw:
        return DEFAULT_WINDOW_RATIO
    try:
        v = float(raw)
    except (ValueError, TypeError):
        logger.error("[压缩参数] OPUS_AUTO_COMPACT_RATIO=%r 不是数字 · 已回退 %.2f (改好 .env 后重启生效)",
                     raw, DEFAULT_WINDOW_RATIO)
        return DEFAULT_WINDOW_RATIO
    if not (0.1 <= v <= 0.95):
        logger.error("[压缩参数] OPUS_AUTO_COMPACT_RATIO=%.3f 超出合法区间 [0.1, 0.95] · 已回退 %.2f",
                     v, DEFAULT_WINDOW_RATIO)
        return DEFAULT_WINDOW_RATIO
    return v


def validate_params() -> list[str]:
    """v3 (wish-273d3d3f · ③) · 参数自检 · 返问题列表(空=健康)。

    DSH 原版: 「保留比例不小于阈值比例 → 插件加载失败, 因为任何模型容量都无法让该策略有效」。
    我们对应: 尾部保护比例 >= 触发线 = 压完立刻又超线 = 同款无解组合。
    调用点: /dashboard 健康检查 · WebUI 保存时拒绝非法组合。
    """
    probs: list[str] = []
    r = _get_ratio()
    # v3 · 上一条 if 实际上是死分支: _get_ratio() 自己就把越界值钳回默认了,
    # 拿到手的 r 永远合法。要真把越界暴露出来, 必须查【原始配置】(env 原文)。
    _raw = (os.environ.get("OPUS_AUTO_COMPACT_RATIO") or "").strip()
    if _raw:
        try:
            _rv = float(_raw)
            if not (0.1 <= _rv <= 0.95):
                probs.append(
                    f"触发线环境变量 {_rv:.2f} 越界 (合法 0.1~0.95) · 已被静默回退到 {r:.2f}")
        except (ValueError, TypeError):
            probs.append(
                f"触发线环境变量 {_raw!r} 不是数字 · 已被静默回退到 {r:.2f}")
    if TAIL_MAX_WINDOW_FRAC >= r:
        probs.append(
            f"尾部保护比例 {TAIL_MAX_WINDOW_FRAC:.2f} >= 触发线 {r:.2f} · "
            f"压完立刻又超线 (DSH 同款无解组合)")
    # MAX_CONSECUTIVE_COMPACTS 硬编码常量 2 → 不可能 <1, 不做运行时检查
    # (原来那条 `if MAX_CONSECUTIVE_COMPACTS < 1` 是恒为假的死分支, 已删)
    if TAIL_TOKEN_BUDGET <= 0:
        probs.append("TAIL_TOKEN_BUDGET <= 0 · 尾部无保护 · 会压掉刚说的话")

    # v3 (wish-98d77aaf) · 消双真相源: THRESHOLD 会静默顶掉 RATIO
    _th = _env_int("OPUS_AUTO_COMPACT_THRESHOLD", 0)
    if _th > 0 and _raw:
        probs.append(
            f"OPUS_AUTO_COMPACT_THRESHOLD={_th} 与 OPUS_AUTO_COMPACT_RATIO={_raw} 同时设了 · "
            f"阈值优先生效 · 比例形同虚设 (同一件事两个真相源 · 建议只留 RATIO)")

    # v3 (wish-98d77aaf) · 双向钳制区间自检 (写反了会让钳制静默失效)
    for _nm, _lo, _hi in (
        ("原话", USER_VERBATIM_MIN_FRAC, USER_VERBATIM_MAX_FRAC),
        ("digest", DIGEST_MIN_FRAC, DIGEST_MAX_FRAC),
        ("尾部", TAIL_MIN_WINDOW_FRAC, TAIL_MAX_WINDOW_FRAC),
    ):
        if not (0.0 <= _lo < _hi <= 1.0):
            probs.append(
                f"{_nm}钳制区间非法: min={_lo:.3f} max={_hi:.3f} · 应满足 0 <= min < max <= 1")

    # v3 (wish-98d77aaf) · 保留总量【实算】vs 触发线 (DSH 同款「无解组合」)
    #    三项作用在不同区段不叠加·但总保留量超过触发线 = 压完立刻又超线。
    _cw = _get_context_window(None) or DEFAULT_ABS_CAP_TOKENS
    _keep = (
        _clamp_budget(USER_VERBATIM_BUDGET, _cw, USER_VERBATIM_MIN_FRAC, USER_VERBATIM_MAX_FRAC)
        + _clamp_budget(DIGEST_BUDGET_TOKENS, _cw, DIGEST_MIN_FRAC, DIGEST_MAX_FRAC)
        + _clamp_budget(TAIL_TOKEN_BUDGET, _cw, TAIL_MIN_WINDOW_FRAC, TAIL_MAX_WINDOW_FRAC)
    )
    _line = int(_cw * r)
    if _keep >= _line:
        probs.append(
            f"保留总量 {_keep // 1000}K >= 触发线 {_line // 1000}K (窗口 {_cw // 1000}K × {r:.2f}) · "
            f"压完立刻又超线 (DSH 同款无解组合 · 调小三个预算或调大 RATIO)")
    return probs


def _cap_override_path():
    """WebUI「访问 & 会话 → 记忆整理线」落盘位置 (data/runtime 是既有分类 · 不新开目录)。"""
    from pathlib import Path
    return Path(__file__).resolve().parent.parent / "data" / "runtime" / "compact_cap.json"


def read_cap_override() -> int:
    """读 WebUI 存的压缩绝对线 · 没有/坏了返 0 (= 不覆盖 · 走 env/缺省)。"""
    try:
        p = _cap_override_path()
        if p.exists():
            import json
            return int(json.loads(p.read_text(encoding="utf-8")).get("abs_cap") or 0)
    except Exception:
        pass
    return 0


def set_cap_override(v) -> int:
    """写 WebUI 的压缩绝对线 · 返实际生效值 (钳 40K 下限)。 v<=0 = 清除覆盖 · 回落 env/缺省。

    返回值语义 (v3 · 与 0 区分开):
      >0  = 生效值
       0  = 【已清除覆盖】
      -1  = 【被拒绝】(非数字) · 盘上原值未动
    旧版两种情形都返 0 → 调用方无法区分「拒了」和「清了」, WebUI 会误报 ok。

    即时生效 · 不用重启 (每次 _get_abs_cap 现读)。
    """
    try:
        iv = int(v or 0)
    except (ValueError, TypeError):
        # v3 · 不再静默当成“清除覆盖” · 报错且不动盘(调用方能从日志看出异常)
        logger.error("[压缩参数] 记忆整理线收到非数字值 %r · 本次不修改 (盘上原值保留)", v)
        return -1
    p = _cap_override_path()
    try:
        if iv > 0:
            val = max(40_000, iv)
            p.parent.mkdir(parents=True, exist_ok=True)
            import json
            p.write_text(json.dumps({"abs_cap": val}, ensure_ascii=False), encoding="utf-8")
            return val
        if p.exists():
            p.unlink()
    except Exception:
        pass
    return 0


def _get_abs_cap() -> int:
    """0.8.8 · 压缩绝对线 (env OPUS_AUTO_COMPACT_MAX_TOKENS · 缺省 256K)。

    为什么: 1M 窗口 × 0.7 = 700K · 普通会话 80-250K 永远够不到 → 永不压缩 → 全量发送慢。
    绝对线让大窗口模型按"体验拐点"触发 (不依赖窗口比例) · 小窗口模型不受影响 (min 取小)。
    下限钳制 40K · 防设太低导致每几轮就压缩+重建缓存 (热抖动)。

    0.9.x · 取值顺序: WebUI 存的值 (「访问 & 会话」当场可改 · 即时生效)
                      → env OPUS_AUTO_COMPACT_MAX_TOKENS → 缺省 256K。
    原先只有 env 一条路 · 用户看不到也改不了 · 等于暗规则 (BRO 2026-09-14 指出)。
    """
    ui_v = read_cap_override()
    if ui_v > 0:
        return max(40_000, ui_v)
    raw = (os.environ.get("OPUS_AUTO_COMPACT_MAX_TOKENS") or "").strip()
    if raw:
        # v3 · 不再静默退回: 非法值走 _env_int 大声报错 + 回退缺省
        v = _env_int("OPUS_AUTO_COMPACT_MAX_TOKENS", DEFAULT_ABS_CAP_TOKENS)
        if v > 0:
            return max(40_000, v)
    return DEFAULT_ABS_CAP_TOKENS


# ---------- auto-compress ----------

def token_budget_check(
    messages: list[dict],
    model_id: Optional[str] = None,
) -> bool:
    """判断该不该自动压缩。

    触发优先级:
      1. env OPUS_AUTO_COMPACT_THRESHOLD 显式设了 → 用它
      2. token 预算: 历史+前缀 ≥ min(窗户×ratio, 前缀+25.6 万)
         认不出窗户 → 只走前缀+25.6 万 · 不再数 30 条
         前缀已经 ≥ 窗户×ratio → 压历史救不了窗 · 改走绝对线（防小窗空转摘要）

    都得过 cooldown。返回 True → 上层该调 auto_compress()。
    """
    st = _state()

    # 1. env 显式阈值（最高优先）
    # v3 · 原实现用 try 把【整段业务逻辑】包住 → env 写错、_estimate_tokens 抛错
    # 都会被安静吞掉、无痕降级到别的判定路径。现改为只解析 env，业务错照实抛。
    token_threshold = _env_int("OPUS_AUTO_COMPACT_THRESHOLD", 0)
    if token_threshold > 0:
        # v3 (wish-98d77aaf) · 消双真相源。
        # 这个 env 会【顶掉】OPUS_AUTO_COMPACT_RATIO —— 两者描述同一件事(压缩触发线)。
        # 原实现静默顶掉·无任何提示 → 现在响亮报出·让漂移无处藏。
        _ratio_raw = (os.environ.get("OPUS_AUTO_COMPACT_RATIO") or "").strip()
        if _ratio_raw:
            global _warned_threshold_conflict
            if not _warned_threshold_conflict:
                _warned_threshold_conflict = True
                logger.warning(
                    "[压缩参数·冲突] OPUS_AUTO_COMPACT_THRESHOLD=%d 已设 → 它顶掉了 "
                    "OPUS_AUTO_COMPACT_RATIO=%r (两者同一件事·阈值优先)。"
                    "建议只留 RATIO · 删掉 THRESHOLD 避免漂移。",
                    token_threshold, _ratio_raw)
        estimated = _estimate_tokens(messages)
        if estimated >= token_threshold:
            # 过 cooldown
            turns_since_last = len(messages) - st["last_compression_turn"]
            return turns_since_last >= COOLDOWN_TURNS
        # 没过 token 阈值 → 不触发（env 显式设了就不走消息数 fallback）
        return False

    # 2. token 预算 · 认不出窗户也走绝对线 (不再数 30 条)
    ctx_window = _get_context_window(model_id)
    prefix = estimate_prefix_tokens()
    estimated = _estimate_tokens(messages)
    total = estimated + prefix
    threshold = _compact_threshold(ctx_window, prefix)
    _hit = total >= threshold
    if not _hit and len(messages) >= 200 and estimated >= threshold * 0.5:
        # wish-8f122254 · 条数爆了 + 估算逼近阈值一半 → 跨 tokenizer 低估漏网
        _hit = True
    if not _hit:
        st["consecutive_compacts"] = 0
        return False
    if st["consecutive_compacts"] >= MAX_CONSECUTIVE_COMPACTS:
        # wish-a5f77893 刀A (2026-09-16): 停手不能永久 —— 事故复盘 (daemon.log 02:24):
        # 连续压缩仍超线后彻底停手 · 水位一路涨到 246.8k 无人拦 (静默停手是帮凶)。
        # 改为: 距上次压缩 ≥ EMERGENCY_BREAK_TURNS 轮 → 紧急豁免一次; 否则暂缓 (带限频日志)。
        turns_since_last = len(messages) - st["last_compression_turn"]
        if turns_since_last >= EMERGENCY_BREAK_TURNS:
            logger.warning(
                "[压缩·紧急豁免] 连续 %d 次仍超线 · 距上次 %d 轮 → 突破停手 (防永久停手)",
                st["consecutive_compacts"], turns_since_last)
            return True
        if turns_since_last <= 1 or turns_since_last % 10 == 0:
            logger.warning(
                "[压缩·停手] 连续 %d 次仍超线 · 距上次 %d 轮 · 暂缓 (水位在危险区)",
                st["consecutive_compacts"], turns_since_last)
        return False
    turns_since_last = len(messages) - st["last_compression_turn"]
    return turns_since_last >= COOLDOWN_TURNS


def _generate_summary(
    text_to_summarize: str,
    client: Any,
    model: str,
    provider: str,
    system_stable: str = "",
) -> str:
    """调 LLM 生成摘要。失败抛异常。

    v3 (wish-273d3d3f) · 摘要缓存复用:
      system_stable = 主对话那截「一个 session 内字节不变」的稳定前缀
      (tool_loop 的 system)。带上它 → 摘要调用与主对话共享同一段开头 →
      这段走 prompt cache (约 1/10 价), 不再每次从零读。
      **刻意不带 system_suffix** —— 它每轮变, 带上反而断前缀 (铁律 14)。
    """
    if client is None:
        raise RuntimeError("LLM client not available for summary generation")

    # SUMMARY_MODEL_HINT 带 BRO/OPUS/「下一根毛」自指·会让摘要器照着产出母体 lore·
    # 在使用点按实例去母体化(母体 no-op)。
    from identity import localize_narration as _ln
    prompt = f"{_ln(SUMMARY_MODEL_HINT)}\n\n--- 待压缩的对话 ---\n\n{text_to_summarize}"

    from daemon_runtime import bg_max_tokens
    _mt = bg_max_tokens(default=4000)
    if provider == "anthropic":
        _sys_kw = {}
        if system_stable:
            _sys_kw["system"] = system_stable   # v3 · 与主对话同前缀 → 命中缓存
        resp = client.messages.create(
            model=model,
            max_tokens=_mt,
            messages=[{"role": "user", "content": prompt}],
            **_sys_kw,
        )
        for block in resp.content:
            if getattr(block, "type", "") == "text":
                return block.text.strip()
        raise RuntimeError("anthropic response had no text block")
    else:
        _oai_msgs: list[dict] = []
        if system_stable:
            _oai_msgs.append({"role": "system", "content": system_stable})  # v3 · 同前缀
        _oai_msgs.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=model,
            max_tokens=_mt,
            messages=_oai_msgs,
        )
        return (resp.choices[0].message.content or "").strip()


def _adaptive_keep_last_n(
    messages: list[dict],
    model_id: Optional[str],
    caller_keep_last_n: Optional[int],
) -> int:
    """计算自适应 keep_last_n。

    优先级:
      1. caller 显式传了 → 用它（summarize_session 工具手动的 keep_last_n）
      2. model_id 已知 + context_window 能查到 → 按剩余预算反推
      3. 退化 → DEFAULT_KEEP_LAST_N (8)

    自适应公式:
      budget 剩余 = context_window * (1 - ratio)  → 压缩后可用的 token 空间
      avg_msg = 总 token / 消息数
      keep_last_n = max(MIN_KEEP_LAST_N, min(MAX_KEEP_LAST_N, budget_remaining / avg_msg))
    """
    if caller_keep_last_n is not None:
        return caller_keep_last_n

    ctx_window = _get_context_window(model_id)
    if ctx_window <= 0:
        return DEFAULT_KEEP_LAST_N

    n = len(messages)
    if n == 0:
        return DEFAULT_KEEP_LAST_N

    total_est = _estimate_tokens(messages)
    avg = total_est / n if n > 0 else 100  # 单条消息平均 token

    ratio = _get_ratio()
    budget_remaining = ctx_window * (1.0 - ratio)

    if avg <= 0:
        return DEFAULT_KEEP_LAST_N

    adaptive = int(budget_remaining / avg)
    return max(MIN_KEEP_LAST_N, min(MAX_KEEP_LAST_N, adaptive))


def _summarize_tool_args(args: str) -> str:
    """工具参数摘要 (Reasonix summarizeToolArgs 移植): 合法 JSON → {key1, key2} (N keys) · 非法 → (N bytes)。"""
    try:
        data = json.loads(args)
        if isinstance(data, dict):
            keys = list(data.keys())[:8]
            return "{" + ", ".join(str(k) for k in keys) + f"}} ({len(data)} keys)"
        return f"({len(args)} bytes)"
    except Exception:
        return f"({len(args)} bytes)"


def prune_stale_tool_results(messages: list[dict]) -> tuple[list[dict], dict]:
    """v2 · 修剪陈旧大工具结果 (Reasonix PruneStaleToolResults 移植 · wish-7f0adf2c)

    候选: role=='tool' 且 content ≥ PRUNE_MIN_CHARS
    保护: 最后 8 条不动 · 跳过已带 PRUNED_MARKER (幂等) · 跳过错误结果 (排障线索保命)
    流程: 先归档原件 (失败 → 原样返回 + stats error · 绝不动历史) → 替换 content 为占位符
    只换 content · 不删消息 · 不动 tool_call_id (配对不断)

    v3 (2026-08-14 · DeepSeek Harness compaction-tool-result-pruner 对比升级):
      整条替换占位符 → **head+tail 中间裁剪**。 Harness 的核心改进: 工具结果的"头"
      (通常是结构化输出/结论) 和"尾" (错误信息/补充) 都在·只删中间冗长部分 →
      裁剪后 LLM 仍能从残留读到关键信息·不用重新调用。 保留我们的错误保护+归档+幂等。

    返回 (新 messages, stats{pruned, saved_chars, archive})
    """
    candidates: list[tuple[int, str]] = []
    protect = tail_protect_index(messages)
    # wish-a5f77893 刀2 (2026-09-16): 叠加“最近 N tok 保护” (对齐 OpenCode PRUNE_PROTECT=40K)
    # —— 轮次保护之外 · 最近 PRUNE_PROTECT_TOKENS tok 内的内容同样不剪 (两保护取并集)。
    protect = min(protect, _token_budget_protect_index(messages))
    for i, m in enumerate(messages):
        if not isinstance(m, dict) or m.get("role") != "tool":
            continue
        if i >= protect:
            continue  # 最近 N 个 user 回合原文保活
        content = m.get("content") or ""
        if not isinstance(content, str):
            continue
        if PRUNED_MARKER in content[:200]:
            continue  # 幂等
        low = content.lstrip().lower()
        if low.startswith(("error", "blocked", "[error")):
            continue  # 错误结果保命
        if len(content) >= PRUNE_MIN_CHARS:
            candidates.append((i, m))

    if not candidates:
        return messages, {"pruned": 0, "saved_chars": 0, "archive": None}

    originals = [messages[i] for i, _ in candidates]
    try:
        archive_path = _archive_messages("prune", originals)
    except Exception as e:
        return messages, {"pruned": 0, "saved_chars": 0, "archive": None, "error": str(e)}

    # v3 · head/tail 预算 (Harness: head 4096 + tail 1024 · 我们按中文密度收紧 + 对齐 PRUNE_MIN_CHARS=1024)
    # 阈值 = head+tail+200 ≈ 1480 → 覆盖 1480+ 的内容走 head/tail · 1024-1480 之间内容本身不大整条替换
    _head_chars = 1024
    _tail_chars = 256
    new_msgs = list(messages)
    saved = 0
    for i, orig in candidates:
        content = orig.get("content") or ""
        name = "?"
        for j in range(i - 1, max(-1, i - 20), -1):
            prev = messages[j]
            if prev.get("role") == "assistant" and prev.get("tool_calls"):
                for tc in prev["tool_calls"]:
                    if isinstance(tc, dict) and tc.get("id") == orig.get("tool_call_id"):
                        fn = tc.get("function") or {}
                        name = fn.get("name", "?") if isinstance(fn, dict) else "?"
                        break
                if name != "?":
                    break
        # v3 · head + marker + tail (中间裁剪 · 保留开头关键结论 + 结尾错误/补充)
        if len(content) > _head_chars + _tail_chars + 200:
            _h = content[:_head_chars]
            _t = content[-_tail_chars:]
            placeholder = (
                f"{PRUNED_MARKER}{name} · 原 {len(content)} 字符 · "
                f"保留头 {_head_chars}+尾 {_tail_chars} · 已归档 {archive_path} · "
                f"需要更全请 read_file 归档或重新调用该工具]\n\n"
                f"── 头部 (关键结论) ──\n{_h}\n\n"
                f"── 尾部 (错误/补充) ──\n{_t}"
            )
            new_msgs[i] = dict(orig)
            new_msgs[i]["content"] = placeholder
            saved += len(content) - len(placeholder)
        else:
            # 不够剪 (只比阈值多一点) · 仍整条替换占位符 (保留归档路径)
            placeholder = (
                f"{PRUNED_MARKER}{name} · 原 {len(content)} 字符 · "
                f"已归档 {archive_path} · 需要原文请重新调用该工具或读归档]"
            )
            new_msgs[i] = dict(orig)
            new_msgs[i]["content"] = placeholder
            saved += len(content)

    return new_msgs, {"pruned": len(candidates), "saved_chars": saved, "archive": archive_path}


def prune_if_needed(messages: list[dict], model_id: Optional[str] = None) -> list[dict]:
    """压力够了先免费剪旧工具结果 · 不够省就不动盘 (OpenCode PRUNE_MINIMUM)。

    不调 LLM。跟 auto_compress 拆开 · 长会话不用等到 256k 才剪。
    """
    global _pruned_total
    n = len(messages)
    if n < MIN_MESSAGES_TO_COMPRESS:
        return messages
    hist = _estimate_tokens(messages)
    if hist < PRUNE_HISTORY_PRESSURE:
        return messages
    st = _state()
    if n - int(st.get("last_prune_turn", -COOLDOWN_TURNS)) < COOLDOWN_TURNS:
        return messages
    new_msgs, pstats = prune_stale_tool_results(messages)
    if pstats.get("pruned", 0) <= 0:
        return messages
    if int(pstats.get("saved_chars") or 0) < MIN_PRUNE_SAVED_CHARS:
        return messages
    # v3 · 磁盘必须留全量: 内存里的 messages 是「折叠版」(折叠段已被摘要替换),
    # 直接写盘 = 用折叠版覆盖磁盘上的全量版 → V3 ① 白做。
    # 解法: 取磁盘原文(全量) → 对全量施加同样的剪枝 → 写回。
    # prune_stale_tool_results 是纯函数(只换工具结果·不动结构) → 对全量重跑安全。
    full_msgs = _prune_full_from_disk()
    if full_msgs is not None:
        _persist_rewrite(new_msgs, full_msgs)
    # else: 拿不到全量 → 本次不写盘(内存里 prune 已生效 · 磁盘保持全量)。
    # 收尾只写一份(原先写在 if 分支里 → 主路径被漏掉, 函数隐式返回 None)。
    st["last_prune_turn"] = len(new_msgs)
    _pruned_total += pstats["pruned"]
    return new_msgs


def _prune_full_from_disk() -> Optional[list[dict]]:
    """v3 · 取磁盘上的全量会话并施加同样的剪枝 (保住全量版不被折叠版覆盖)。

    为什么必须这么做: prune_if_needed / auto_compress 收到的 messages 是
    「折叠版」——磁盘上的全量版(带 compacted 标记)只有读盘才拿得到。
    直接 _persist_rewrite(折叠版) 会把全量抹掉, V3 ①(显示全量/发送折叠) 失效。

    ⚠ 取数必须用 load_session_for_storage(存储形态) · 不能用 load_session_for_ui:
    后者是给前端渲染的有损形态 (tool_calls 压扁成 {id,name,arguments} / content 超
    50K 截断) —— 拿它当"全量版"写回 = 在磁盘上把真源降级。
    (2026-09-19 事故: 这样写盘 → DeepSeek 422 missing field `type` → 会话打不开)

    返回 None = 没读到全量 → 调用方应放弃写盘(保磁盘现状)。
    """
    sid = _state().get("current_sid")
    if not sid:
        return None
    try:
        from daemon_session import load_session_for_storage
        disk = load_session_for_storage(sid)
        if not disk:
            return None
        pruned, _stats = prune_stale_tool_results(disk)
        return pruned or None
    except Exception:
        logging.getLogger("opus.memcomp").warning(
            "prune 全量版读盘失败 · 本次不写盘(保住磁盘现有全量)", exc_info=True)
        return None


def _persist_rewrite(messages: list[dict], full_messages: list[dict] | None = None) -> None:
    """v2 · 压缩/修剪结果原子重写 session jsonl (治重启蒸发 · wish-7f0adf2c)。

    v3 (wish-273d3d3f) · 显示/发送分层:
      messages       = 折叠版(折叠段已被摘要替换) → 返回给内存/LLM
      full_messages  = 全量版(折叠段原话在 · 打 compacted 标记) → 写盘
    磁盘存全量 → 重启后 UI 仍完整; load_session 跳过 compacted → LLM 拿折叠版。
    支持两种调用形态:
      _persist_rewrite(folded, full)  → 盘上写全量 (auto_compress 主路)
      _persist_rewrite(folded, full_from_disk) → prune 路也走全量
    调用方拿不到全量时用 _prune_full_from_disk() 取 (拿不到就别写盘 · 宁可本次不落盘也不丢全量)。
    失败不抛 (压缩本身已生效 · 持久化尽力而为)。

    延迟 import daemon_session 防循环。失败不抛 (压缩本身已生效 · 持久化尽力而为)。
    """
    sid = _state()["current_sid"]
    if not sid:
        return
    try:
        from daemon_session import rewrite_session
        rewrite_session(sid, full_messages if full_messages is not None else messages)
    except Exception:
        logging.getLogger("opus.memcomp").warning(
            "压缩重写 session jsonl 失败 · 磁盘仍是旧版 · 重启会回退到压缩前", exc_info=True)


def _msg_key(m) -> Optional[tuple]:
    """消息比对键 (尾部对齐用 · 不依赖 id() · 磁盘与内存是不同对象)。

    ⚠ wish-220071ea · content 必须先折叠形态再比:
      磁盘原文存的是 ""，而内存经 load_session 归一后是 None
      (2026-07-28 跨模型空串修复 daemon_session.py L527-530) ——
      直接 str() 会算出 "" ≠ "None"，锚点永远找不到 → 静默放弃写盘
      → 磁盘水位只涨不落(b05418 实测顶穿 102.6%)。
      空串 / None / 纯空白统一折叠成 "" 再比。
    """
    if not isinstance(m, dict):
        return None
    c = m.get("content")
    if c is None or (isinstance(c, str) and not c.strip()):
        c = ""
    return (m.get("role"), str(c)[:160],
            str(m.get("tool_call_id") or ""), bool(m.get("compacted")))


def _find_tail_anchor(disk: list[dict], tail: list[dict]) -> Optional[int]:
    """在 disk 里找 tail 的起始下标 (尾部对齐 · 内容比对)。找不到返 None。

    两版(磁盘全量 / 内存折叠)的【尾部】内容一致(本次压缩没动尾部),
    所以可以拿内存尾部去磁盘里反推本次折叠区的位置。
    """
    if not disk:
        return None
    if not tail:
        return len(disk)
    t0 = _msg_key(tail[0])
    if t0 is None:
        return None
    for i in range(len(disk) - len(tail), -1, -1):
        if _msg_key(disk[i]) != t0:
            continue
        if all(_msg_key(disk[i + j]) == _msg_key(tail[j]) for j in range(len(tail))):
            return i
    return None


def _assemble_full_from_disk(messages2: list[dict], head: int, start: int,
                             digest_msg: dict,
                             fold: Optional[list[dict]] = None) -> Optional[list[dict]]:
    """v4 · 组装磁盘全量版: 以磁盘为基底 · 历史一条不丢 · 只给"已折走"补标记。

    为什么必须这么做: auto_compress 收到的 messages2 是「折叠版」——被压过的
    老原话不在里面。若直接 messages2[:head] + [digest] + tail 拼全量,
    第二次压缩就会把第一次的全量抹掉(每压一轮丢一层)。

    wish-e3c3e379 修正 (v3 的坑 · 真凶):
      v3 这里写的是 `[m for m in disk[head:dstart] if m.get("compacted")]` ——
      只保留【已带标记】的消息。可磁盘上还有一批【没有标记】的历史消息
      (尤其 assistant: 早期写折叠版时留下的), 它们被当成垃圾系统性丢弃。
      而 new_region 来自内存折叠版(assistant 早已被折走) → 两头都没有
      → 每写一次盘就丢一批。实测 b05418: 磁盘 user:assistant 失衡到 189:65,
      发给模型的更失衡到 185:18; UI 上是「一片我的话、一片你的话」。
    现在: disk[:dstart] 全取(仅剔旧 digest) —— 历史不丢、顺序原样。

    发送侧隔离(磁盘留全量 ≠ 全发给模型): 靠 compacted 标记区分 —— 已折走的
    带标记(写盘保留 · load_session 不回放给 LLM), 活的没标记。
    ⚠ 标记由 load_session(include_compacted=True) 从磁盘带回 ——
    wish-e3c3e379 修复前它在重建消息时丢了标记, 导致下面的判据恒为空, 全量
    被折叠版顶掉、老 assistant 被系统性抹掉。

    读盘失败 / 尾部对齐失败 → 返回 None = 【不能安全写盘】。
    调用方拿到 None 时必须放弃 _persist_rewrite —— 否则就用折叠版覆盖了磁盘全量,
    与 prune 路径同一条纪律: 宁愿这一次不落盘, 也不能丢全量。
    基底同样只能取 load_session_for_storage(存储形态) · 不能用 UI 形态(有损)。
    """
    try:
        from daemon_session import load_session_for_storage
        sid = _state().get("current_sid")
        if not sid:
            return None
        disk = load_session_for_storage(sid)
    except Exception:
        logging.getLogger("opus.memcomp").warning(
            "全量版读盘失败 · 本次不写盘(保住磁盘现有全量)", exc_info=True)
        return None
    if not disk:
        return None
    dstart = _find_tail_anchor(disk, messages2[start:])
    if dstart is None or dstart < head:
        logging.getLogger("opus.memcomp").warning(
            "全量版尾部对齐失败 · 本次不写盘(保住磁盘现有全量)")
        return None
    # 磁盘上的 compacted 标记是权威判据 (前提: load_session 存储形态把标记带回来了)。
    # 所以这里只需: 全取 disk[:dstart] · 只剔旧 digest —— 不筛、不猜、不重排。
    # 旧实现在这里按 compacted 筛选 → 无标记的历史消息(尤其 assistant)被当垃圾丢。
    # 本轮刚被折叠的消息也要补标记 —— 否则下次 load_session 会把它们当"活着的"
    # 回放给 LLM: 同一段历史既在摘要里、又在原文里, 白占窗口(压缩白做)。
    # 磁盘上带标记的是【历史上】折过的; 本轮折的还没写进磁盘, 只能靠内容 key 认。
    # 用 key[:3] 去掉 compacted 位(磁盘上无标记, 内存里也未标, 不影响)。
    _fold_keys: set = set()
    for _fm0 in (fold or []):
        _k0 = _msg_key(_fm0)
        if _k0:
            _fold_keys.add(_k0[:3])

    out: list[dict] = []
    for m in disk[:dstart]:
        if not isinstance(m, dict):
            continue
        if _is_compaction_summary(m):
            continue                        # 旧 digest · 由新 digest 取代
        if _fold_keys and not m.get("compacted"):
            _k3 = _msg_key(m)
            if _k3 and _k3[:3] in _fold_keys:
                _mm = dict(m)
                _mm["compacted"] = True     # 本轮已折走 · 只存盘不发送
                out.append(_mm)
                continue
        out.append(m)                       # 原样保留(compacted 标记随消息带回)

    return out + [digest_msg] + messages2[start:]


def auto_compress(
    messages: list[dict],
    client: Any,
    model: str,
    provider: str,
    keep_last_n: int | None = None,
    model_id: Optional[str] = None,
    force: bool = False,
    system_stable: str = "",
) -> list[dict]:
    """
    自动压缩 v2 (wish-7f0adf2c · Reasonix compact.go 移植)。

    v2 相对 v1 的改进:
      - 用户说过的每句话 (小 user turn) 永不摘要 (partitionFold)
      - 旧 digest 拼接回去 (增量 · 摘要累积不塌缩 · 治漂移)
      - 先免费修剪陈旧大工具结果 (0 次 LLM 调用 · prune_stale_tool_results)
      - 归档: 折叠/修剪的原件落 sessions/archive/ · 可恢复
      - 摘要失败 → 机械折叠兜底 (不 abort · 不循环)
      - 经济性检查: 折叠区太小不值一次摘要调用
      - _persist_rewrite: 压缩结果原子重写 session jsonl (重启不蒸发)
      - force=True (手动触发) 绕过经济性/stuck guard

    参数：
      messages  · 当前会话完整消息列表
      client    · LLM client（用于生成摘要）
      model     · 模型 id
      provider  · 'openai' | 'anthropic'
      keep_last_n · 保留最近多少条不压缩（None=自适应）
      model_id  · 用于查 context_window
      force     · 手动触发 (summarize_session) 时 True · 绕过经济性/stuck guard
      system_stable · v3 · 主对话稳定前缀(抄给摘要调用复用缓存) · 默认 "" 退化为旧行为

    返回：新的 messages 列表
    """
    global _pruned_total

    n = len(messages)
    if n < MIN_MESSAGES_TO_COMPRESS:
        return messages

    # ---- 步骤 2 · 先免费修剪 (0 次 LLM 调用) ----
    messages2, pstats = prune_stale_tool_results(messages)
    if pstats.get("pruned", 0) > 0:
        _pruned_total += pstats["pruned"]
    ctx_window = _get_context_window(model_id)
    if pstats.get("pruned", 0) > 0 and not force:
        prefix = estimate_prefix_tokens()
        threshold = _compact_threshold(ctx_window, prefix)
        if _estimate_tokens(messages2) + prefix < threshold:
            # 修剪后已低于阈值 → prune 单独清掉警报 · 不调 LLM
            # v3 · 同 prune_if_needed: 磁盘要留全量 (内存 messages 是折叠版)
            _fm = _prune_full_from_disk()
            if _fm is not None:
                _persist_rewrite(messages2, _fm)
            # 埋点 (wish-accd038a) · prune 单独成事也记一笔：它是"0 次 LLM 调用"的那类压缩
            _record_compress_event(
                kind="prune_only",
                sid=_state()["current_sid"],
                model=model,
                provider=provider,
                model_id=model_id,
                ctx_window=ctx_window,
                before_tok=_estimate_tokens(messages) + prefix,
                after_tok=_estimate_tokens(messages2) + prefix,
                folded=0,
                kept=0,
                pruned=pstats.get("pruned", 0),
                summary_sec=0.0,
                summary_chars=0,
                disk_full=_fm is not None,
            )
            return messages2

    # ---- 步骤 3 · 规划折叠区 ----
    head = _pinned_prefix_len(messages2, ctx_window)
    # v3 (wish-98d77aaf) · 双向钳制: 上界 TAIL_MAX_WINDOW_FRAC (防小窗爆) ·
    #   下界 TAIL_MIN_WINDOW_FRAC (防大窗降智 · 尾部最短保活量)。256K 下值不变。
    budget = _clamp_budget(TAIL_TOKEN_BUDGET, ctx_window, TAIL_MIN_WINDOW_FRAC, TAIL_MAX_WINDOW_FRAC)
    start = _tail_start(messages2, head, budget)
    if start - head < 2:
        start = _tail_start(messages2, head, budget, min_keep=1)  # 放宽到至少 1 条
    if start - head < 1:
        return messages2  # 尾部已覆盖一切值得保留的 · 别丢 prune 成果

    # ---- 步骤 4 · 分区 (kept 原样保留 / fold 折叠) ----
    kept, fold = _partition_fold(messages2[head:start], ctx_window)
    if not fold:
        return messages2  # 只有 kept user turn · 折叠没省头

    # ---- 步骤 5 · 经济性 ----
    if not force and _estimate_tokens(fold) < MIN_FOLD_TOKENS:
        return messages2

    # ---- 步骤 6 · stuck guard (wish-a5f77893 刀A: 紧急豁免与 token_budget_check 同步) ----
    if not force and _state()["consecutive_compacts"] >= MAX_CONSECUTIVE_COMPACTS:
        if (len(messages2) - _state()["last_compression_turn"]) < EMERGENCY_BREAK_TURNS:
            return messages2
        # 距上次 ≥ EMERGENCY_BREAK_TURNS 轮 → 放行 (token_budget_check 侧已放行·这里不能挡)

    # ---- 步骤 7 · 归档原件 (必须先归档成功才允许动历史 · 数据安全红线) ----
    try:
        archive_path = _archive_messages("compact", fold)
    except Exception:
        return messages2

    # ---- 步骤 8 · 渲染折叠区 (超限保尾弃头 · 原件已在归档) ----
    rendered = "\n\n".join(_stringify_message(m) for m in fold)
    if len(rendered) > MAX_RENDER_CHARS:
        rendered = rendered[-MAX_RENDER_CHARS:] + (
            "\n\n[... 渲染超限 · 最早的若干条未进摘要 · 原件在归档 " + archive_path + " ...]"
        )

    # ---- 步骤 9 · 摘要 (失败重试一次 · 再败机械折叠兜底) ----
    # wish-accd038a · 计时包住"尝试 + 重试"整段：反映真实等待时长(不是单次 LLM 耗时)
    _sum_t0 = time.perf_counter()
    summary = ""
    for attempt in range(2):
        try:
            summary = _generate_summary(rendered, client, model, provider, system_stable=system_stable)
            if summary:
                break
        except Exception:
            summary = ""
    _summary_sec = time.perf_counter() - _sum_t0
    if not summary:
        summary = (
            f"此处折叠了 {len(fold)} 条早期消息以释放上下文 · 自动摘要不可用 · "
            f"原件已归档 {archive_path} · 需要细节请询问 BRO 或读归档。"
        )

    key_facts = extract_key_facts(summary)

    digest_msg = {
        "role": "user",
        "content": (
            f"{SUMMARY_TAG_OPEN}\n"
            f"早前对话摘要 (旧消息已压缩 · 原件归档 {archive_path}):\n"
            f"{summary}\n"
            f"{SUMMARY_TAG_CLOSE}"
        ),
    }
    ack_msg = {
        "role": "assistant",
        "content": "明白。我已装上之前的上下文。继续。",
    }

    # ---- 步骤 10 · 组装 (v3 双版本: 内存折叠版 / 磁盘全量版) ----
    new_messages = messages2[:head] + kept + [digest_msg] + messages2[start:]

    # v4 (wish-e3c3e379) · 磁盘全量版由 _assemble_full_from_disk 以磁盘为基底组装:
    # 历史一条不丢(不再按 compacted 筛选), 已折走的消息在那里面就地补标记。
    # 详见该函数 docstring。
    full_messages = _assemble_full_from_disk(messages2, head, start, digest_msg, fold)

    # digest 后若紧跟 user → 插 ack 防双 user 连排 (两个版本都要 · 结构必须一致)
    tail_roles = [m.get("role") for m in new_messages if isinstance(m, dict)]
    if len(tail_roles) >= 2 and tail_roles[-1] == "user" and tail_roles[-2] == "user":
        new_messages.insert(len(new_messages) - 1, ack_msg)
        # full_messages 可能为 None(拿不到磁盘全量) → 别直接 .insert
        if full_messages is not None:
            full_messages.insert(len(full_messages) - 1, ack_msg)

    # ---- 步骤 11 · 落盘 + 持久化 + 计数 ----
    _st = _state()
    _st["last_compression_turn"] = len(new_messages)
    _st["compression_count"] += 1
    _st["consecutive_compacts"] += 1
    _save_summary_json(summary, len(fold), key_facts)
    # v3 · 磁盘写全量版(UI 可回溯) · 内存继续用折叠版(省 token)
    # full_messages is None = 拿不到磁盘全量 → 本次【不写盘】,
    # 保住磁盘上已有的全量(下一次压缩还能接着累积)。
    if full_messages is not None:
        _persist_rewrite(new_messages, full_messages)

    # ---- 步骤 11.5 · 埋点 (wish-accd038a · 旁路, 写盘失败静默) ----
    # 只在这一处记 compact —— 不分散到各 return (V3 踩过"收尾分散导致漏 return")
    try:
        _pfx_now = estimate_prefix_tokens()
    except Exception:
        _pfx_now = 0
    _record_compress_event(
        kind="compact",
        sid=_st["current_sid"],
        model=model,
        provider=provider,
        model_id=model_id,
        ctx_window=ctx_window,
        before_tok=_estimate_tokens(messages) + _pfx_now,
        after_tok=_estimate_tokens(new_messages) + _pfx_now,
        folded=len(fold),
        kept=len(kept),
        pruned=pstats.get("pruned", 0),
        summary_sec=_summary_sec,
        summary_chars=len(summary),
        disk_full=full_messages is not None,
    )

    # ---- 步骤 12 ----
    return new_messages


# ---------- key fact extraction ----------

# 简单规则——不用 LLM，省 token
_DECISION_PATTERNS = [
    re.compile(r"(拍板|决定|选定|确认|批准|否决|取消|放弃|推迟)[：:]\s*(.+?)(?:[。\n]|$)"),
    re.compile(r"(BRO|用户)\s*(说|提出|要求|让|希望|要)\s*(.+?)(?:[。\n]|$)"),
    re.compile(r"(OPUS|我)\s*(做了|完成了|交付了|上线了|修复了|加了|改了)\s*(.+?)(?:[。\n]|$)"),
]


def extract_key_facts(summary_text: str) -> list[str]:
    """从压缩摘要中用规则提取关键事实。

    返回最多 8 条，用于落 sessions/{sid}.summary.json。
    未来 wish-273374f6 (FTS5) 会直接索引这个数组。
    """
    facts: list[str] = []

    for pat in _DECISION_PATTERNS:
        for m in pat.finditer(summary_text):
            fact = m.group(0).strip()
            if len(fact) > 4 and fact not in facts:
                facts.append(fact)
            if len(facts) >= 8:
                return facts

    return facts


# ---------- summary.json 落盘 ----------

_SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"
_ARCHIVE_DIR = _SESSIONS_DIR / "archive"


def _archive_messages(kind: str, msgs: list[dict]) -> str:
    """把被折叠/被修剪的原始消息落盘归档 · tmp+os.replace 原子写。

    sessions/archive/{sid}-{kind}-{ts}.jsonl · 一条 message 一行 (原样 dump dict)。
    失败抛异常 —— 调用方必须 archive 成功后才允许改历史 (数据安全红线)。
    """
    global _archived_files
    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    sid = _state()["current_sid"] or "anon"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = _ARCHIVE_DIR / f"{sid}-{kind}-{ts}.jsonl"

    import tempfile
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=".archive.", suffix=".tmp", dir=str(_ARCHIVE_DIR)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            for m in msgs:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
        os.replace(tmp_name, path)
        _archived_files += 1
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    # 刀5-live (wish-a5f77893 · 2026-09-16): 归档即入索引 —— 不靠用户想起、不靠全量重建。
    # 失败只影响“立刻可搜”; 下次 daemon 启动 refresh_stale 按 mtime 自动补 (check_stale 会检出)。
    try:
        from workers.memory_index import index_archive_file
        index_archive_file(path)
    except Exception as e:
        logger.warning("归档入索引失败(下次启动自动补): %s", e)
    try:
        return str(path.relative_to(_SESSIONS_DIR.parent))
    except ValueError:
        return str(path)  # 归档目录在 sessions/ 外 (测试/自建) → 用绝对路径


def _save_summary_json(summary: str, from_turns: int, key_facts: list[str]) -> None:
    """把本次压缩的摘要落 sessions/{sid}.summary.json。

    格式：
      {
        "compressed_at": "ISO",
        "from_turns": N,
        "summary": "...",
        "key_facts": [...]
      }
    """
    _st = _state()
    if not _st["current_sid"]:
        return

    _SESSIONS_DIR.mkdir(exist_ok=True)
    path = _SESSIONS_DIR / f"{_st['current_sid']}.summary.json"

    entry = {
        "compressed_at": datetime.now().isoformat(timespec="seconds"),
        "from_turns": from_turns,
        "summary": summary,
        "key_facts": key_facts,
    }

    # 读取已有记录，追加新条目（数组形式）
    existing: list[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8")) or []
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(entry)
    # 只保留最近 20 条压缩记录
    existing = existing[-20:]

    # atomic write
    import tempfile

    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=".summary.", suffix=".tmp", dir=str(_SESSIONS_DIR)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    # 卷五十八续 · 接通血管: 摘要落盘成功即推进 FTS5 召回索引 (best-effort · 不阻塞压缩)
    try:
        from workers.memory_index import index_session_summary

        index_session_summary(_st["current_sid"], summary, key_facts)
    except Exception:
        pass


def get_last_compression_stats() -> dict:
    """返回最近一次压缩的统计信息（给日志/UI 用）。"""
    st = _state()
    return {
        "compression_count": st["compression_count"],
        "last_compression_at_turn": st["last_compression_turn"],
        "current_sid": st["current_sid"],
        "consecutive_compacts": st["consecutive_compacts"],
        "pruned_total": _pruned_total,
        "archived_files": _archived_files,
    }


# ---------- 埋点 · 压缩事件 append-only (wish-accd038a) ----------
# 《上下文治理上游精读 · DSH 设计手册》首页约定 09-17~09-19 为对照基线窗口，
# 采集「压缩触发次数 / 压缩后水位 / 摘要耗时 / 摘要 token 成本 / 面板与磁盘偏差」。
# 实测：耗时与压后水位两格全盲（前者全库零痕迹，后者只在危险区报警时才记）→
# 本函数【只补记录, 不动任何压缩逻辑与阈值】。
# 纪律：埋点是旁路 —— 写盘失败静默跳过, 绝不允许影响压缩本身（压缩是主路）。
_COMPRESS_EVENTS_PATH = Path("data/runtime/compress_events.jsonl")

# 埋点写盘失败计数 (模块级 · 跨会话混计无害)。
# 为什么不是纯 pass: 静音 = 出事时没有信号 (V3 code_review 同一坑)。
# 首次失败 debug 留痕、连续失败每 100 次 warning 一次 —— 既不刷屏、又不失联。
_compress_event_fail_count: int = 0


def _record_compress_event(
    kind: str,
    sid: str,
    model: str,
    provider: str,
    model_id: Optional[str],
    ctx_window: int,
    before_tok: int,
    after_tok: int,
    folded: int,
    kept: int,
    pruned: int,
    summary_sec: float,
    summary_chars: int,
    disk_full: bool,
) -> None:
    """落一行压缩事件。kind: 'compact' | 'prune_only'。

    存【原始值】(token 数 / 秒)而不是百分比 —— 百分比由展示层拿 ctx_window 现算，
    这样以后改窗口口径不必回改历史数据。
    """
    # global 必须在函数内任何赋值之前声明 (Python 硬规则)
    global _compress_event_fail_count
    try:
        rec = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "kind": kind,
            "sid": sid,
            "model": model,
            "provider": provider,
            "model_id": model_id,
            "ctx_window": ctx_window,
            "before_tok": before_tok,
            "after_tok": after_tok,
            "before_pct": round(before_tok / ctx_window * 100, 1) if ctx_window else None,
            "after_pct": round(after_tok / ctx_window * 100, 1) if ctx_window else None,
            "folded": folded,
            "kept": kept,
            "pruned": pruned,
            "summary_sec": round(summary_sec, 2),
            "summary_chars": summary_chars,
            "disk_full": disk_full,
        }
        _COMPRESS_EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _COMPRESS_EVENTS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        # 写成功即清零 —— 这个计数器的语义是"【连续】失败"，不清零名不副实
        _compress_event_fail_count = 0
    except Exception as exc:
        # 埋点失败绝不影响压缩（旁路纪律）—— 但不许彻底静音：
        # 首次 debug 留痕（DEBUG 级可定位），【连续】失败每 100 次升为 warning。
        # 与成功路径的清零配对: 中途成功一次 → 计数归零 → 下次失败又从 debug 开始。
        _compress_event_fail_count += 1
        if _compress_event_fail_count == 1:
            logger.debug("[压缩埋点] 写盘失败·已跳过 (旁路·不影响压缩): %s", exc, exc_info=True)
        elif _compress_event_fail_count % 100 == 0:
            logger.warning(
                "[压缩埋点] 已连续失败 %d 次 · 最后原因: %s (不影响压缩·但对照数据会缺)",
                _compress_event_fail_count, exc,
            )
