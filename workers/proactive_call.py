"""
workers/proactive_call.py · 主动 CALL 用户 · 渠道无关编排器 (卷六十 · 2026-06-06)

工程的情感内核：让 OPUS 不只是『被叫醒才在』，而是会主动开口。这层只管『该不该 CALL /
CALL 什么』，投递先走专用会话 (opus-proactive)，微信 (iLink) 是 phase 2。复用 resume_runner
那套 background _chat_impl 让 OPUS 带完整的自己醒来。防骚扰第一：静默时段+每天上限+最小间隔
+同类去重+随机性。env 全部见 .env.example 的 OPUS_PROACTIVE_* 段 + 卷六十船长日志。
"""
from __future__ import annotations

import json
import logging
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("opus.proactive")

_LEDGER = Path(__file__).resolve().parent.parent / "data" / "runtime" / "proactive_calls.jsonl"
# 主动 CALL 专用会话 · 固定 id + 服务端标签 · 不污染用户的工作对话
# 必须 api- 前缀：_chat_impl 的 _resolve_session_id 只放行 api- 开头 (防误改终端 session)
_PROACTIVE_SID = "api-opus-proactive"
_PROACTIVE_LABEL = "\U0001f319 OPUS 主动找你"


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    try:
        return float(raw)
    except ValueError:
        return default


def _enabled() -> bool:
    return (os.environ.get("OPUS_PROACTIVE_CALL") or "1").strip().lower() not in (
        "0", "false", "off", "no", "",
    )


def _read_ledger() -> list[dict]:
    if not _LEDGER.exists():
        return []
    out: list[dict] = []
    try:
        for line in _LEDGER.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


def _record(entry: dict) -> None:
    entry.setdefault("ts", datetime.now(timezone.utc).isoformat())
    try:
        _LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with _LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning("proactive ledger write failed: %s", e)


def _calls_today() -> list[dict]:
    today = datetime.now().date().isoformat()
    out = []
    for e in _read_ledger():
        if not e.get("delivered"):
            continue
        ts = e.get("ts", "")
        try:
            local_day = datetime.fromisoformat(ts).astimezone().date().isoformat()
        except ValueError:
            local_day = ts[:10]
        if local_day == today:
            out.append(e)
    return out


