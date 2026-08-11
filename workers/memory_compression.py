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
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ---------- 常量 ----------

DEFAULT_KEEP_LAST_N = 8          # 保留最近 N 条不压缩（模型窗口未知时 fallback）
MIN_KEEP_LAST_N = 4              # 自适应 keep_last_n 硬下限
MAX_KEEP_LAST_N = 20             # 自适应 keep_last_n 硬上限
MIN_MESSAGES_TO_COMPRESS = 12    # 总数少于此不压缩（工具手动触发用）
AUTO_COMPRESS_THRESHOLD = 30     # 自动压缩触发阈值（消息数 · 模型窗口未知时 fallback）
COOLDOWN_TURNS = 5               # 两次自动压缩之间至少隔 N 轮
_TOK_SAFETY_MULT = 1.25          # 估算保守系数 · 防跨 tokenizer 低估 (DeepSeek tokenizer ≠ cl100k_base)
MAX_RENDER_CHARS = 120000         # 摘要 LLM 输入上限 (v2: 60K→120K · 超限保尾弃头)
DEFAULT_WINDOW_RATIO = 0.7       # 默认在模型窗口占比多少时触发压缩 (调优 0.6→0.7:配合工具瘦身+任务账本·减少重复摘要造成的"漂移/失忆"·仍比 CC≈0.83 保守)

# ---------- v2 · Reasonix 移植 (compact.go/prune.go · wish-7f0adf2c) ----------
SUMMARY_TAG_OPEN  = "<compaction-summary>"
SUMMARY_TAG_CLOSE = "</compaction-summary>"
PRUNED_MARKER = "[已修剪工具结果 — "
MIN_FOLD_TOKENS = 400            # 经济性: 可折叠区低于此 token 不值一次摘要调用
TAIL_TOKEN_BUDGET = int(os.environ.get("OPUS_COMPACT_TAIL_TOKENS") or "16384")
TAIL_MAX_WINDOW_FRAC = 0.5       # 尾部 token 预算不超窗口此比例
PRUNE_MIN_CHARS = int(os.environ.get("OPUS_PRUNE_MIN_CHARS") or "1024")
PRUNE_RATIO = float(os.environ.get("OPUS_COMPACT_PRUNE_RATIO") or "0.6")  # 先修剪档
PIN_FIRST_USER_MAX_TOKENS = 1500
PIN_FIRST_USER_WINDOW_FRAC = 0.15
MAX_CONSECUTIVE_COMPACTS = 2     # 连续压缩仍超阈值 → 暂停自动压缩 (防每轮重建缓存)
_TOK_PER_CHAR_FALLBACK = 0.35    # CJK 偏多·介于 Go 0.25 与 1.0 之间
DEFAULT_ABS_CAP_TOKENS = 256_000  # 0.8.8 · 压缩绝对线: 大窗口(1M)模型普通会话到不了 70% → 按体验拐点硬触发

SUMMARY_MODEL_HINT = (
    "把下面的对话历史压缩成结构化简报。规则：\n"
    "1. 按固定小标题组织：`持久事实与约束` / `目标` / `决策与理由` / `文件与代码` / `命令与结果` / `错误与修复` / `待办与下一步`\n"
    "2. 用 bullet 碎片，不写散文；标识符 / 路径 / 数字逐字保留，不改写不省略\n"
    "3. 不知道就不写；无内容的小标题省略；不要编造\n"
    "4. 不写元描述（'用户问了 X' 'OPUS 回答了 Y'），直接写事实\n"
    "5. 控制在 300-600 字"
)

# 模块级 cooldown 计数器——跨 tool_loop 调用共享
_last_compression_turn: int = -COOLDOWN_TURNS
_compression_count: int = 0
_consecutive_compacts: int = 0   # v2 · 连续压缩计数 (防每轮重建缓存 · wish-7f0adf2c)
_pruned_total: int = 0           # v2 · 累计修剪的工具结果数
_archived_files: int = 0         # v2 · 累计归档文件数

# 模块级 session_id——由上层在每次新一轮对话开始时设置
_current_sid: str = ""

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
    """让压缩层知道当前 session id，以便落 summary.json。"""
    global _current_sid
    _current_sid = sid


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


