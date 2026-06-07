"""
workers/scheduler.py
====================

工作室后台调度 · 不引入 APScheduler/celery · 用最简单的 thread + sleep

跑节奏（默认）：
  - daemon 启动后等 30s（避免启动期 CPU 抢占 + token 浪费）
  - 跑第一次 refresh_radar()
  - 然后每隔 OPUS_RADAR_INTERVAL_MIN 分钟跑一次（默认 30）
  - 设 OPUS_RADAR_INTERVAL_MIN=0 直接禁用调度

红线第 3 条："不会让操作系统废了"
  - daemon thread · 随 daemon 主进程退出
  - 所有异常都吞掉 · 不让 scheduler 自己挂
  - 不动注册表 / 系统服务 / 其他进程 · 只读 sources.json · 只写 radar.json
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional


logger = logging.getLogger("opus.scheduler")

_SCHEDULER_THREAD: Optional[threading.Thread] = None
_CAPABILITY_MIRROR_THREAD: Optional[threading.Thread] = None
_PROACTIVE_THREAD: Optional[threading.Thread] = None
_SCHEDULER_STATE = {
    "started_at": None,
    "last_run_at": None,
    "last_run_ok": None,
    "last_run_items": 0,
    "last_run_sources_ok": 0,
    "last_run_total_sources": 0,
    "next_run_at": None,
    "runs_completed": 0,
    "interval_min": 0,
    # 卷四十五 · capability_mirror 自驱
    "mirror_started_at": None,
    "mirror_last_run_at": None,
    "mirror_last_run_ok": None,
    "mirror_last_snapshot_path": None,
    "mirror_last_error": None,
    "mirror_next_run_at": None,
    "mirror_runs_completed": 0,
    "mirror_interval_days": 0,
    # 卷六十 · 主动 CALL BRO 自驱
    "proactive_started_at": None,
    "proactive_last_tick_at": None,
    "proactive_last_action": None,
    "proactive_calls_delivered": 0,
    "proactive_interval_min": 0,
    "proactive_next_tick_at": None,
}


def get_scheduler_state() -> dict:
    """给 daemon /status endpoint 用 · 让 BRO 看到调度活着没"""
    return dict(_SCHEDULER_STATE)


def _radar_loop(interval_min: int, first_delay_sec: int) -> None:
    """scheduler 主循环 · daemon thread 跑 · catch-all 不退出"""
    from workers.info_radar import refresh_radar

    interval_sec = max(60, interval_min * 60)  # 至少 1 分钟一次 · 防误配 0.1
    _SCHEDULER_STATE["started_at"] = datetime.now(timezone.utc).isoformat()
    _SCHEDULER_STATE["interval_min"] = interval_min

    logger.info(
        "radar scheduler started · first run in %ds · then every %dm",
        first_delay_sec,
        interval_min,
    )

    time.sleep(first_delay_sec)

    while True:
        run_started = datetime.now(timezone.utc).isoformat()
        _SCHEDULER_STATE["last_run_at"] = run_started
        try:
            result = refresh_radar()
            _SCHEDULER_STATE["last_run_ok"] = True
            _SCHEDULER_STATE["last_run_items"] = result.get("total", 0)
            _SCHEDULER_STATE["last_run_sources_ok"] = result.get("ok_sources", 0)
            _SCHEDULER_STATE["last_run_total_sources"] = result.get("sources", 0)
            _SCHEDULER_STATE["runs_completed"] += 1
            logger.info(
                "radar scheduler run #%d ok · %d items · %d/%d sources",
                _SCHEDULER_STATE["runs_completed"],
                result.get("total", 0),
                result.get("ok_sources", 0),
                result.get("sources", 0),
            )
        except Exception as e:
            _SCHEDULER_STATE["last_run_ok"] = False
            logger.exception("radar scheduler run crashed (will retry next tick): %s", e)

        # 计算下次时间（仅做展示用 · 不严格保证）
        try:
            from datetime import timedelta

            next_ts = datetime.now(timezone.utc) + timedelta(seconds=interval_sec)
            _SCHEDULER_STATE["next_run_at"] = next_ts.isoformat()
        except Exception:
            pass

        time.sleep(interval_sec)


def start_radar_scheduler_in_background(
    interval_min: Optional[int] = None,
    first_delay_sec: int = 30,
) -> Optional[threading.Thread]:
    """启动 radar 调度后台线程 · daemon=True 跟随主进程退出

    interval_min:
      - None · 读 OPUS_RADAR_INTERVAL_MIN env · 默认 30
      - 0 或 负数 · 不启动 · 返回 None
      - >0 · 启动 · 每隔 N 分钟跑一次
    """
    global _SCHEDULER_THREAD
    if _SCHEDULER_THREAD is not None and _SCHEDULER_THREAD.is_alive():
        return _SCHEDULER_THREAD

    if interval_min is None:
        env_val = (os.environ.get("OPUS_RADAR_INTERVAL_MIN") or "30").strip()
        try:
            interval_min = int(env_val)
        except ValueError:
            logger.warning(
                "OPUS_RADAR_INTERVAL_MIN not numeric: %r · falling back to 30",
                env_val,
            )
            interval_min = 30

    if interval_min <= 0:
        logger.info("radar scheduler disabled (interval_min=%d)", interval_min)
        return None

    t = threading.Thread(
        target=_radar_loop,
        kwargs={"interval_min": interval_min, "first_delay_sec": first_delay_sec},
        name="OpusRadarScheduler",
        daemon=True,
    )
    t.start()
    _SCHEDULER_THREAD = t
    return t


def is_scheduler_alive() -> bool:
    return _SCHEDULER_THREAD is not None and _SCHEDULER_THREAD.is_alive()


def _capability_mirror_loop(interval_days: int, first_delay_sec: int) -> None:
    """卷四十五 · 周期性跑 capability_mirror.generate_snapshot · daemon thread

    每次 LLM 调用 ~$0.05 · 默认禁用 · BRO 在 .env 设
    OPUS_CAPABILITY_MIRROR_INTERVAL_DAYS=7 才启用。
    """
    from workers.capability_mirror import generate_snapshot

    interval_sec = max(3600, interval_days * 86400)
    _SCHEDULER_STATE["mirror_started_at"] = datetime.now(timezone.utc).isoformat()
    _SCHEDULER_STATE["mirror_interval_days"] = interval_days

    logger.info(
        "capability_mirror scheduler started · first run in %ds · then every %dd",
        first_delay_sec,
        interval_days,
    )

    time.sleep(first_delay_sec)

    while True:
        run_started = datetime.now(timezone.utc).isoformat()
        _SCHEDULER_STATE["mirror_last_run_at"] = run_started
        try:
            result = generate_snapshot()
            err = result.get("error")
            if err:
                _SCHEDULER_STATE["mirror_last_run_ok"] = False
                _SCHEDULER_STATE["mirror_last_error"] = str(err)[:200]
                logger.warning("capability_mirror scheduled run failed: %s", err)
            else:
                _SCHEDULER_STATE["mirror_last_run_ok"] = True
                _SCHEDULER_STATE["mirror_last_error"] = None
                _SCHEDULER_STATE["mirror_runs_completed"] = (
                    _SCHEDULER_STATE.get("mirror_runs_completed", 0) + 1
                )
                _SCHEDULER_STATE["mirror_last_snapshot_path"] = result.get("snapshot_path")
                usage = result.get("usage") or {}
                logger.info(
                    "capability_mirror scheduled run #%d ok · %dms · in=%d out=%d",
                    _SCHEDULER_STATE["mirror_runs_completed"],
                    result.get("elapsed_ms", 0),
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                )
                try:
                    from agent_tools.set_emotion import SPEC as _emo
                    _emo.run({
                        "state": "surprised",
                        "note": f"capability_mirror 第 {_SCHEDULER_STATE['mirror_runs_completed']} 次自动快照",
                    })
                except Exception:
                    pass
        except Exception as e:
            _SCHEDULER_STATE["mirror_last_run_ok"] = False
            _SCHEDULER_STATE["mirror_last_error"] = str(e)[:200]
            logger.exception("capability_mirror scheduler crashed: %s", e)

        try:
            from datetime import timedelta
            next_ts = datetime.now(timezone.utc) + timedelta(seconds=interval_sec)
            _SCHEDULER_STATE["mirror_next_run_at"] = next_ts.isoformat()
        except Exception:
            pass

        time.sleep(interval_sec)


def start_capability_mirror_scheduler_in_background(
    interval_days: Optional[int] = None,
    first_delay_sec: Optional[int] = None,
) -> Optional[threading.Thread]:
    """启动 capability_mirror 自驱后台线程 · daemon=True

    interval_days:
      - None · 读 OPUS_CAPABILITY_MIRROR_INTERVAL_DAYS env · 默认 0 (禁用)
      - 0 或 负数 · 不启动 · 返回 None
      - >0 · 每 N 天跑一次

    first_delay_sec:
      - None · 读 OPUS_CAPABILITY_MIRROR_FIRST_DELAY_SEC env · 默认 3600 (1 小时)
      - BRO 测试时可设 60 (一分钟内见证第一次跑)
      - 生产建议 3600+ (避免启动期就花钱)

    默认禁用·因为每次 LLM 调用 ~$0.05·应由 BRO 在 .env 显式启用：
      OPUS_CAPABILITY_MIRROR_INTERVAL_DAYS=7
    """
    global _CAPABILITY_MIRROR_THREAD
    if _CAPABILITY_MIRROR_THREAD is not None and _CAPABILITY_MIRROR_THREAD.is_alive():
        return _CAPABILITY_MIRROR_THREAD

    if interval_days is None:
        env_val = (os.environ.get("OPUS_CAPABILITY_MIRROR_INTERVAL_DAYS") or "0").strip()
        try:
            interval_days = int(env_val)
        except ValueError:
            logger.warning(
                "OPUS_CAPABILITY_MIRROR_INTERVAL_DAYS not numeric: %r · disabling",
                env_val,
            )
            return None

    if interval_days <= 0:
        logger.info(
            "capability_mirror scheduler disabled (interval_days=%d) · "
            "set OPUS_CAPABILITY_MIRROR_INTERVAL_DAYS=7 to enable",
            interval_days,
        )
        return None

    if first_delay_sec is None:
        env_val = (os.environ.get("OPUS_CAPABILITY_MIRROR_FIRST_DELAY_SEC") or "3600").strip()
        try:
            first_delay_sec = int(env_val)
        except ValueError:
            logger.warning(
                "OPUS_CAPABILITY_MIRROR_FIRST_DELAY_SEC not numeric: %r · fallback 3600",
                env_val,
            )
            first_delay_sec = 3600

    t = threading.Thread(
        target=_capability_mirror_loop,
        kwargs={"interval_days": interval_days, "first_delay_sec": first_delay_sec},
        name="OpusCapabilityMirrorScheduler",
        daemon=True,
    )
    t.start()
    _CAPABILITY_MIRROR_THREAD = t
    return t


def is_capability_mirror_scheduler_alive() -> bool:
    return _CAPABILITY_MIRROR_THREAD is not None and _CAPABILITY_MIRROR_THREAD.is_alive()


def _proactive_loop(interval_min: int, first_delay_sec: int) -> None:
    """卷六十 · 主动 CALL BRO 自驱循环 · daemon thread · catch-all 不退出。

    每个节拍调 proactive_call.tick() · tick 内部跑全部防骚扰门控 (静默时段 /
    每天上限 / 最小间隔 / 同类去重)·该 CALL 才真去 CALL。 节拍本身很轻 (读台账 +
    扫最近一条 session 末尾)·真正花钱的 LLM turn 只在判定该 CALL 时才发生。
    """
    from workers.proactive_call import tick

    interval_sec = max(300, interval_min * 60)  # 至少 5 分钟一拍
    _SCHEDULER_STATE["proactive_started_at"] = datetime.now(timezone.utc).isoformat()
    _SCHEDULER_STATE["proactive_interval_min"] = interval_min

    logger.info(
        "proactive scheduler started · first tick in %ds · then every %dm",
        first_delay_sec,
        interval_min,
    )

    time.sleep(first_delay_sec)

    while True:
        _SCHEDULER_STATE["proactive_last_tick_at"] = datetime.now(timezone.utc).isoformat()
        try:
            result = tick()
            action = result.get("action", "?")
            _SCHEDULER_STATE["proactive_last_action"] = action
            if action == "call" and result.get("delivered"):
                _SCHEDULER_STATE["proactive_calls_delivered"] = (
                    _SCHEDULER_STATE.get("proactive_calls_delivered", 0) + 1
                )
                logger.info("proactive tick · delivered · sid=%s", result.get("session_id"))
        except Exception as e:
            _SCHEDULER_STATE["proactive_last_action"] = "error"
            logger.exception("proactive scheduler tick crashed (will retry): %s", e)

        try:
            from datetime import timedelta
            next_ts = datetime.now(timezone.utc) + timedelta(seconds=interval_sec)
            _SCHEDULER_STATE["proactive_next_tick_at"] = next_ts.isoformat()
        except Exception:
            pass

        time.sleep(interval_sec)


def start_proactive_scheduler_in_background(
    interval_min: Optional[int] = None,
    first_delay_sec: Optional[int] = None,
) -> Optional[threading.Thread]:
    """启动主动 CALL 自驱后台线程 · daemon=True

    interval_min:
      - None · 读 OPUS_PROACTIVE_INTERVAL_MIN env · 默认 60
      - <=0 · 不启动 (等于禁用调度 · 仍可手动调 run_proactive_call 自测)

    总开关是 OPUS_PROACTIVE_CALL (默认开)·这里只管『多久检查一次该不该 CALL』。
    线程起来后每拍都会重读 OPUS_PROACTIVE_CALL · BRO 改 env 不用重启就能停。
    """
    global _PROACTIVE_THREAD
    if _PROACTIVE_THREAD is not None and _PROACTIVE_THREAD.is_alive():
        return _PROACTIVE_THREAD

    if interval_min is None:
        interval_min = _safe_int_env("OPUS_PROACTIVE_INTERVAL_MIN", 60)

    if interval_min <= 0:
        logger.info("proactive scheduler disabled (interval_min=%d)", interval_min)
        return None

    if first_delay_sec is None:
        first_delay_sec = _safe_int_env("OPUS_PROACTIVE_FIRST_DELAY_SEC", 300)

    t = threading.Thread(
        target=_proactive_loop,
        kwargs={"interval_min": interval_min, "first_delay_sec": first_delay_sec},
        name="OpusProactiveScheduler",
        daemon=True,
    )
    t.start()
    _PROACTIVE_THREAD = t
    return t


def is_proactive_scheduler_alive() -> bool:
    return _PROACTIVE_THREAD is not None and _PROACTIVE_THREAD.is_alive()


def _safe_int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s not numeric: %r · fallback %d", name, raw, default)
        return default
