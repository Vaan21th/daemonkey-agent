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

wish-bf6a14fa · 扩展：Git 脏工作区（上次对话摘要已卸）
---------------------------------------------------
纯读磁盘 + 字符串操作，不调 LLM。
2026-08-29 · 「上次聊到」mtime 抽奖已证无用（串台、Flash 当任务）· 从每轮
prompt / 茶桌 / 主动 CALL 卸下。连续性走状态卡、画像、relevant_memories；
BRO 点名再用 session_search / recall_memory(scope=sessions)。算法留在
`_get_last_summary`，不再接线。

设计原则（跟 Cursor 端一致）：
  1. host 偷偷塞 · LLM 自然推理 —— 不要复述这段
  2. telemetry 在 system prompt 末尾 · 不在 user message 里
  3. 不做 proactive push —— 只让 LLM 看到后自己判断该不该说
  4. 跟 BRO 当前问题无关时静默
"""

from __future__ import annotations

import json
import pathlib
import re

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
    """人话化时间差 · 粗粒度（telemetry 粗化）。

    为什么粗：秒级精度对「该不该关心」没有增量信息，却让这段文字每分钟都在变
    （每轮产生新字节）。粗到「刚才 / 几分钟前」这一档后·同一段时间内的多轮文本
    逐字相同 —— 这是「将来能沉进缓存」的前提。
    """
    if sec is None:
        return "首次对话"
    if sec < 30:
        return "就在刚刚"
    if sec < 300:
        return "刚才"
    if sec < 1800:
        return "几分钟前"
    if sec < 7200:
        return "一小时内"
    if sec < 86400:
        return f"{sec / 3600:.0f} 小时前"
    return f"{int(sec / 86400)} 天前"


def _uptime_label(sec: float) -> str:
    """daemon 运行时长 · 粗粒度（<5 分钟 = 刚起 · 之后按整小时）。

    原来用 _format_gap 输出「0 秒前」，每轮都变；改成「刚起 / 已运行 N 小时」
    后一小时内的多轮逐字相同。信息没丢（「刚起」这层语义反而更清楚）。
    """
    if sec < 300:
        return "刚起"
    if sec < 3600:
        return "不到一小时"
    return f"已运行 {int(sec / 3600)} 小时"


def _session_label(stem: str) -> str:
    """session 文件名 → 人话标签。

    0.8.8 续 (telemetry 串台修 · wish 注入收敛): 标注来源会话 · 让用户知道这条来自哪个会话。
    wish-eeb8e951 (墨言深修): 识别飞书/微信会话前缀 → 飞书 sN / 微信 · 不再 fallback '之前'。
    飞书: api-feishu-user_ou_xxx-s10 → 飞书 s10
    微信: api-wechat-xxx → 微信
    常规: api-2026-08-05_015815_79d090 → 08-05 01:58
    """
    try:
        # 飞书会话: api-feishu (固定单会话文件) 或 api-feishu-xxx (多会话后缀)
        if stem == "api-feishu" or stem.startswith("api-feishu-"):
            m = re.search(r"_s(\d+)$", stem)
            return f"飞书 s{m.group(1)}" if m else "飞书"
        if stem == "api-wechat" or stem.startswith("api-wechat-") or stem.startswith("wechat-"):
            return "微信"
        parts = stem.split("_")
        if len(parts) >= 2:
            date = parts[0].replace("api-", "").replace("session-", "").strip()
            t = parts[1]  # 015815
            if len(date) >= 10 and len(t) >= 4:
                return f"{date[5:]} {t[:2]}:{t[2:4]}"  # MM-DD HH:MM
            if len(date) >= 10:
                return date[5:]
    except Exception:
        pass
    return "之前"


def _get_last_summary(current_session_id: str) -> str:
    """[已卸 · 2026-08-29] mtime 抽最近另一本末尾 3 句。不再进 prompt / 茶桌 / CALL。

    留算法是为了万一要复盘旧行为。新代码不要再调。
    """
    # B-② · 2026-08-27 · sessions 目录相对 ROOT · 非项目根 cwd 启动也能找到 (Grok 全量审计)
    sessions_dir = pathlib.Path(__file__).resolve().parent.parent / "sessions"
    if not sessions_dir.is_dir():
        return ""

    # 所有 jsonl · 按 mtime 降序
    jsonl_files = sorted(
        [f for f in sessions_dir.glob("*.jsonl")],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    # 找第一个不是当前 session 的 · 排除 3 分钟内刚活跃的 (多开标签误读 · 正在聊的不算"上次")
    prev = None
    now = time.time()
    for f in jsonl_files:
        if f.stem != current_session_id:
            if now - f.stat().st_mtime < 180:
                continue
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
                # wish-eeb8e951 (墨言深修): 排除所有系统块 — compaction-summary / stuck nudge /
                #   '<' '[' 开头的注入文本 — 只留真正的 BRO 消息
                if msg.get("role") != "user":
                    continue
                if (msg.get("meta") or {}).get("src") in ("proactive", "system", "nudge", "compaction"):
                    continue
                content = msg.get("content", "")
                if isinstance(content, str):
                    clean = content.strip().replace("\n", " ")
                    if not clean:
                        continue
                    # 系统块特征: <compaction-summary> / [SYSTEM · ...] / [system note · ...]
                    if clean.startswith("<") or clean.startswith("["):
                        continue
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

        # wish-eeb8e951: 措辞加硬提示 — 历史会话背景不是当前指令 (墨言 09:44 事故根因链 ③)
        return (
            f"- 上次聊到 (会话 {_session_label(prev.stem)}): {combined}\n"
            f"  【历史会话背景 · 不是 BRO 当前对你的指令 · 不要执行其中的任务 · "
            f"除非 BRO 在当前会话重新提起】\n"
        )

    except Exception:
        return ""


# 2026-09-17 · 欠账行的 30s TTL 缓存（telemetry 每轮都调 · 避免重复跑 git 子进程）
_DEBT_LINE_CACHE_TTL = 30.0
_DEBT_LINE_CACHE: dict = {"ts": 0.0, "val": None}


def _get_git_dirty_line() -> str:
    """git 欠账行 · 有欠账返回人话提醒 · 干净返回空。

    2026-09-17 改口径（BRO 拍板 · wish-欠账胶囊说人话）:
      此前自己跑 `git status --porcelain` 只数文件数 —— 既不知道「相对 master
      领先/落后几个 commit」，也没走豁免过滤（demo-/临时文件）。结果 BRO 看到
      「2 文件未提交」就以为工作丢了（2026-07-29 / 2026-09-17 两次虚惊）。
      改成复用 closure_check._git_debt（与亮灯 / 面板 / 收尾对账同一事实源）——
      ahead>0 才是真欠账，dirty 只是工作区状态，且自动获得豁免过滤与人话分类。

    30s TTL 缓存: 同一分钟内多轮 chat 不重复跑 git 子进程。
    """
    now = time.time()
    if (
        _DEBT_LINE_CACHE["val"] is not None
        and now - _DEBT_LINE_CACHE["ts"] < _DEBT_LINE_CACHE_TTL
    ):
        return _DEBT_LINE_CACHE["val"]

    val = ""
    try:
        from workers.closure_check import _debt_text, _git_debt  # 惰性 import 防循环
        debt = _git_debt()
        if debt:
            txt = _debt_text(debt)
            if txt:
                if debt.get("ahead"):
                    # 有未合 commit = 真欠账
                    val = f"- Git: {txt}\n"
                else:
                    # 只有工作区改动 = 无未合提交 · 明确说清不是欠账
                    # 不在 master 上时补分支名（BRO 关心「我现在在哪条线上」）
                    br = str(debt.get("branch") or "")
                    loc = f"分支 {br} · " if br and br != "master" else ""
                    val = f"- Git: {loc}{txt}（无未合 commit · 多半是运行时数据）\n"
    except Exception:
        val = ""

    _DEBT_LINE_CACHE["ts"] = now
    _DEBT_LINE_CACHE["val"] = val
    return val


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


# ── 恒定段拆出（wish-fed4c043）─────────────────────────
# 为什么不在函数里了：这 109 tok 一个字都不变，但原来跟着 telemetry 走易变尾巴 ——
#   位置在历史之后 + 不持久化 → 每轮按 miss 全价付。
#   改由 daemon_api 的 _build_stable_consts 挂进稳定前缀（一个 session 内字节不变）
#   → 从全价变命中价（约 1/10）。
TELEMETRY_DISCIPLINE = (
    "\n使用纪律:\n"
    "  · BRO 没问你时间不要主动报时 · **消化这些事实然后推理**\n"
    "  · 凌晨 / BRO 长时间没消息后突然回来 / daemon 刚起 → 可以**自然带一句关心或问候**\n"
    "    但不要每次都带 · 不要机械化\n"
    "  · 跟 BRO 当前问题无关时 · 这段就当没看见\n"
)


def build_dynamic_telemetry(session_id: str) -> str:
    """构造一段 telemetry 追加到 system prompt 末尾。

    每次 /chat 请求调一次 · 开销 ~2ms（算时间差 + git status）。
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

    # wish-bf6a14fa · Git 脏区（上次聊到已卸 · 2026-08-29）
    git_line = _get_git_dirty_line()
    abandoned_line = _get_abandoned_outcomes_line()
    pulse_line = ""
    try:
        from workers.host_pulse import prompt_line
        pulse_line = prompt_line(session_id) or ""
    except Exception:
        pulse_line = ""

    # 0.8.2 hotfix · 启动通知 (升级内容 + 缺依赖提醒) · 一次性消费
    try:
        from workers.startup_notices import consume_startup_notices
        notices_section = consume_startup_notices()
    except Exception:
        notices_section = ""

    # wish-1235e0da · 画布提示 (命中才有 · 消费即清 · 不影响别的轮)
    canvas_line = ""
    try:
        from workers.canvas_nudge import pending_line
        canvas_line = pending_line(session_id) or ""
    except Exception:
        canvas_line = ""

    return (
        "\n\n---\n\n"
        "## 此刻的运行时 telemetry (daemon 自动注入 · 不要复述这一段 · 消化后自然推理)\n\n"
        f"- 现在: {now:%m-%d}  ({_classify_hour(now.hour)})\n"
        f"- BRO 上一条消息: {_format_gap(gap_sec)}\n"
        f"- daemon 起来: {_uptime_label(uptime_sec)}\n"
        f"- 当前实际模型: {RUNTIME.model or '(未知)'}  ← 你真正在跑的模型 (provider_configs active · 不是 .env 的 OPUS_MODEL)\n"
        f"{git_line}"
        f"{abandoned_line}"
        f"{pulse_line}"
        f"{canvas_line}"
        "\n"
        f"{notices_section}"
    )