def _pinned_prefix_len(msgs: list[dict], ctx_window: int) -> int:
    """从头部数出【永不折叠】的段: 首个可 pin 的 user turn + 紧随的连续旧 digest。

    旧摘要永远不再进折叠区 → 摘要累积 (增量) · 不会二次丢失。
    """
    head = 0
    for i, m in enumerate(msgs):
        if _pinnable_user_turn(m, ctx_window):
            head = i + 1
        elif head > 0 and i == head:  # 头部段结束后第一个非 pin 消息 → 停
            break
        elif head == 0:
            # 还没遇到 pin 点 · 跳过 system/工具噪音直到第一个 user
            if m.get("role") == "user":
                if _pinnable_user_turn(m, ctx_window):
                    head = i + 1
                break
    return head


def _partition_fold(region: list[dict], ctx_window: int) -> tuple[list[dict], list[dict]]:
    """把折叠区分成 kept (原样保留) 与 fold (可折叠进摘要)。

    kept = 小 user turn + 旧 digest (用户原话/已固化摘要永不丢)
    fold = 其余 (工具往返 / 大消息 / assistant 过程)
    """
    kept: list[dict] = []
    fold: list[dict] = []
    for m in region:
        if _pinnable_user_turn(m, ctx_window):
            kept.append(m)
        else:
            fold.append(m)
    return kept, fold


def _tail_start(msgs: list[dict], head: int, budget_tokens: int, min_keep: int = 4) -> int:
    """从最新往旧走 · 累积到预算上限 (但至少留 min_keep 条) · 边界对齐掉 tool 消息。

    返回尾部起点 index (含) —— [start, len) 保留原文。
    """
    start = len(msgs)
    acc = 0
    for i in range(len(msgs) - 1, head, -1):
        c = int(_msg_chars(msgs[i]) * _tok_per_char())
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
    """查模型上下文窗口 · 拿不到返 0（上层退化到老逻辑）。"""
    if not model_id:
        return 0
    try:
        from provider_presets import context_window_for
        return context_window_for(model_id)
    except Exception:
        return 0


def _get_ratio() -> float:
    """读 OPUS_AUTO_COMPACT_RATIO · 默认 0.7 · 非法值退化 (省 token 想更狠→调 0.6·想留更多原文→0.8)。"""
    raw = (os.environ.get("OPUS_AUTO_COMPACT_RATIO") or "").strip()
    if not raw:
        return DEFAULT_WINDOW_RATIO
    try:
        v = float(raw)
        if 0.1 <= v <= 0.95:
            return v
    except (ValueError, TypeError):
        pass
    return DEFAULT_WINDOW_RATIO


def _get_abs_cap() -> int:
    """0.8.8 · 压缩绝对线 (env OPUS_AUTO_COMPACT_MAX_TOKENS · 缺省 256K)。

    为什么: 1M 窗口 × 0.7 = 700K · 普通会话 80-250K 永远够不到 → 永不压缩 → 全量发送慢。
    绝对线让大窗口模型按"体验拐点"触发 (不依赖窗口比例) · 小窗口模型不受影响 (min 取小)。
    下限钳制 40K · 防设太低导致每几轮就压缩+重建缓存 (热抖动)。
    """
    raw = (os.environ.get("OPUS_AUTO_COMPACT_MAX_TOKENS") or "").strip()
    if raw:
        try:
            v = int(raw)
            if v > 0:
                return max(40_000, v)
        except (ValueError, TypeError):
            pass
    return DEFAULT_ABS_CAP_TOKENS


# ---------- auto-compress ----------

