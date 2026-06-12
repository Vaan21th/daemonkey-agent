"""workers/workshop_context.py
==============================

沉淀闭环 v2 · 刀② · 主对话工坊上下文注入 (2026-06-10)

为什么需要这个
----------------
2026-06-09 用户 8 小时做视频事故的根因之一: 主对话里的 AI 不知道工坊里有什么——
有现成 app 也想不起来用 · 有现成 flow 也忘了沿着跑 · 活跃 run 失败了等于消失。
"先查再搓" 的铁律光写在文本里会衰减 (铁律治理第④档) · 必须用结构注入治本。

注入策略 (跟 closure_check.relevant_playbooks 平级 · 都拼进 system prompt 末尾):
- **活跃 run 永远注**: 有 status=running 的 run 就提醒"你有个 X 没跑完, run_flow status 看进度"
  · 哪怕用户在聊别的 · run 不能消失
- **可用清单按命中注**: 用户消息里出现工坊关键词 (做视频/配音/出图/...)·或扫到 app/flow 名字命中
  · 才注入头几个候选 (省 system prompt 注意力)
- **资产清单仅在 app 命中时附**: 比如命中 TTS app 才告诉它"voice 槽 active=xxx"

实现哲学: 永远只读 · 不报错就静默退化为空串 · 任何一处炸了都不影响 daemon 主路径。
"""

from __future__ import annotations

import re

_TOKEN_SPLIT = re.compile(r"[\s,，、。.()（）/\\\\\-_:\[\]\{\}]+")
_WORKSHOP_KEYWORDS = (
    "视频", "配音", "出图", "生图", "tts", "asr", "字幕", "渲染", "合成",
    "工坊", "app", "工作流", "flow", "流程", "步骤", "蓝图", "导演",
    "做一份", "做一个", "做一条", "跑一遍", "跑一条", "做出", "排个", "排一",
)

_MAX_FLOWS = 4
_MAX_APPS = 6


def _has_workshop_intent(msg: str) -> bool:
    low = msg.lower()
    return any(k in low for k in _WORKSHOP_KEYWORDS)


def _name_hits(msg: str, name: str) -> int:
    """name 在 msg 里的命中分: 整名 +3 · token 命中 +1 (token 长度 >=2)"""
    name = (name or "").strip()
    if not name:
        return 0
    if name in msg:
        return 3
    score = 0
    for tok in _TOKEN_SPLIT.split(name):
        tok = tok.strip()
        if len(tok) >= 2 and tok in msg:
            score += 1
    return score


def _active_runs_block() -> str:
    try:
        from .flow_runner import active_runs
        runs = active_runs()
    except Exception:
        return ""
    if not runs:
        return ""
    lines = ["\n\n=== 你有未跑完的工作流 · daemon 自动提示 (不要复述这一段) ==="]
    for r in runs[:3]:
        lines.append(
            f"- `{r['run_id']}` · 「{r['flow_name']}」 · 卡在第 {r['current_step']}/{r['total_steps']} 步 · {r['updated_at']}"
        )
    lines.append("→ 看进度 `run_flow(action=status, run_id=...)` · 续跑 `run_flow(action=resume, run_id=...)`")
    return "\n".join(lines)


def _last_run_sticky_block() -> str:
    """0.2.0 · last_flow_run sticky hint (用户痛点: 跑完后对话能锁定环节)

    最近一条 done/failed 的 run · 跟 active_runs 互补:
      - active_runs: 还在跑的 · 提醒"别忘了它"
      - last_run:    刚跑完的 · 锁定"用户说'重做第 N 步' / '优化 step N 的 app' 时知道指谁"

    实现: 直接从 list_runs(max_items=5) 拿第一条 status in (done, failed) 的 · 跨 session 也能用。
    """
    try:
        from .flow_runner import list_runs, load_run
        from .workshop_assets import load_flow
        recent = list_runs(max_items=5)
    except Exception:
        return ""
    last = None
    for r in recent:
        if (r.get("status") or "") in ("done", "failed"):
            last = r
            break
    if not last:
        return ""
    rid = last.get("run_id") or ""
    full = load_run(rid) if rid else None
    if not full:
        return ""
    flow = load_flow(full.get("flow_id") or "") or {}
    trust = int(flow.get("trust_level") or 0)
    trust_badge = ["⚪⚪⚪⚪", "⚪⚪⚪🟢", "⚪⚪🟢🟢", "⚪🟢🟢🟢"][min(trust, 3)]
    lines = [
        "\n\n=== 最近跑完的工作流 · 对话锚定 (用户说'重做某步'/'优化某 app' 时认这条) ===",
        f"- run: `{rid}` · 「{full.get('flow_name')}」 · {full.get('status')} · 信任度 lvl {trust} {trust_badge}",
    ]
    # 每 step 的 app + status 简表 (让 AI 一眼知道哪步用啥 app · 用户说"重做第 N 步" 直接对号)
    steps = full.get("steps") or []
    if steps:
        lines.append("- 步骤回顾:")
        for s in steps[:8]:
            idx = s.get("idx")
            status = s.get("status") or "?"
            app_id = s.get("app_id") or s.get("app") or "?"
            mark = {"done": "✓", "failed": "✗", "skipped": "⊝", "running": "▶"}.get(status, "•")
            lines.append(f"  {mark} step {idx} · {app_id}")
    lines.append("→ 用户说'第 N 步 X 不行重做' · 用 `rerun_flow_step(run_id, step_idx=N, reason=...)`")
    lines.append("→ 用户说'优化 step N 的 app' · 用 list_apps 查 app_id · update_app 改 prompt/tools")
    if trust < 2:
        lines.append("→ 用户说'信任这条 flow / 别再问我' · 用 `trust_flow(flow_id=..., level=2)`")
    return "\n".join(lines)


