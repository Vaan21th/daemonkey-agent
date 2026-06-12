"""workers/flow_runner.py
=========================

沉淀闭环 v2 · 刀② · steps 工作流执行器 + 落盘状态机 (2026-06-10)
P0 · 异步化 (2026-06-10 用户痛点: 跑 flow 同步阻塞主对话 turn 几分钟)

为什么不用 workflow_engine
---------------------------
workflow_engine 跑 litegraph 图 (端口对齐 · 全内存 · 无状态落盘)。
steps flow 的执行哲学不同: 线性步骤 · 松耦合传递 (上步产出整体给下步当上下文) ·
**每步状态落盘** —— 这是铁律衰减治理第③档: 对话再长 · LLM 忘了 · 状态文件没忘 ·
workshop_context 每轮把活跃 run 进度重新注入 · 等于"刚说过"。

落点
----
- 状态: data/workshop/runs/<run_id>.json (运行时产物 · gitignored)
- run_id: run-<yyyymmdd-HHMMSS>-<4hex>
- 状态机: pending → running → done | failed (单步: pending/running/done/failed/skipped)
- 断点: start(from_step) / resume(run_id, from_step) · 失败后修好 app 从失败步续跑 ·
  不用整条重来 (用户: "精确到环·不整体重来")

执行约定
--------
- 每步 = 解析 app (id 优先 · 名字兜底) → app_runner.run_app(goal+substeps 进 inputs ·
  上步 outputs 走 upstream_outputs) → 状态落盘
- 步失败 → run 失败收场 · 状态保留 (on_fail='goto:N' 字段已存 · 回跳留刀③ · 防失控循环)

异步入口 (P0)
---------------------
- `start_run_async` / `resume_run_async` : 同步建初始 state + 落盘 + 派 daemon thread
  跑 `_execute` · 立刻返回 (state.status='running', current_step=from_step)。
- LLM tool turn 不再 hang · 用户在 chat 实时看 banner 进度色 (2.5s 轮询 +
  workshop_context 注入活跃 run · 完成 / 失败下轮 AI 自然提醒)。
- 子线程内自行管理信任 ContextVar (ContextVar 不跨线程·必须 worker 内重新 set)。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "data" / "workshop" / "runs"

_UPSTREAM_TEXT_MAX = 2000


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _atomic_write(path: Path, content: str) -> None:
    from .safe_write import atomic_write_text
    atomic_write_text(path, content, backup=False)  # run 状态高频写 · 不值得每次备份


def _save_state(state: dict) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _iso_now()
    _atomic_write(RUNS_DIR / f"{state['run_id']}.json", json.dumps(state, ensure_ascii=False, indent=2))


def load_run(run_id: str) -> Optional[dict]:
    p = RUNS_DIR / f"{(run_id or '').strip()}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_runs(*, max_items: int = 10) -> list[dict]:
    """列最近的 runs · 倒序 · 摘要"""
    if not RUNS_DIR.exists():
        return []
    out: list[dict] = []
    for p in sorted(RUNS_DIR.glob("run-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        s = load_run(p.stem)
        if not s:
            continue
        out.append({
            "run_id": s.get("run_id"),
            "flow_id": s.get("flow_id"),
            "flow_name": s.get("flow_name"),
            "status": s.get("status"),
            "current_step": s.get("current_step"),
            "total_steps": s.get("total_steps"),
            "updated_at": s.get("updated_at"),
        })
        if len(out) >= max_items:
            break
    return out


def active_runs() -> list[dict]:
    """状态 = running 的 runs (workshop_context 每轮注入用)"""
    return [r for r in list_runs(max_items=20) if r.get("status") == "running"]


def _resolve_app(ref: str) -> Optional[dict]:
    """app 引用解析: id 精确 → 名字精确 → 名字包含 (唯一命中才算)"""
    from .workshop_assets import list_apps, load_app
    ref = (ref or "").strip()
    if ref.startswith("app-"):
        return load_app(ref)
    apps = list_apps()
    exact = [a for a in apps if (a.get("name") or "").strip() == ref]
    if len(exact) == 1:
        return exact[0]
    fuzzy = [a for a in apps if ref and ref in (a.get("name") or "")]
    if len(fuzzy) == 1:
        return fuzzy[0]
    return None


def _step_inputs(step: dict) -> dict:
    inputs = {"step_goal": step.get("goal") or ""}
    subs = step.get("substeps") or []
    if subs:
        inputs["step_substeps"] = " / ".join(f"{step['idx']}-{j} {s}" for j, s in enumerate(subs, 1))
    return inputs


def _trim_outputs(outputs: dict) -> dict:
    """传给下一步前裁剪 · 防 _text 巨大撑爆下步 prompt"""
    out = {}
    for k, v in (outputs or {}).items():
        if isinstance(v, str) and len(v) > _UPSTREAM_TEXT_MAX:
            v = v[:_UPSTREAM_TEXT_MAX] + " …(截断)"
        out[k] = v
    return out


def _init_state(flow: dict, *, from_step: int = 1) -> tuple[dict, list[dict]]:
    """同步建初始 state + 落盘 · 返 (state, steps)
    
    拆出来给 sync start_run 和 async start_run_async 共用 (DRY)。
    """
    steps = list(flow.get("steps") or [])
    if not steps:
        raise ValueError(f"flow {flow.get('id')} 不是 steps 格式 (老画布 flow 请在工坊画布里跑)")

    run_id = "run-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    state = {
        "run_id": run_id,
        "flow_id": flow.get("id") or "",
        "flow_name": flow.get("name") or "",
        "status": "running",
        "current_step": from_step,
        "total_steps": len(steps),
        "started_at": _iso_now(),
        "steps": [
            {
                "idx": st["idx"],
                "app": st["app"],
                "goal": st["goal"],
                "substeps": st.get("substeps") or [],
                "status": "skipped" if st["idx"] < from_step else "pending",
                "summary": "",
                "error": None,
            }
            for st in steps
        ],
    }
    _save_state(state)
    return state, steps


def start_run(
    flow: dict,
    *,
    runtime: Any,
    progress: Optional[Callable[[str, dict], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    from_step: int = 1,
) -> dict:
    """跑一条 steps flow · **同步阻塞** 到全部跑完 · 返回最终 state
    
    给老路径 / 测试用 · LLM 工具入口走 `start_run_async` (P0 后)。
    """
    state, steps = _init_state(flow, from_step=from_step)
    return _execute(state, steps, runtime=runtime, progress=progress, cancel_check=cancel_check)


def start_run_async(
    flow: dict,
    *,
    runtime: Any,
    trusted_flow_id: Optional[str] = None,
    from_step: int = 1,
) -> dict:
    """异步跑 steps flow · 立刻返回初始 state (status=running, current_step=from_step)
    
    用户在 chat 让 AI 调 run_flow → 这条路径 → tool 立刻给 LLM 报 "已启动 run_id=xxx" ·
    LLM turn 不再 hang · 主对话立刻可继续。 后台 daemon thread 实跑 ·
    状态文件 (data/workshop/runs/<id>.json) 持续写 · 前端 2.5s 轮询拿到色态变化。
    
    Args:
        trusted_flow_id: trust_level≥2 的 flow id · worker 线程内 set ContextVar 让
            内部 CONFIRM tier 工具自动放行 (GUARD 仍要用户拍)。 ContextVar 不跨
            线程·必须传 id 到 worker 内自己 set。
    """
    state, steps = _init_state(flow, from_step=from_step)
    run_id = state["run_id"]

    def worker() -> None:
        # ContextVar 跨线程不传递 · 进 worker 后自己 set + finally reset · 别泄露
        token = None
        try:
            if trusted_flow_id:
                try:
                    from agent_tools import set_trusted_flow_context
                    token = set_trusted_flow_context(trusted_flow_id)
                except Exception:
                    token = None
            try:
                _execute(state, steps, runtime=runtime, progress=None, cancel_check=None)
            except Exception as e:
                # 防御: _execute 内部已 try/except 大多场景 · 这里兜一手
                cur = load_run(run_id) or state
                cur["status"] = "failed"
                cur["error"] = f"{type(e).__name__}: {e}"
                try:
                    _save_state(cur)
                except Exception:
                    pass
        finally:
            if token is not None:
                try:
                    from agent_tools import reset_trusted_flow_context
                    reset_trusted_flow_context(token)
                except Exception:
                    pass

    threading.Thread(target=worker, daemon=True, name=f"flow-run-{run_id}").start()
    return state


def _prep_resume(run_id: str, *, from_step: Optional[int]) -> tuple[dict, list[dict]]:
    """同步拉 state + reset 待重跑 step + 落盘 · 返 (state, steps)"""
    state = load_run(run_id)
    if not state:
        raise ValueError(f"run 不存在: {run_id}")

    from .workshop_assets import load_flow
    flow = load_flow(state.get("flow_id") or "")
    if not flow or not flow.get("steps"):
        raise ValueError(f"flow 不存在或不是 steps 格式: {state.get('flow_id')}")
    steps = list(flow["steps"])

    target = from_step or state.get("current_step") or 1
    target = max(1, min(target, len(steps)))
    for entry in state["steps"]:
        if entry["idx"] >= target:
            entry["status"] = "pending"
            entry["error"] = None
    state["status"] = "running"
    state["current_step"] = target
    _save_state(state)
    return state, steps


def resume_run(
    run_id: str,
    *,
    runtime: Any,
    progress: Optional[Callable[[str, dict], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    from_step: Optional[int] = None,
) -> dict:
    """从断点 **同步** 续跑 · 默认从失败/未完成那步开始 · from_step 可显式指定 (重跑某一环)"""
    state, steps = _prep_resume(run_id, from_step=from_step)
    return _execute(state, steps, runtime=runtime, progress=progress, cancel_check=cancel_check)


def resume_run_async(
    run_id: str,
    *,
    runtime: Any,
    trusted_flow_id: Optional[str] = None,
    from_step: Optional[int] = None,
) -> dict:
    """异步断点续跑 · 立刻返回 state (status=running)"""
    state, steps = _prep_resume(run_id, from_step=from_step)
    target_run_id = state["run_id"]

    def worker() -> None:
        token = None
        try:
            if trusted_flow_id:
                try:
                    from agent_tools import set_trusted_flow_context
                    token = set_trusted_flow_context(trusted_flow_id)
                except Exception:
                    token = None
            try:
                _execute(state, steps, runtime=runtime, progress=None, cancel_check=None)
            except Exception as e:
                cur = load_run(target_run_id) or state
                cur["status"] = "failed"
                cur["error"] = f"{type(e).__name__}: {e}"
                try:
                    _save_state(cur)
                except Exception:
                    pass
        finally:
            if token is not None:
                try:
                    from agent_tools import reset_trusted_flow_context
                    reset_trusted_flow_context(token)
                except Exception:
                    pass

    threading.Thread(target=worker, daemon=True, name=f"flow-run-{target_run_id}").start()
    return state


def _execute(
    state: dict,
    steps: list[dict],
    *,
    runtime: Any,
    progress: Optional[Callable[[str, dict], None]],
    cancel_check: Optional[Callable[[], bool]],
) -> dict:
    """跑 flow 主体 · 任何返回路径 (done / 中途 failed / cancel) 都走 _settle_trust 兜底"""
    try:
        return _execute_body(state, steps, runtime=runtime, progress=progress, cancel_check=cancel_check)
    finally:
        # done / failed / 异常 · 都给信任账本一次结算 (内化原 run_flow.py L156-165 的逻辑)
        _settle_trust(state)


def _execute_body(
    state: dict,
    steps: list[dict],
    *,
    runtime: Any,
    progress: Optional[Callable[[str, dict], None]],
    cancel_check: Optional[Callable[[], bool]],
) -> dict:
    from .app_runner import run_app

    upstream: Optional[dict] = None
    by_idx = {e["idx"]: e for e in state["steps"]}

    for st in steps:
        entry = by_idx.get(st["idx"])
        if entry is None or entry["status"] in ("done", "skipped"):
            # 已跑过/明确跳过的步 · 不重跑 (断点续跑语义)
            continue
        if cancel_check and cancel_check():
            state["status"] = "failed"
            entry["status"] = "failed"
            entry["error"] = "用户取消"
            _save_state(state)
            return state

        state["current_step"] = st["idx"]
        entry["status"] = "running"
        _save_state(state)
        if progress:
            try:
                progress("flow_step_start", {"run_id": state["run_id"], "step": st["idx"], "app": st["app"]})
            except Exception:
                pass

        app = _resolve_app(st["app"])
        if app is None:
            entry["status"] = "failed"
            entry["error"] = f"app 解析失败: {st['app']!r} (不存在或名字命中多个 · 用 app-id 引用)"
            state["status"] = "failed"
            _save_state(state)
            return state

        entry["app_id"] = app.get("id")
        result = run_app(
            app=app,
            inputs=_step_inputs(st),
            runtime=runtime,
            progress=progress,
            cancel_check=cancel_check,
            upstream_outputs=upstream,
        )

        if not result.get("ok"):
            entry["status"] = "failed"
            entry["error"] = result.get("error") or "(未知错误)"
            state["status"] = "failed"
            _save_state(state)
            return state

        text = result.get("text") or ""
        entry["status"] = "done"
        entry["summary"] = text[:300] + ("…" if len(text) > 300 else "")
        entry["finished_at"] = _iso_now()
        upstream = _trim_outputs(result.get("outputs") or {})
        _save_state(state)
        if progress:
            try:
                progress("flow_step_done", {"run_id": state["run_id"], "step": st["idx"]})
            except Exception:
                pass

    state["status"] = "done"
    state["current_step"] = state["total_steps"]
    _save_state(state)

    try:
        from .workshop_assets import increment_flow_runs
        increment_flow_runs(state.get("flow_id") or "")
    except Exception:
        pass

    # 沉淀闭环 v2 刀④ · 收口提示 (跑完一条 flow · 下轮主对话提示"要不要固化")
    try:
        from .workshop_run_closure import note_flow_done
        note_flow_done(state.get("flow_id") or "", state.get("run_id") or "")
    except Exception:
        pass

    # done 路径的 _settle_trust 由外层 _execute 的 finally 兜底 · 不重复调
    return state


def _settle_trust(state: dict) -> None:
    """跑完后 (done / failed) 调一次 · 给 flow 信任账本 bump 或 reset
    
    done   → bump 一档 (累积成功 → 下次 run_flow 直接 AUTO · 不再要用户拍 y)
    failed → reset 到 0 (任何失败重置 · 防带病升级)
    """
    fid = (state.get("flow_id") or "").strip()
    if not fid:
        return
    try:
        from .workshop_assets import bump_flow_trust, reset_flow_trust
        st = state.get("status")
        if st == "done":
            bump_flow_trust(fid)
        elif st == "failed":
            err = next(
                (e.get("error") for e in state.get("steps") or [] if e.get("status") == "failed"),
                state.get("error") or "",
            )
            reset_flow_trust(fid, reason=str(err or ""))
    except Exception:
        pass


def format_run(state: dict) -> str:
    """run 状态 → 人话 (工具回显 / 上下文注入共用)"""
    from .flow_steps import format_steps
    statuses = {e["idx"]: e["status"] for e in state.get("steps") or []}
    steps_view = [
        {"idx": e["idx"], "app": e["app"], "goal": e["goal"], "substeps": e.get("substeps") or []}
        for e in state.get("steps") or []
    ]
    head = (
        f"run `{state.get('run_id')}` · flow 「{state.get('flow_name')}」({state.get('flow_id')}) · "
        f"状态 {state.get('status')} · 第 {state.get('current_step')}/{state.get('total_steps')} 步"
    )
    body = format_steps(steps_view, current=int(state.get("current_step") or 0), statuses=statuses)
    fails = [e for e in state.get("steps") or [] if e.get("status") == "failed"]
    tail = ""
    if fails:
        tail = "\n失败详情: " + "; ".join(f"STEP{e['idx']} {e.get('error')}" for e in fails)
    return f"{head}\n{body}{tail}"