def token_budget_check(
    messages: list[dict],
    model_id: Optional[str] = None,
) -> bool:
    """判断该不该自动压缩 (三触发: token 预算 / 消息数 / env 阈值 · 任一满足触发)

    触发优先级:
      1. env OPUS_AUTO_COMPACT_THRESHOLD 显式设了 → 用它（最高优先·保持向后兼容）
      2. model_id 已知 + context_window 能查到 → 阈值 = context_window × ratio
      3. 退化 → 消息数 >= AUTO_COMPRESS_THRESHOLD (30)

    都得过 cooldown (距上次压缩 >= COOLDOWN_TURNS 轮 · 防热抖动)

    返回 True → 上层该调 auto_compress()。

    wish-83fe7c7b · 卷五十四:
      加 model_id 参数 · 按模型窗口动态算触发阈值 · 替掉写死的 30 条。
    """
    global _last_compression_turn, _compression_count, _consecutive_compacts

    # 1. env 显式阈值（最高优先）
    try:
        token_threshold_env = (os.environ.get("OPUS_AUTO_COMPACT_THRESHOLD") or "0").strip()
        token_threshold = int(token_threshold_env)
        if token_threshold > 0:
            estimated = _estimate_tokens(messages)
            if estimated >= token_threshold:
                # 过 cooldown
                turns_since_last = len(messages) - _last_compression_turn
                if turns_since_last >= COOLDOWN_TURNS:
                    return True
                return False
            # 没过 token 阈值 → 不触发（env 显式设了就不走消息数 fallback）
            return False
    except (ValueError, TypeError):
        pass

    # 2. 模型窗口动态阈值 (0.8.8: min(窗口比例, 绝对线) · 治大窗口普通会话永不压缩)
    ctx_window = _get_context_window(model_id)
    if ctx_window > 0:
        ratio = _get_ratio()
        threshold = min(int(ctx_window * ratio), _get_abs_cap())
        estimated = _estimate_tokens(messages)
        _hit = estimated >= threshold
        if not _hit and len(messages) >= 200 and estimated >= threshold * 0.5:
            # wish-8f122254 · 条数爆了 + 估算逼近阈值一半 → 跨 tokenizer 低估漏网 · 强制触发
            _hit = True
        if not _hit:
            _consecutive_compacts = 0   # v2 · 估算低于阈值 → 连续压缩计数清零
            return False
        if _consecutive_compacts >= MAX_CONSECUTIVE_COMPACTS:
            # v2 · 连续压缩仍超阈值 → 暂停自动压缩 (防每轮重建缓存 · wish-7f0adf2c)
            return False
        turns_since_last = len(messages) - _last_compression_turn
        return turns_since_last >= COOLDOWN_TURNS

    # 3. 退化 · 消息数阈值
    if len(messages) >= AUTO_COMPRESS_THRESHOLD:
        turns_since_last = len(messages) - _last_compression_turn
        return turns_since_last >= COOLDOWN_TURNS

    return False