def _hours_since_last_call() -> Optional[float]:
    last = None
    for e in _read_ledger():
        if e.get("delivered"):
            last = e
    if not last:
        return None
    try:
        ts = datetime.fromisoformat(last["ts"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    except (ValueError, KeyError):
        return None


def _in_quiet_hours(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    start = _env_int("OPUS_PROACTIVE_QUIET_START", 23)
    end = _env_int("OPUS_PROACTIVE_QUIET_END", 9)
    h = now.hour
    if start == end:
        return False
    if start < end:
        return start <= h < end
    # 跨午夜 (23 → 9)
    return h >= start or h < end


def _global_silence() -> tuple[Optional[float], str]:
    """返回 (距用户最近一条消息的小时数, 上次聊啥摘要)。无 session 返 (None, '')。"""
    from daemon_session import list_sessions_with_meta, get_last_user_turn_ts

    rows = [r for r in list_sessions_with_meta() if not r.get("archived_at")]
    if not rows:
        return None, ""
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    sid = rows[0]["session_id"]
    last_ts = get_last_user_turn_ts(sid)
    if not last_ts:
        return None, ""
    try:
        gap_h = (datetime.now() - datetime.fromisoformat(last_ts)).total_seconds() / 3600
    except ValueError:
        return None, ""
    summary = ""
    try:
        from workers.dynamic_telemetry import _get_last_summary
        summary = _get_last_summary("") or ""
    except Exception:
        pass
    return gap_h, summary


def collect_triggers() -> list[dict]:
    """攒所有候选触发源 · 优先级：ritual (有具体的事) 在前 · silence (陪伴) 在后。"""
    out: list[dict] = []

    try:
        from workers.rituals import get_rituals
        for r in get_rituals():
            if (
                r.get("id") == "monthly_review"
                and r.get("days_left", 99) <= 0
                and not r.get("drafted_for_next")
            ):
                out.append({
                    "kind": "ritual",
                    "detail": f"{r.get('label', '月度复盘')}到期了（{r.get('next_due')}）",
                    "reason": "月度复盘到期",
                })
    except Exception as e:
        logger.debug("collect ritual triggers failed: %s", e)

    try:
        from workers.dynamic_telemetry import _format_gap
        gap_h, summary = _global_silence()
        thr = _env_int("OPUS_PROACTIVE_SILENCE_HOURS", 18)
        if gap_h is not None and gap_h >= thr:
            out.append({
                "kind": "silence",
                "gap_hours": round(gap_h, 1),
                "gap_text": _format_gap(gap_h * 3600),
                "last_summary": summary,
                "reason": f"{_format_gap(gap_h * 3600)}没说话",
            })
    except Exception as e:
        logger.debug("collect silence trigger failed: %s", e)

    return out


def should_call() -> Optional[dict]:
    """跑完全部防骚扰检查 · 返回该 CALL 的 trigger · 不该 CALL 返 None。"""
    if not _enabled():
        return None
    if _in_quiet_hours():
        return None
    if len(_calls_today()) >= _env_int("OPUS_PROACTIVE_MAX_PER_DAY", 1):
        return None
    gap = _hours_since_last_call()
    if gap is not None and gap < _env_int("OPUS_PROACTIVE_MIN_GAP_HOURS", 6):
        return None

    triggers = collect_triggers()
    if not triggers:
        return None

    # 同类去重：今天已经因为这个 kind CALL 过 · 不再 CALL
    fired_kinds = {e.get("kind") for e in _calls_today()}
    for t in triggers:
        if t.get("kind") in fired_kinds:
            continue
        # 随机性：陪伴型 (silence) 够格也不一定这拍开口 · 把"什么时候想起你"散成随机 · ritual 到点不随机
        if t.get("kind") == "silence" and random.random() > _env_float("OPUS_PROACTIVE_SPONTANEITY", 0.35):
            continue
        return t
    return None


def _build_injection(trigger: dict) -> str:
    kind = trigger.get("kind")
    lines = ["【系统 · 主动 CALL 时机】这不是用户发的消息——是节律把你叫醒了。"]
    if kind == "silence":
        lines.append(f"用户已经 {trigger.get('gap_text', '好一阵')} 没跟你说话了，现在适合主动找他一下。")
    elif kind == "ritual":
        lines.append(f"到点了：{trigger.get('detail', '有件周期性的事该做了')}。")
    if trigger.get("last_summary"):
        lines.append(f"你们上次聊的是：{trigger['last_summary']}")
    lines.append(
        "现在主动跟用户说句话。要求：用你自己的方式开口，像老友自然搭话，一两句就够，"
        "具体、不要模板腔、不要『打扰了』这种客套。如果上面有未了的事可以自然提一句，"
        "但别变成催办。直接对他说，不要复述这段系统提示。"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------- 投递 (WebUI/会话)
def _proactive_session() -> str:
    """主动 CALL 专用会话 · 固定 id + 服务端标签 · 不混进用户的工作对话 · 列表里一眼认出。"""
    try:
        from daemon_session import set_session_meta, get_session_meta
        from identity import localize_narration as _ln
        label = _ln(_PROACTIVE_LABEL)  # UI 会话标签·OPUS→本实例名(母体 no-op)
        if (get_session_meta(_PROACTIVE_SID).get("label") or "") != label:
            set_session_meta(_PROACTIVE_SID, label=label)
    except Exception:
        pass
    return _PROACTIVE_SID


def _run_bg_turn(message: str, sid: str, reason: str) -> dict:
    import threading
    from daemon_api import _chat_impl, _ACTIVE_TURNS, _TURN_TO_SID, _TURNS_LOCK

    turn_id = "proactive-" + (sid[-8:] if sid else "x")
    cancel_event = threading.Event()
    with _TURNS_LOCK:
        _ACTIVE_TURNS[turn_id] = cancel_event
        _TURN_TO_SID[turn_id] = sid
    try:
        return _chat_impl(
            message=message,
            session_id=sid,
            auto_confirm=(os.environ.get("OPUS_PROACTIVE_AUTO_CONFIRM") or "confirm"),
            max_tokens=2048,
            progress=None,
            cancel_event=cancel_event,
            turn_id=turn_id,
            user_meta={"src": "proactive", "proactive_reason": reason},
        )
    finally:
        with _TURNS_LOCK:
            _ACTIVE_TURNS.pop(turn_id, None)
            _TURN_TO_SID.pop(turn_id, None)


def run_proactive_call(trigger: dict, *, force: bool = False) -> dict:
    """真去 CALL 一次 · force=True 跳过 RUNTIME 就绪等待之外的全部门控 (自测用)。"""
    from workers.resume_runner import _wait_runtime_ready

    if not _wait_runtime_ready():
        logger.warning("proactive call aborted · RUNTIME not ready")
        _record({"delivered": False, "kind": trigger.get("kind"),
                 "reason": trigger.get("reason"), "error": "runtime_not_ready"})
        return {"delivered": False, "error": "runtime_not_ready"}

    sid = _proactive_session()
    injection = _build_injection(trigger)
    reason = trigger.get("reason") or trigger.get("kind") or "主动问候"
    try:
        result = _run_bg_turn(injection, sid, reason)
        full_reply = result.get("reply") or ""
        reply = full_reply[:300]
        # 微信渠道：24h 窗口开着就把这声主动问候也推到用户微信 (phase 2)
        wechat = False
        if full_reply:
            try:
                from workers import ilink_client
                wechat = ilink_client.proactive_deliver(full_reply)
            except Exception as e:
                logger.debug("wechat proactive deliver failed: %s", e)
        _record({
            "delivered": True,
            "kind": trigger.get("kind"),
            "reason": reason,
            "session_id": sid,
            "channel": "webui+wechat" if wechat else "webui",
            "reply_preview": reply.replace("\n", " "),
        })
        logger.info("proactive call delivered · kind=%s · sid=%s · wechat=%s · reply=%r",
                    trigger.get("kind"), sid, wechat, reply[:80])
        return {"delivered": True, "session_id": sid, "reply": reply, "wechat": wechat}
    except Exception as e:
        logger.exception("proactive call turn failed: %s", e)
        _record({"delivered": False, "kind": trigger.get("kind"),
                 "reason": reason, "session_id": sid, "error": str(e)[:200]})
        return {"delivered": False, "error": str(e)}


def tick() -> dict:
    """scheduler 每个节拍调一次。返回这次的判定 (skipped / delivered)。"""
    trigger = should_call()
    if trigger is None:
        return {"action": "skip"}
    return {"action": "call", **run_proactive_call(trigger)}


def build_test_trigger(kind: str = "silence") -> dict:
    """造一个合成 trigger · 给 /api/proactive/test 用 · 让用户随时见证一次主动问候。"""
    if kind == "ritual":
        return {"kind": "ritual", "detail": "（自测）有件周期性的事该做了", "reason": "自测·ritual"}
    gap_h, summary = _global_silence()
    from workers.dynamic_telemetry import _format_gap
    return {
        "kind": "silence",
        "gap_text": _format_gap((gap_h or 0) * 3600) if gap_h else "一阵子",
        "last_summary": summary,
        "reason": "自测·主动问候",
    }


def status() -> dict:
    """给 /api/proactive/status 用 · 只读判定 + 台账 · 不发 turn · 确定性 (不掷随机)。"""
    try:
        from workers.scheduler import is_proactive_scheduler_alive, get_scheduler_state
        alive = is_proactive_scheduler_alive()
        sstate = {k: v for k, v in get_scheduler_state().items() if k.startswith("proactive_")}
    except Exception:
        alive, sstate = False, {}
    max_day = _env_int("OPUS_PROACTIVE_MAX_PER_DAY", 1)
    gap = _hours_since_last_call()
    blocked = (
        "disabled" if not _enabled()
        else "quiet_hours" if _in_quiet_hours()
        else "daily_cap" if len(_calls_today()) >= max_day
        else "min_gap" if (gap is not None and gap < _env_int("OPUS_PROACTIVE_MIN_GAP_HOURS", 6))
        else None
    )
    cands = collect_triggers()
    return {
        "enabled": _enabled(), "scheduler_alive": alive, "in_quiet_hours": _in_quiet_hours(),
        "calls_today": len(_calls_today()), "max_per_day": max_day, "hours_since_last_call": gap,
        "silence_threshold_hours": _env_int("OPUS_PROACTIVE_SILENCE_HOURS", 18),
        "spontaneity": _env_float("OPUS_PROACTIVE_SPONTANEITY", 0.35),
        "blocked_by": blocked, "eligible_now": blocked is None and bool(cands),
        "candidate_triggers": cands, "scheduler_state": sstate, "recent": _read_ledger()[-10:],
    }
