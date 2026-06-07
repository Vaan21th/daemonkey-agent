"""
dynamic_telemetry.py
====================

wish-1d286099 · 给 daemon OPUS 装上"在场感的眼睛"
--------------------------------------------------

问题：daemon system_prompt 是启动时一次性缓存的静态 soul 文件，每次 chat
OPUS 看到的都是同样的"静态身份 + BRO 这条消息 + 历史"。缺动态 telemetry
（当前时间 / BRO 上一条消息多久前 / daemon 起来多久），导致 daemon OPUS
想关心 BRO 时只能机械调 Get-Date → BRO 觉得刻意。

方案：每次 chat 请求时在 system_prompt 末尾拼一段动态 telemetry，跟 Cursor
IDE 自动塞 `<timestamp>` / `<git_status>` 同款哲学——host 偷偷塞，LLM 自然消化。

wish-bf6a14fa · 扩展：上次对话摘要 + Git 脏工作区
---------------------------------------------------
纯读磁盘 + 字符串操作，不调 LLM。

设计原则（跟 Cursor 端一致）：
  1. host 偷偷塞 · LLM 自然推理 —— 不要复述这段
  2. telemetry 在 system prompt 末尾 · 不在 user message 里
  3. 不做 proactive push —— 只让 LLM 看到后自己判断该不该说
  4. 跟 BRO 当前问题无关时静默
"""

from __future__ import annotations

import json
import pathlib

from agent_tools._subprocess_helper import no_window_kwargs
from agent_tools._git_lock import daemon_git_lock
import subprocess
import time
from datetime import datetime
from typing import Optional

from daemon_runtime import RUNTIME


def _classify_hour(h: int) -> str:
    if 23 <= h or h < 5:
        return "深夜"
    if 5 <= h < 8:
        return "清晨"
    if 8 <= h < 12:
        return "上午"
    if 12 <= h < 14:
        return "中午"
    if 14 <= h < 18:
        return "下午"
    return "晚上"


def _format_gap(sec: Optional[float]) -> str:
    if sec is None:
        return "首次对话"
    if sec < 60:
        return f"{int(sec)} 秒前"
    if sec < 3600:
        return f"{int(sec / 60)} 分钟前"
    if sec < 86400:
        return f"{sec / 3600:.1f} 小时前"
    return f"{int(sec / 86400)} 天前"


def _get_last_summary(current_session_id: str) -> str:
    """扫 sessions/ 目录 · 找最近一个非当前 session 的 BRO user message · 压成一句摘要。

    纯字符串操作 · 不调 LLM。 开销 ~1ms（扫目录 + 读 jsonl 末尾 20 行）。
    """
    sessions_dir = pathlib.Path("sessions")
    if not sessions_dir.is_dir():
        return ""

    # 所有 jsonl · 按 mtime 降序
    jsonl_files = sorted(
        [f for f in sessions_dir.glob("*.jsonl")],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    # 找第一个不是当前 session 的
    prev = None
    for f in jsonl_files:
        if f.stem != current_session_id:
            prev = f
            break
    if prev is None:
        return ""

    # 读末尾 ~20 行 · 取最后 3 条 BRO user message
    try:
        lines = prev.read_text(encoding="utf-8").strip().split("\n")
        recent = lines[-20:]
        user_messages: list[str] = []
        for line in recent:
            try:
                msg = json.loads(line)
                # 卷六十 · 主动 CALL 的系统唤醒也是 role=user (src=proactive) · 不是 BRO 说的话 · 跳过
                if msg.get("role") == "user" and (msg.get("meta") or {}).get("src") != "proactive":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        clean = content.strip().replace("\n", " ")
                        if clean:
                            user_messages.append(clean)
            except Exception:
                pass

        if not user_messages:
            return ""

        # 取最后 3 条 · 每条截到 ~40 字 · 拼成一句
        last = user_messages[-3:]
        combined = " · ".join(last)
        if len(combined) > 150:
            combined = combined[:147] + "..."

        return f"- 上次聊到: {combined}\n"

    except Exception:
        return ""


def _get_git_dirty_line() -> str:
    """跑 git status --porcelain · 有未提交返回提醒行 · 干净返回空。

    分支名从 git branch --show-current 取。 开销 ~0.05s（两个 git 子进程）。
    """
    try:
        with daemon_git_lock("telemetry:git"):
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, timeout=5,
                **no_window_kwargs(),
                ).stdout.strip()
            if not branch:
                return ""

            porcelain = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=5,
                **no_window_kwargs(),
            ).stdout.strip()
        if not porcelain:
            return ""

        count = len([l for l in porcelain.split("\n") if l.strip()])
        if count == 0:
            return ""

        return f"- Git: 当前分支 {branch} · {count} 文件未提交\n"

    except Exception:
        return ""


