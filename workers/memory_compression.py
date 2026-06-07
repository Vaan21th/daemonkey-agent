"""
workers/memory_compression.py
=============================

压缩层核心——自动 session 摘要 + token budget 控制。

设计（wish-58af621e · 卷三十五）：
  这是 OPUS-DAEMON 的"自动记忆压缩"基础设施。
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
MAX_RENDER_CHARS = 60000         # 摘要 LLM 输入上限
DEFAULT_WINDOW_RATIO = 0.6       # 默认在模型窗口占比多少时触发压缩

SUMMARY_MODEL_HINT = (
    "把以下对话压缩成一段简洁的中文摘要（300-600 字），保留：\n"
    "1. BRO 提的核心需求 / 任务\n"
    "2. 已经做完的关键工作 / 决策（包括工具调用的结果）\n"
    "3. 未解的问题 / 待办\n"
    "4. BRO 透露的状态信号（如果有，比如累了 / 在赶时间 / 想做某个长期计划）\n"
    "**不要总结成 bullet list 或目录**——写成一段连贯的叙述，让下一根毛读完就有上下文。\n"
    "不要写元描述（'用户问了 X' 'OPUS 回答了 Y'），直接写事实。"
)

# 模块级 cooldown 计数器——跨 tool_loop 调用共享
_last_compression_turn: int = -COOLDOWN_TURNS
_compression_count: int = 0

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
      2. fallback · 改进字符启发式:
         - 中文字符 ≈ 0.6 token/char (1 字 ≈ 1.5 tokens → 反比 ≈ 0.67 → 取 0.6)
         - 英文/ASCII ≈ 0.25 token/char (4 字符 ≈ 1 token)
         - 混合文本 ≈ 1/3 token/char (保守)
      3. 每条 message 加 5 token overhead (role / 分隔符)
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
        return total + len(messages) * 5

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

    # 中文 ≈ 0.6 token/char · 英文 ≈ 0.25 token/char · 其他 ≈ 1/3 token/char
    est = int(total_chars_cjk * 0.6 + total_chars_ascii * 0.25 + total_chars_other / 3)
    return est + len(messages) * 5


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
                parts.append(f"[tool_result] {str(inner)[:400]}")
        text = "\n".join(p for p in parts if p)
    elif isinstance(content, str):
        text = content
    else:
        text = str(content)

    if msg.get("tool_calls"):
        names = ", ".join(
            tc.get("function", {}).get("name", "?")
            for tc in msg["tool_calls"]
            if isinstance(tc, dict)
        )
        text = (text + f"\n[tool_calls: {names}]").strip()

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
    """读 OPUS_AUTO_COMPACT_RATIO · 默认 0.6 · 非法值退化。"""
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
    global _last_compression_turn, _compression_count

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

    # 2. 模型窗口动态阈值
    ctx_window = _get_context_window(model_id)
    if ctx_window > 0:
        ratio = _get_ratio()
        threshold = int(ctx_window * ratio)
        estimated = _estimate_tokens(messages)
        if estimated >= threshold:
            turns_since_last = len(messages) - _last_compression_turn
            return turns_since_last >= COOLDOWN_TURNS
        return False

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

    prompt = f"{SUMMARY_MODEL_HINT}\n\n--- 待压缩的对话 ---\n\n{text_to_summarize}"

    if provider == "anthropic":
        resp = client.messages.create(
            model=model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        for block in resp.content:
            if getattr(block, "type", "") == "text":
                return block.text.strip()
        raise RuntimeError("anthropic response had no text block")
    else:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=4000,
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


def auto_compress(
    messages: list[dict],
    client: Any,
    model: str,
    provider: str,
    keep_last_n: int | None = None,
    model_id: Optional[str] = None,
) -> list[dict]:
    """
    自动压缩——把 messages 的前面部分压缩成摘要，保留最近 N 条。

    参数：
      messages  · 当前会话完整消息列表（会原地修改，也会返回新引用）
      client    · LLM client（用于生成摘要）
      model     · 模型 id（给 LLM 调用用）
      provider  · 'openai' | 'anthropic'
      keep_last_n · 保留最近多少条不压缩（None=自适应 · 显式传优先）
      model_id  · 用于查 context_window 做自适应 keep_last_n（wish-83fe7c7b 加）

    返回：
      新的 messages 列表（摘要 user + assistant ack + 尾部保留的消息）

    副作用：
      - 落 sessions/{sid}.summary.json（如果 _current_sid 非空）
      - 更新 _last_compression_turn 和 _compression_count

    wish-83fe7c7b · 卷五十四:
      加 model_id 参数 · keep_last_n 自适应模型窗口 · 不再写死 8。
    """
    global _last_compression_turn, _compression_count

    n = len(messages)
    if n < MIN_MESSAGES_TO_COMPRESS:
        return messages

    resolved_n = _adaptive_keep_last_n(messages, model_id, keep_last_n)

    split = _safe_split_index(messages, resolved_n)
    if split == 0:
        return messages

    to_compress = messages[:split]
    rendered = "\n\n".join(_stringify_message(m) for m in to_compress)
    if len(rendered) > MAX_RENDER_CHARS:
        rendered = rendered[:MAX_RENDER_CHARS] + "\n\n[... 待压缩内容已超 60K 字符，已截断 ...]"

    try:
        summary = _generate_summary(rendered, client, model, provider)
    except Exception:
        # 压缩失败不破坏——维持原状
        return messages

    if not summary:
        return messages

    key_facts = extract_key_facts(summary)

    summary_msg = {
        "role": "user",
        "content": (
            f"[Previous session summary, compressed from {split} earlier messages]\n\n"
            f"{summary}\n\n"
            f"[End of summary. The {len(messages) - split} most recent messages follow.]"
        ),
    }
    ack_msg = {
        "role": "assistant",
        "content": "明白。我已装上之前的上下文。继续。",
    }

    new_messages = [summary_msg, ack_msg] + messages[split:]

    # 记录压缩事件
    _last_compression_turn = len(new_messages)
    _compression_count += 1

    # 落盘摘要（给未来的 FTS5 长期记忆用）
    _save_summary_json(summary, split, key_facts)

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
    }