def _generate_summary(
    text_to_summarize: str,
    client: Any,
    model: str,
    provider: str,
) -> str:
    """调 LLM 生成摘要。失败抛异常。"""
    if client is None:
        raise RuntimeError("LLM client not available for summary generation")

    # SUMMARY_MODEL_HINT 带 BRO/OPUS/「下一根毛」自指·会让摘要器照着产出母体 lore·
    # 在使用点按实例去母体化(母体 no-op)。
    from identity import localize_narration as _ln
    prompt = f"{_ln(SUMMARY_MODEL_HINT)}\n\n--- 待压缩的对话 ---\n\n{text_to_summarize}"

    from daemon_runtime import bg_max_tokens
    _mt = bg_max_tokens(default=4000)
    if provider == "anthropic":
        resp = client.messages.create(
            model=model,
            max_tokens=_mt,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in resp.content:
            if getattr(block, "type", "") == "text":
                return block.text.strip()
        raise RuntimeError("anthropic response had no text block")
    else:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=_mt,
            messages=[{"role": "user", "content": prompt}],
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

    返回 (新 messages, stats{pruned, saved_chars, archive})
    """
    candidates: list[tuple[int, str]] = []
    for i, m in enumerate(messages):
        if not isinstance(m, dict) or m.get("role") != "tool":
            continue
        if len(messages) - i <= 8:
            continue  # 保护尾
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
        placeholder = (
            f"{PRUNED_MARKER}{name} · 原 {len(content)} 字符 · "
            f"已归档 {archive_path} · 需要原文请重新调用该工具或读归档]"
        )
        new_msgs[i] = dict(orig)
        new_msgs[i]["content"] = placeholder
        saved += len(content)

    return new_msgs, {"pruned": len(candidates), "saved_chars": saved, "archive": archive_path}


def _persist_rewrite(messages: list[dict]) -> None:
    """v2 · 压缩/修剪结果原子重写 session jsonl (治重启蒸发 · wish-7f0adf2c)。

    延迟 import daemon_session 防循环。失败不抛 (压缩本身已生效 · 持久化尽力而为)。
    """
    global _current_sid
    if not _current_sid:
        return
    try:
        from daemon_session import rewrite_session
        rewrite_session(_current_sid, messages)
    except Exception:
        logging.getLogger("opus.memcomp").warning(
            "压缩重写 session jsonl 失败 · 磁盘仍是旧版 · 重启会回退到压缩前", exc_info=True)


def auto_compress(
    messages: list[dict],
    client: Any,
    model: str,
    provider: str,
    keep_last_n: int | None = None,
    model_id: Optional[str] = None,
    force: bool = False,
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

    返回：新的 messages 列表
    """
    global _last_compression_turn, _compression_count, _consecutive_compacts, _pruned_total

    n = len(messages)
    if n < MIN_MESSAGES_TO_COMPRESS:
        return messages

    # ---- 步骤 2 · 先免费修剪 (0 次 LLM 调用) ----
    messages2, pstats = prune_stale_tool_results(messages)
    if pstats.get("pruned", 0) > 0:
        _pruned_total += pstats["pruned"]
    ctx_window = _get_context_window(model_id)
    if pstats.get("pruned", 0) > 0 and not force:
        threshold = int(ctx_window * _get_ratio()) if ctx_window > 0 else AUTO_COMPRESS_THRESHOLD * 1000
        if _estimate_tokens(messages2) < threshold:
            # 修剪后已低于阈值 → prune 单独清掉警报 · 不调 LLM
            _persist_rewrite(messages2)
            return messages2

    # ---- 步骤 3 · 规划折叠区 ----
    head = _pinned_prefix_len(messages2, ctx_window)
    budget = TAIL_TOKEN_BUDGET
    if ctx_window > 0:
        budget = min(budget, int(ctx_window * TAIL_MAX_WINDOW_FRAC))
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

    # ---- 步骤 6 · stuck guard ----
    if not force and _consecutive_compacts >= MAX_CONSECUTIVE_COMPACTS:
        return messages2

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
    summary = ""
    for attempt in range(2):
        try:
            summary = _generate_summary(rendered, client, model, provider)
            if summary:
                break
        except Exception:
            summary = ""
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

    # ---- 步骤 10 · 组装 ----
    new_messages = messages2[:head] + kept + [digest_msg] + messages2[start:]
    # digest 后若紧跟 user → 插 ack 防双 user 连排
    tail_roles = [m.get("role") for m in new_messages if isinstance(m, dict)]
    if len(tail_roles) >= 2 and tail_roles[-1] == "user" and tail_roles[-2] == "user":
        new_messages.insert(len(new_messages) - 1, ack_msg)

    # ---- 步骤 11 · 落盘 + 持久化 + 计数 ----
    _last_compression_turn = len(new_messages)
    _compression_count += 1
    _consecutive_compacts += 1
    _save_summary_json(summary, len(fold), key_facts)
    _persist_rewrite(new_messages)

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
    global _current_sid, _archived_files
    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    sid = _current_sid or "anon"
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
    global _current_sid
    if not _current_sid:
        return

    _SESSIONS_DIR.mkdir(exist_ok=True)
    path = _SESSIONS_DIR / f"{_current_sid}.summary.json"

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

        index_session_summary(_current_sid, summary, key_facts)
    except Exception:
        pass


def get_last_compression_stats() -> dict:
    """返回最近一次压缩的统计信息（给日志/UI 用）。"""
    return {
        "compression_count": _compression_count,
        "last_compression_at_turn": _last_compression_turn,
        "current_sid": _current_sid,
        "consecutive_compacts": _consecutive_compacts,
        "pruned_total": _pruned_total,
        "archived_files": _archived_files,
    }