def _get_abandoned_outcomes_line() -> str:
    """卷五十四 · 把 BRO 已放弃的方向塞进 telemetry (闭环·Hermes '建立对你的深度模型')。

    abandoned outcomes 是 BRO 能力边界最强的负信号。 每轮注入一行 (最多 3 个·只放
    标题 + 短理由) · 让主对话里的 OPUS 别再推荐 BRO 已经否决过的方向。 纯读·~50 token。
    """
    try:
        from workers.outcomes import list_outcomes
        summary = list_outcomes(max_items=50)
        items = [
            it for it in (summary.get("items") or [])
            if it.get("status") == "abandoned"
        ]
        if not items:
            return ""
        parts: list[str] = []
        for it in items[:3]:
            title = (it.get("opp_title") or "?").strip()[:24]
            reason = (it.get("decision_reason") or "").strip().replace("\n", " ")
            if reason:
                parts.append(f"《{title}》({reason[:28]})")
            else:
                parts.append(f"《{title}》")
        more = f" 等共 {len(items)} 个" if len(items) > 3 else ""
        return f"- BRO 已放弃方向 (别再推荐·除非有新理由): {' · '.join(parts)}{more}\n"
    except Exception:
        return ""


def build_dynamic_telemetry(session_id: str) -> str:
    """构造一段 telemetry 追加到 system prompt 末尾。

    每次 /chat 请求调一次 · 开销 ~2ms（读 jsonl 末尾 20 行 + 算时间差 + 扫 sessions + git status）。
    """
    from daemon_session import get_last_user_turn_ts

    now = datetime.now()

    # BRO 上一条消息距今多久
    last_ts_str = get_last_user_turn_ts(session_id)
    gap_sec: Optional[float] = None
    if last_ts_str:
        try:
            last_dt = datetime.fromisoformat(last_ts_str)
            gap_sec = (now - last_dt).total_seconds()
        except (ValueError, TypeError):
            pass

    # daemon 启动多久
    uptime_sec = time.time() - RUNTIME.started_at if RUNTIME.started_at > 0 else 0.0

    # wish-bf6a14fa · 上次对话摘要 + Git 脏区
    summary_line = _get_last_summary(session_id)
    git_line = _get_git_dirty_line()
    abandoned_line = _get_abandoned_outcomes_line()

    return (
        "\n\n---\n\n"
        "## 此刻的运行时 telemetry (daemon 自动注入 · 不要复述这一段 · 消化后自然推理)\n\n"
        f"- 现在: {now:%Y-%m-%d %H:%M %A}  ({_classify_hour(now.hour)})\n"
        f"- BRO 上一条消息: {_format_gap(gap_sec)}\n"
        f"- daemon 起来: {_format_gap(uptime_sec)}\n"
        f"{summary_line}"
        f"{git_line}"
        f"{abandoned_line}"
        "\n"
        "使用纪律:\n"
        "  · BRO 没问你时间不要主动报时 · **消化这些事实然后推理**\n"
        "  · 凌晨 / BRO 长时间没消息后突然回来 / daemon 刚起 → 可以**自然带一句关心或问候**\n"
        "    但不要每次都带 · 不要机械化\n"
        "  · 跟 BRO 当前问题无关时 · 这段就当没看见\n"
    )
