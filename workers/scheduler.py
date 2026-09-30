"""
workers/scheduler.py
====================

工作室后台调度 · 不引入 APScheduler/celery · 用最简单的 thread + sleep

跑节奏（默认）：
  - daemon 启动后等 30s（避免启动期 CPU 抢占 + token 浪费）
  - **距上次刷新不足一个间隔就跳过**（2026-09-28 · 重启不该重刷一遍）
  - 到点了才跑 refresh_radar()
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
_STATE_CONDENSER_THREAD: Optional[threading.Thread] = None
_SHE_GALLERY_THREAD: Optional[threading.Thread] = None
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
    "enabled": True,  # 设置页「掘金雷达」开关的实时镜像（暂停时 False）
    # 卷四十五 · capability_mirror 自驱
    "mirror_started_at": None,
    "mirror_last_run_at": None,
    "mirror_last_run_ok": None,
    "mirror_last_snapshot_path": None,
    "mirror_last_error": None,
    "mirror_next_run_at": None,
    "mirror_runs_completed": 0,
    "mirror_interval_days": 0,
    # H4 · state_condenser 周度凝练
    "condenser_started_at": None,
    "condenser_last_run_at": None,
    "condenser_last_run_ok": None,
    "condenser_last_error": None,
    "condenser_last_skipped_reason": None,
    "condenser_last_condensed": None,
    "condenser_next_run_at": None,
    "condenser_runs_completed": 0,
    # 她·画廊 · 羁绊式朋友圈
    "gallery_started_at": None,
    "gallery_last_run_at": None,
    "gallery_last_result": None,
    "gallery_next_run_at": None,
    "gallery_runs_completed": 0,
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


_RADAR_CONFIG_TICK_SEC = 10  # 配置热读节拍 · 设置页改完最多 10 秒生效


def _radar_sleep(seconds: int, snapshot: dict) -> dict:
    """切片 sleep：每 _RADAR_CONFIG_TICK_SEC 对一次配置快照。

    配置被设置页改了就提前醒（返回新配置）· 没改就睡满。返回给下一轮用的配置。
    """
    from workers.radar_config import load_radar_config

    waited = 0.0
    while waited < seconds:
        step = min(_RADAR_CONFIG_TICK_SEC, seconds - waited)
        time.sleep(step)
        waited += step
        try:
            cur = load_radar_config()
        except Exception:
            continue
        if cur != snapshot:
            logger.info("radar config changed (设置页) · %s → %s", snapshot, cur)
            return cur
    return snapshot


def _radar_last_generated_ts() -> Optional[float]:
    """上一次雷达真正抓到数据的时间（data/radar.json 的 generated_at）→ epoch 秒。

    2026-09-28 · 用来判断「这轮该不该刷」。读不到（没刷过/文件坏）返回 None
    —— 那时不跳，照常刷（首刷必须成功）。
    """
    try:
        from workers.info_radar import load_radar

        g = (load_radar() or {}).get("generated_at")
        if not g:
            return None
        dt = datetime.fromisoformat(str(g).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception as e:
        logger.debug("radar last generated_at 读不到: %s", e)
        return None


def _radar_loop(first_delay_sec: int = 30) -> None:
    """scheduler 主循环 · daemon thread 跑 · catch-all 不退出

    间隔与开关都从 workers/radar_config.py 热读（设置页「掘金雷达」tab 控制）·
    改完 10 秒内生效 · 不用重启 daemon。
    """
    from workers.info_radar import refresh_radar
    from workers.radar_config import load_radar_config

    cfg = load_radar_config()
    interval_sec = max(60, int(cfg.get("interval_min") or 30) * 60)  # 至少 1 分钟一次 · 防误配 0.1
    _SCHEDULER_STATE["started_at"] = datetime.now(timezone.utc).isoformat()
    _SCHEDULER_STATE["interval_min"] = int(cfg.get("interval_min") or 30)
    _SCHEDULER_STATE["enabled"] = bool(cfg.get("enabled", True))

    logger.info(
        "radar scheduler started · first check in %ds · enabled=%s · every %s min (设置页可改)",
        first_delay_sec,
        cfg.get("enabled"),
        cfg.get("interval_min"),
    )

    cfg = _radar_sleep(first_delay_sec, cfg)

    while True:
        enabled = bool(cfg.get("enabled", True))
        interval_min = int(cfg.get("interval_min") or 30)
        interval_sec = max(60, interval_min * 60)
        _SCHEDULER_STATE["enabled"] = enabled
        _SCHEDULER_STATE["interval_min"] = interval_min

        if not enabled:
            _SCHEDULER_STATE["next_run_at"] = None
            logger.info("radar scheduler paused (设置页关了自动刷新) · 60s 后复查")
            cfg = _radar_sleep(60, cfg)
            continue

        # 2026-09-28 · 距上次刷新不足一个间隔就跳过。
        #   原来按「进程起来多久」计时 → daemon 一天重启几次就白刷几次
        #   （BRO 报「启动卡」那天：13:33 刷完 167 条，13:43 重启后又刷同样 167 条，
        #    翻译跟着烧两轮 token）。改成按 radar.json 的 generated_at 计时。
        last_ts = _radar_last_generated_ts()
        if last_ts is not None:
            age_sec = time.time() - last_ts
            due_sec = interval_sec * 0.9  # 留 10% 余量 · 免得差几秒又刷一遍
            if age_sec < due_sec:
                wait_sec = int(min(due_sec - age_sec, interval_sec))
                _SCHEDULER_STATE["last_skipped_reason"] = (
                    f"距上次刷新仅 {age_sec / 60:.0f} 分钟（间隔 {interval_min} 分钟）"
                )
                try:
                    from datetime import timedelta

                    _SCHEDULER_STATE["next_run_at"] = (
                        datetime.now(timezone.utc) + timedelta(seconds=wait_sec)
                    ).isoformat()
                except Exception:
                    pass
                logger.info(
                    "radar scheduler skip · 距上次刷新 %.0f 分钟 · 未到 %d 分钟 · %.0f 分钟后复查",
                    age_sec / 60,
                    interval_min,
                    wait_sec / 60,
                )
                cfg = _radar_sleep(wait_sec, cfg)
                continue

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

        cfg = _radar_sleep(interval_sec, cfg)


def start_radar_scheduler_in_background(
    first_delay_sec: int = 30,
) -> Optional[threading.Thread]:
    """启动 radar 调度后台线程 · daemon=True 跟随主进程退出

    间隔/开关不再由这里定死 —— 线程里每 10s 热读 data/radar_config.json
    （设置页「掘金雷达」tab 写 · 缺文件时用 .env OPUS_RADAR_INTERVAL_MIN 兜底）。
    所以总是启动：即使 .env 设 0 也只是「默认暂停」，BRO 在设置页能重新打开。
    """
    global _SCHEDULER_THREAD
    if _SCHEDULER_THREAD is not None and _SCHEDULER_THREAD.is_alive():
        return _SCHEDULER_THREAD

    t = threading.Thread(
        target=_radar_loop,
        kwargs={"first_delay_sec": first_delay_sec},
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


def _state_condenser_loop(first_delay_sec: int) -> None:
    """H4 · 周度凝练 · 每 6 小时 tick · 条件满足才跑。"""
    from workers.state_condenser import condense_state_card

    interval_sec = 6 * 3600
    _SCHEDULER_STATE["condenser_started_at"] = datetime.now(timezone.utc).isoformat()

    logger.info(
        "state_condenser scheduler started · first tick in %ds · then every 6h",
        first_delay_sec,
    )

    time.sleep(first_delay_sec)

    while True:
        run_started = datetime.now(timezone.utc).isoformat()
        _SCHEDULER_STATE["condenser_last_run_at"] = run_started
        try:
            result = condense_state_card()
            if result.get("skipped"):
                _SCHEDULER_STATE["condenser_last_run_ok"] = True
                _SCHEDULER_STATE["condenser_last_error"] = result.get("error")
                _SCHEDULER_STATE["condenser_last_skipped_reason"] = (
                    result.get("reason") or result.get("error") or "skipped"
                )
                _SCHEDULER_STATE["condenser_last_condensed"] = 0
                logger.info(
                    "state_condenser tick skipped: %s",
                    _SCHEDULER_STATE["condenser_last_skipped_reason"],
                )
            else:
                _SCHEDULER_STATE["condenser_last_run_ok"] = True
                _SCHEDULER_STATE["condenser_last_error"] = None
                _SCHEDULER_STATE["condenser_last_skipped_reason"] = None
                _SCHEDULER_STATE["condenser_runs_completed"] = (
                    _SCHEDULER_STATE.get("condenser_runs_completed", 0) + 1
                )
                n = int(result.get("condensed") or 0)
                _SCHEDULER_STATE["condenser_last_condensed"] = n
                logger.info(
                    "state_condenser run #%d ok · condensed=%d total=%d",
                    _SCHEDULER_STATE["condenser_runs_completed"],
                    n,
                    result.get("total_entries", 0),
                )
        except Exception as e:
            _SCHEDULER_STATE["condenser_last_run_ok"] = False
            _SCHEDULER_STATE["condenser_last_error"] = str(e)[:200]
            logger.exception("state_condenser scheduler crashed: %s", e)

        # ── 升格 (wish-fa1699c1 后续 · 第 2 步) ────────────────────────────
        # 与凝练独立: 凝练会被节流跳过 (>= CONDENSE_DAYS 或 history delta 不够)，
        # 升格每次 tick 都跑。判据是 memory_index.hit_count —— 「已下沉」段里被真
        # 召回够多的条目捞回了解层。只沉不捞 = 单向下沉 = 慢性失忆，这句是那半边的补丁。
        try:
            from pathlib import Path as _P

            from workers import memory_reaper as _mr
            from workers.state_condenser import DEFAULT_NOTEBOOK

            _nb = _P(DEFAULT_NOTEBOOK)
            if _nb.exists():
                _raw = _nb.read_text(encoding="utf-8")
                _new, _got = _mr.promote_by_hits(_raw)
                if _got:
                    _nb.write_text(_new, encoding="utf-8")
                    _SCHEDULER_STATE["promoted_last_n"] = len(_got)
                    _SCHEDULER_STATE["promoted_last_at"] = datetime.now(timezone.utc).isoformat()
                    logger.info("memory promote · 升格 %d 条进了解层", len(_got))
        except Exception as e:
            logger.warning("memory promote 失败: %s", e)

        try:
            from datetime import timedelta
            next_ts = datetime.now(timezone.utc) + timedelta(seconds=interval_sec)
            _SCHEDULER_STATE["condenser_next_run_at"] = next_ts.isoformat()
        except Exception:
            pass

        time.sleep(interval_sec)


_PLAYBOOK_CURATOR_THREAD: Optional[threading.Thread] = None


def _playbook_curator_loop(first_delay_sec: int) -> None:
    """操作手册自动整理 · 每周一次 tick · 每次上限 1 簇。

    wish-fa1699c1 后续 · 第 3 步: audit_playbooks 早就能查出重复簇，但「合不合」
    要人拍板 —— 而人不会来。这一层把最后一脚接上 (先备份 + 状态机退休 · 可回滚)。
    """
    from workers.playbook_curator import curate

    interval_sec = 7 * 24 * 3600
    _SCHEDULER_STATE["curator_started_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(
        "playbook_curator scheduler started · first tick in %ds · then weekly",
        first_delay_sec,
    )

    time.sleep(first_delay_sec)

    while True:
        try:
            rep = curate()
            _SCHEDULER_STATE["curator_last_at"] = datetime.now(timezone.utc).isoformat()
            _SCHEDULER_STATE["curator_clusters_found"] = rep.get("clusters_found", 0)
            _SCHEDULER_STATE["curator_merged"] = rep.get("merged", [])
            _SCHEDULER_STATE["curator_skipped"] = rep.get("skipped", [])
            _SCHEDULER_STATE["curator_last_error"] = None
            logger.info(
                "playbook_curator tick · 发现 %d 簇 · 合并 %d · 跳过 %d",
                rep.get("clusters_found", 0),
                len(rep.get("merged", [])), len(rep.get("skipped", [])),
            )
        except Exception as e:
            _SCHEDULER_STATE["curator_last_error"] = str(e)[:200]
            logger.exception("playbook_curator crashed: %s", e)
        time.sleep(interval_sec)


def start_playbook_curator_scheduler_in_background(
    first_delay_sec: int = 600,
) -> Optional[threading.Thread]:
    """操作手册自动整理 · 开机 10 分钟后第一次 · 之后每周一次。"""
    global _PLAYBOOK_CURATOR_THREAD
    if os.environ.get("OPUS_DISABLE_PLAYBOOK_CURATOR") == "1":
        logger.info("OPUS_DISABLE_PLAYBOOK_CURATOR=1 · 跳过手册整理")
        return None
    if _PLAYBOOK_CURATOR_THREAD is not None and _PLAYBOOK_CURATOR_THREAD.is_alive():
        return _PLAYBOOK_CURATOR_THREAD

    t = threading.Thread(
        target=_playbook_curator_loop,
        kwargs={"first_delay_sec": first_delay_sec},
        name="OpusPlaybookCurator",
        daemon=True,
    )
    t.start()
    _PLAYBOOK_CURATOR_THREAD = t
    return t


_MONTHLY_REVIEW_THREAD: Optional[threading.Thread] = None


def _monthly_review_loop(first_delay_sec: int) -> None:
    """月度复盘 · 每天检查一次「到期了没」· 到期且还没起草 → 自动起草。

    wish-fa1699c1 后续 · 第 4 步: 复盘的价值在「读」，不在「记得去点那个按钮」。
    起草是全自动的 (产物落 data/reviews/ · 铺中栏) · 读不读是 BRO 的情分。

    幂等靠 drafted_for_next: 起草成功后它变 True，不会重复起草。
    """
    from workers.rituals import get_rituals

    interval_sec = 24 * 3600
    _SCHEDULER_STATE["monthly_auto_started_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(
        "monthly_review auto-draft scheduler started · first tick in %ds · then daily",
        first_delay_sec,
    )

    time.sleep(first_delay_sec)

    while True:
        try:
            mr = next((r for r in get_rituals() if r["id"] == "monthly_review"), None)
            if mr is None:
                _SCHEDULER_STATE["monthly_auto_last_action"] = "节律表读不到 · 跳过"
                logger.info("月度复盘自动检查 · 节律表读不到 · 跳过")
            elif mr.get("drafted_for_next"):
                _SCHEDULER_STATE["monthly_auto_last_action"] = "本期已起草过 · 跳过"
                logger.info(
                    "月度复盘自动检查 · 本期已起草过 · 跳过 (next_due=%s)",
                    mr.get("next_due"),
                )
            elif int(mr.get("days_left", 99)) <= 0:
                from agent_tools.monthly_review import _run as _mr_run

                res = _mr_run({"action": "draft", "period_end": mr["next_due"]})
                _SCHEDULER_STATE["monthly_auto_last_action"] = (
                    f"起草 {mr['next_due']} · ok={getattr(res, 'ok', '?')}"
                )
                _SCHEDULER_STATE["monthly_auto_last_at"] = datetime.now(timezone.utc).isoformat()
                logger.info(
                    "月度复盘自动起草 · period_end=%s · ok=%s",
                    mr["next_due"], getattr(res, "ok", "?"),
                )
            else:
                _SCHEDULER_STATE["monthly_auto_last_action"] = f"未到期 (还有 {mr.get('days_left')} 天)"
                # 2026-09-29 · 跳过也必须留一行 —— 否则 BRO 问「这个自动任务在跑吗」
                # 时日志里一片空白，只能靠反推。自动任务「撞得见」比省一行日志重要。
                logger.info(
                    "月度复盘自动检查 · 未到期 (还有 %s 天 · next_due=%s) · 跳过",
                    mr.get("days_left"),
                    mr.get("next_due"),
                )
            _SCHEDULER_STATE["monthly_auto_last_error"] = None
        except Exception as e:
            _SCHEDULER_STATE["monthly_auto_last_error"] = str(e)[:200]
            logger.exception("monthly_review auto-draft crashed: %s", e)
        time.sleep(interval_sec)


def start_monthly_review_scheduler_in_background(
    first_delay_sec: int = 1800,
) -> Optional[threading.Thread]:
    """月度复盘自动起草 · 每天检查一次 · 到期自动起草。"""
    global _MONTHLY_REVIEW_THREAD
    if os.environ.get("OPUS_DISABLE_MONTHLY_AUTO") == "1":
        logger.info("OPUS_DISABLE_MONTHLY_AUTO=1 · 跳过月度复盘自动起草")
        return None
    if _MONTHLY_REVIEW_THREAD is not None and _MONTHLY_REVIEW_THREAD.is_alive():
        return _MONTHLY_REVIEW_THREAD

    t = threading.Thread(
        target=_monthly_review_loop,
        kwargs={"first_delay_sec": first_delay_sec},
        name="OpusMonthlyReviewAuto",
        daemon=True,
    )
    t.start()
    _MONTHLY_REVIEW_THREAD = t
    return t


def start_state_condenser_scheduler_in_background(
    first_delay_sec: int = 120,
) -> Optional[threading.Thread]:
    """周度凝练 · 每 6 小时 tick 一次 · 条件满足才跑（≥7天 或 ≥30条）。

    开机补偿天然成立：daemon 没开机就不跑，开机后第一个 tick 检测到 overdue 自动补。
    """
    global _STATE_CONDENSER_THREAD
    if _STATE_CONDENSER_THREAD is not None and _STATE_CONDENSER_THREAD.is_alive():
        return _STATE_CONDENSER_THREAD

    t = threading.Thread(
        target=_state_condenser_loop,
        kwargs={"first_delay_sec": first_delay_sec},
        name="OpusStateCondenserScheduler",
        daemon=True,
    )
    t.start()
    _STATE_CONDENSER_THREAD = t
    # 红线只改本文件 · 跟 condenser 同处拉起，避免再改 opus_daemon.py
    try:
        start_she_gallery_scheduler_in_background(first_delay_sec=first_delay_sec + 60)
    except Exception:
        pass
    # 第 3 步 · 手册自动整理 (每周 · 上限 1 簇 · 先备份 + 状态机退休)
    try:
        start_playbook_curator_scheduler_in_background(first_delay_sec=first_delay_sec + 900)
    except Exception:
        pass
    # 第 4 步 · 月度复盘自动起草 (每天检查 · 到期才跑)
    try:
        start_monthly_review_scheduler_in_background(first_delay_sec=first_delay_sec + 1800)
    except Exception:
        pass
    return t


def is_state_condenser_scheduler_alive() -> bool:
    return _STATE_CONDENSER_THREAD is not None and _STATE_CONDENSER_THREAD.is_alive()


def _she_gallery_loop(first_delay_sec: int) -> None:
    """每 6h 来问一句。开机第一拍只排下次，不补发。交差由画廊闸自己掷。"""
    try:
        from workers.she_gallery import make_gallery_entry
    except ImportError:
        return

    interval_sec = 6 * 3600
    _SCHEDULER_STATE["gallery_started_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(
        "she_gallery scheduler started · first tick in %ds (boot skip) · then every 6h",
        first_delay_sec,
    )
    time.sleep(first_delay_sec)
    boot_skip = True
    while True:
        _SCHEDULER_STATE["gallery_last_run_at"] = datetime.now(timezone.utc).isoformat()
        try:
            if boot_skip:
                boot_skip = False
                _SCHEDULER_STATE["gallery_last_result"] = "boot_skip"
                logger.info("she_gallery tick skipped: boot_skip")
            else:
                result = make_gallery_entry()
                reason = result.get("reason") if not result.get("ok") else "ok"
                _SCHEDULER_STATE["gallery_last_result"] = reason
                if result.get("ok"):
                    _SCHEDULER_STATE["gallery_runs_completed"] = (
                        _SCHEDULER_STATE.get("gallery_runs_completed", 0) + 1
                    )
                    logger.info("she_gallery tick · posted")
                else:
                    logger.info("she_gallery tick skipped: %s", reason)
        except Exception:
            pass
        try:
            from datetime import timedelta
            next_ts = datetime.now(timezone.utc) + timedelta(seconds=interval_sec)
            _SCHEDULER_STATE["gallery_next_run_at"] = next_ts.isoformat()
        except Exception:
            pass
        time.sleep(interval_sec)


def start_she_gallery_scheduler_in_background(
    first_delay_sec: int = 180,
) -> Optional[threading.Thread]:
    """她·画廊 · 6h 来问。冷却 18–48h + 新信号 + 骰子。开机不补发。"""
    global _SHE_GALLERY_THREAD
    if _SHE_GALLERY_THREAD is not None and _SHE_GALLERY_THREAD.is_alive():
        return _SHE_GALLERY_THREAD
    t = threading.Thread(
        target=_she_gallery_loop,
        kwargs={"first_delay_sec": first_delay_sec},
        name="OpusSheGalleryScheduler",
        daemon=True,
    )
    t.start()
    _SHE_GALLERY_THREAD = t
    return t


def is_she_gallery_scheduler_alive() -> bool:
    return _SHE_GALLERY_THREAD is not None and _SHE_GALLERY_THREAD.is_alive()


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
