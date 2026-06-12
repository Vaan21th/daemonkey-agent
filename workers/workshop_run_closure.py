"""workers/workshop_run_closure.py
===================================

沉淀闭环 v2 · 刀④ · 跑完轻量收口提示 (2026-06-10)

为什么不强制问每次都问
------------------------
"跑一次问一次要不要沉淀" 会变成骚扰 · 跟用户说"不要打扰"是迟早的事。 真正需要被提醒
的是 *打磨型* 场景: 用户在反复试同一个 app / 同一条 flow · 而没有 update_app 把这次改进
固化回去——这就是 2026-06-09 那场视频事故的形状(三版声音克隆只钉住废的第一版)。

实现思路
--------
轻量内存计数器(进程级·daemon 重启清零) + workshop_context 注入。
- app_runner.run_app 跑完 → note_app_run(aid)
- flow_runner._execute 收尾 done → note_flow_done(fid, run_id)
- 主对话每轮 workshop_hint 拼装时 · 调 build_closure_hint(message) 看有没有该提示的
  · 有 → 注入 system prompt 末尾一段(跟微信渠道 hint 同语义·随轮即弃)

触发条件 (合并)
-----------------
- 某 app 进程内被跑 ≥3 次 · 且最近一次距今 ≤ 30 分钟 · 且尚未抑制
- 某 flow 完成 done · 且尚未抑制
- 抑制窗口: 提示过一次后 15 分钟内不再提示同一对象(防唠叨)

为什么不持久化
--------------
- 持久化 = 跨重启记忆 = 老问题没人沉淀仍卡在那里反复提示 · 反而更烦
- daemon 重启意味着新一轮工作 · 重新计数即可
- 真要持久化 · changelog/asset history 已经在那 · 助手自己回顾就行
"""

from __future__ import annotations

import time
from typing import Optional

# 内存状态 (进程级 · daemon 启动归零)
_app_runs: dict[str, list[float]] = {}   # aid -> 最近 N 次跑的时间戳 (秒)
_flow_dones: dict[str, dict] = {}         # fid -> {run_id, at}
_suppress_until: dict[str, float] = {}    # key -> 抑制到何时 (epoch sec)

_TRIGGER_APP_RUNS = 3
_TRIGGER_WINDOW = 30 * 60           # 30 分钟
_SUPPRESS_WINDOW = 15 * 60          # 15 分钟


def _now() -> float:
    return time.time()


def note_app_run(aid: str) -> None:
    """app_runner 跑完调 · 失败永不抛"""
    if not aid:
        return
    try:
        cutoff = _now() - _TRIGGER_WINDOW
        hist = [t for t in _app_runs.get(aid, []) if t >= cutoff]
        hist.append(_now())
        _app_runs[aid] = hist[-10:]  # 只留最近 10 次足够判定
    except Exception:
        pass


def note_flow_done(fid: str, run_id: str) -> None:
    """flow_runner 跑完调"""
    if not fid:
        return
    try:
        _flow_dones[fid] = {"run_id": run_id, "at": _now()}
    except Exception:
        pass


def _suppress(key: str) -> None:
    _suppress_until[key] = _now() + _SUPPRESS_WINDOW


def _is_suppressed(key: str) -> bool:
    until = _suppress_until.get(key)
    return bool(until and until > _now())


def _app_brief(aid: str) -> Optional[dict]:
    try:
        from .workshop_assets import load_app
        return load_app(aid)
    except Exception:
        return None


def _flow_brief(fid: str) -> Optional[dict]:
    try:
        from .workshop_assets import load_flow
        return load_flow(fid)
    except Exception:
        return None


def build_closure_hint() -> str:
    """主对话每轮 workshop_hint 内部调 · 返回拼进 system prompt 的提示段(无候选则空)"""
    lines: list[str] = []
    now = _now()

    # 1. 反复跑某个 app
    for aid, hist in list(_app_runs.items()):
        if len(hist) < _TRIGGER_APP_RUNS:
            continue
        if (now - hist[-1]) > _TRIGGER_WINDOW:
            continue
        if _is_suppressed(f"app:{aid}"):
            continue
        app = _app_brief(aid)
        name = (app or {}).get("name") or aid
        cur_v = (app or {}).get("version") or "?"
        lines.append(
            f"- app `{aid}` 「{name}」(v{cur_v}) 在这 30 分钟内跑了 {len(hist)} 次 · "
            f"如果调出了好版本 · `update_app(aid={aid}, change_note=...)` 把改进固化回去 / "
            f"如果产出值得留 (声音/IP/参考) · `manage_app_asset(action=set, app_id={aid}, ...)` 沉淀进资产表"
        )
        _suppress(f"app:{aid}")

    # 2. flow 跑完
    for fid, info in list(_flow_dones.items()):
        if _is_suppressed(f"flow:{fid}"):
            continue
        if (now - info["at"]) > _TRIGGER_WINDOW:
            continue
        flow = _flow_brief(fid)
        name = (flow or {}).get("name") or fid
        lines.append(
            f"- flow `{fid}` 「{name}」run `{info['run_id']}` 已跑完 · "
            f"哪一步的产出/参数值得固化 → `update_app` 改对应 app / "
            f"`manage_app_asset` 把素材沉淀 · 下次同样的任务就一句话起跑"
        )
        _suppress(f"flow:{fid}")
        # 提示过就清掉 · 不重复触发
        _flow_dones.pop(fid, None)

    if not lines:
        return ""

    return (
        "\n\n=== 沉淀提示 · daemon 自动检测 (不要复述这一段) ===\n"
        "下面这些活动最近被你打磨过 · **跑过 ≠ 沉淀了** · 别让心血只活在对话里:\n"
        + "\n".join(lines)
    )


def reset() -> None:
    """daemon 启动 / 自测用 · 清空所有状态"""
    _app_runs.clear()
    _flow_dones.clear()
    _suppress_until.clear()