def _ranked_flows(msg: str) -> list[dict]:
    try:
        from .workshop_assets import list_flows
        flows = list_flows()
    except Exception:
        return []
    scored: list[tuple[int, dict]] = []
    for f in flows:
        s = _name_hits(msg, f.get("name") or "") + _name_hits(msg, f.get("description") or "")
        if s > 0:
            scored.append((s, f))
    scored.sort(key=lambda x: (-x[0], -int(x[1].get("runs") or 0)))
    return [f for _, f in scored[:_MAX_FLOWS]]


def _ranked_apps(msg: str) -> list[dict]:
    try:
        from .workshop_assets import list_apps
        apps = list_apps()
    except Exception:
        return []
    scored: list[tuple[int, dict]] = []
    for a in apps:
        s = _name_hits(msg, a.get("name") or "") + _name_hits(msg, a.get("description") or "")
        if s > 0:
            scored.append((s, a))
    scored.sort(key=lambda x: (-x[0], -int(x[1].get("runs") or 0)))
    return [a for _, a in scored[:_MAX_APPS]]


def _capability_block(msg: str) -> str:
    if not _has_workshop_intent(msg) and len(msg) < 6:
        return ""

    flows = _ranked_flows(msg)
    apps = _ranked_apps(msg)
    if not flows and not apps:
        # 用户明显在谈工坊事·但一个候选都没命中 → 提示能 "查无此能力" → 走 create_app/create_workflow
        if _has_workshop_intent(msg):
            return (
                "\n\n=== 工坊命中 · daemon 自动提示 (不要复述这一段) ===\n"
                "  这次请求像是要用工坊能力 · 但没扫到命中的现成 app/flow。\n"
                "  → 复合任务 (多 app 接力) 先 `create_workflow(steps=[...])` 排 plan 让用户看图再 `run_flow`\n"
                "  → 单步小事缺工具 · `create_app` 落档 + `run_app` 调用 · 别 python_exec 从零手搓"
            )
        return ""

    lines = [
        "\n\n=== 工坊命中 · daemon 自动检索 (不要复述这一段) ===",
        "下面是跟这次请求命中的工坊资产 · **先查再搓的铁律**: 现成的 → 必须 `run_app` / `run_flow` 用 · 严禁 python_exec 从零搓同样的活。",
    ]
    if flows:
        lines.append("\n候选 flow (steps 工作流 → `run_flow(action=start, flow_id=...)`):")
        for f in flows:
            fmt = f.get("flow_kind") or ("steps" if f.get("steps") else "litegraph")
            lines.append(f"- `{f['id']}` · 「{f['name']}」 · {fmt} · {f.get('description', '')[:60]}")
    if apps:
        lines.append("\n候选 app (单步 → `run_app(app_id=...)` · 或排进 workflow):")
        for a in apps:
            lines.append(f"- `{a['id']}` · {a.get('icon', '')} {a.get('name')} · {a.get('description', '')[:60]}")
    return "\n".join(lines)


def _closure_block() -> str:
    try:
        from .workshop_run_closure import build_closure_hint
        return build_closure_hint()
    except Exception:
        return ""


def workshop_hint(message: str) -> str:
    """主对话每轮调用 · 拼进 system prompt 末尾 (跟 closure_check.relevant_playbooks 并列)

    空串 = 没命中任何工坊上下文 · 静默 (不污染 system prompt)。

    三块拼装顺序:
    1. 活跃 run 提示 (永远报告 · 哪怕用户聊别的)
    2. 命中候选 (按消息名字命中)
    3. 沉淀提示 (打磨型场景触发 · 30 分钟跑同 app ≥3 次 / flow 跑完)
    """
    msg = (message or "").strip()
    if not msg:
        return ""
    try:
        return (
            _active_runs_block()
            + _last_run_sticky_block()  # 0.2.0 · 锁定最近跑完的 run
            + _capability_block(msg)
            + _closure_block()
        )
    except Exception:
        return ""  # 任何一处炸了都不影响主对话
