"""workers/flow_steps.py
========================

沉淀闭环 v2 · 刀② · steps 线性工作流格式 (2026-06-10 用户拍板 · Coze 3.0 同向验证)

为什么从 litegraph 图转向 steps 清单
------------------------------------
- litegraph 图 LLM 生成极易错 (nodes/links/槽位索引) · 这是"工作流概念不深"的工程原因之一
- 执行者是 LLM · 上步产出走 upstream_outputs 松耦合传下步 · 端口级硬对齐没有意义
- steps 状态 = "第几步" · 落盘/恢复/每轮重注都简单 (铁律衰减治理第③档)
- 画布降级为只读视图: steps_to_litegraph() 自动投影一条链 · 老画布 UI 照常能看

两层结构 (用户: "STEP1 STEP2 2-1 2-2 2-3 STEP3")
------------------------------------------------
- 主步骤 = 执行单位 · 一步 = 一个 app 跑一次 · 状态机记"第几主步"
- substeps = 站内清单 · 在一次 app 运行内部完成 · 作用: 进度可见 + 站内断点
- 子步骤常常运行时由导演蓝图动态展开 · 模板里可以只留固定项

step 字段:
    app      (必填) app id (app-xxxxxxxx) 或 app 名字 (跑时解析)
    goal     (必填) 这一步要达成什么 · 会拼进该 app 的输入
    substeps (可选) list[str] 站内清单
    on_fail  (可选) 'stop' (默认) | 'goto:N' 回跳第 N 步 (留字段 · runner 刀③实现回跳)
"""

from __future__ import annotations

import re

_MAX_STEPS = 20
_MAX_SUBSTEPS = 12
_APP_ID_RE = re.compile(r"^app-[0-9a-f]{8}$")
_ON_FAIL_RE = re.compile(r"^(stop|goto:\d{1,2})$")


def validate_steps(raw: object) -> list[dict]:
    """规范化 + 校验 steps · 不合法抛 ValueError"""
    if not isinstance(raw, list) or not raw:
        raise ValueError("steps 必须是非空 list")
    if len(raw) > _MAX_STEPS:
        raise ValueError(f"steps 太长: {len(raw)} (max {_MAX_STEPS})")

    out: list[dict] = []
    for i, st in enumerate(raw):
        n = i + 1
        if not isinstance(st, dict):
            raise ValueError(f"steps[{i}] 必须是 dict")
        app = str(st.get("app") or "").strip()
        if not app:
            raise ValueError(f"steps[{i}].app 必填 (app id 或 app 名字)")
        goal = str(st.get("goal") or "").strip()
        if not goal:
            raise ValueError(f"steps[{i}].goal 必填 (这一步要达成什么)")

        cleaned: dict = {"idx": n, "app": app, "goal": goal}

        subs = st.get("substeps")
        if subs:
            if not isinstance(subs, list):
                raise ValueError(f"steps[{i}].substeps 必须是 list[str]")
            if len(subs) > _MAX_SUBSTEPS:
                raise ValueError(f"steps[{i}].substeps 太长 (max {_MAX_SUBSTEPS})")
            cleaned["substeps"] = [str(s).strip() for s in subs if str(s).strip()]

        on_fail = str(st.get("on_fail") or "stop").strip().lower()
        if not _ON_FAIL_RE.match(on_fail):
            raise ValueError(f"steps[{i}].on_fail 必须是 'stop' 或 'goto:N' · 收到 {on_fail!r}")
        if on_fail.startswith("goto:"):
            target = int(on_fail.split(":")[1])
            if not (1 <= target <= len(raw)) or target == n:
                raise ValueError(f"steps[{i}].on_fail 回跳目标越界: {on_fail}")
        cleaned["on_fail"] = on_fail

        out.append(cleaned)
    return out


def steps_to_litegraph(steps: list[dict]) -> dict:
    """steps → litegraph 只读投影 (一条链) · 画布 tab 能看到 · 不用于执行

    node type 尽量用 opus/app/<aid> (app 引用是合法 id 时) · 让画布按 app 节点渲染;
    名字引用时用占位 type · 视图层面无伤 (执行走 flow_runner · 不走 workflow_engine)。

    修补 (反馈截图节点标题显示 "1. app-46efb986" 而非 "1. 内容制作"):
        投影时按 app_ref 反查 app.name · 节点 title 用人话名字
    """
    # app id → name 字典 (查不到的保持 ref 显示)
    name_map: dict[str, str] = {}
    try:
        from .workshop_assets import list_apps
        for a in list_apps():
            aid = a.get("id") or ""
            name = a.get("name") or aid
            if aid:
                name_map[aid] = name
            if name and name not in name_map:
                name_map[name] = name
    except Exception:
        pass

    nodes: list[dict] = []
    links: list[list] = []
    for i, st in enumerate(steps):
        nid = i + 1
        app_ref = st["app"]
        ntype = f"opus/app/{app_ref}" if _APP_ID_RE.match(app_ref) else "opus/app/unresolved"
        display_name = name_map.get(app_ref, app_ref)
        node = {
            "id": nid,
            "type": ntype,
            "title": f"{nid}. {display_name}",
            "pos": [80 + i * 280, 140],
            "size": [240, 120],
            "order": i,
            "mode": 0,
            "flags": {},
            "properties": {"goal": st["goal"], "app_ref": app_ref, "app_name": display_name},
            "inputs": [{"name": "in", "type": "string", "link": (nid - 1) if i > 0 else None}],
            "outputs": [{"name": "out", "type": "string", "links": [nid] if i < len(steps) - 1 else []}],
        }
        nodes.append(node)
        if i > 0:
            links.append([nid - 1, nid - 1, 0, nid, 0, "string"])
    return {
        "nodes": nodes,
        "links": links,
        "groups": [],
        "config": {},
        "last_node_id": len(steps),
        "last_link_id": max(0, len(steps) - 1),
        "version": 0.4,
        "_generated_from": "steps",  # 标记: 这是投影 · 改流程请改 steps · 不要手工连线
    }


def format_steps(steps: list[dict], *, current: int = 0, statuses: dict | None = None) -> str:
    """steps → 人话单行清单 (注入上下文 / 工具回显共用)

    current: 当前执行到第几步 (0=未开始) · statuses: {idx: 'done'/'failed'/...}
    """
    lines: list[str] = []
    statuses = statuses or {}
    for st in steps:
        n = st["idx"]
        mark = {"done": "[x]", "failed": "[!]", "running": "[>]"}.get(statuses.get(n, ""), "[ ]")
        if current and n == current and statuses.get(n) not in ("done", "failed"):
            mark = "[>]"
        line = f"  {mark} STEP{n} {st['app']} · {st['goal']}"
        lines.append(line)
        for j, sub in enumerate(st.get("substeps") or [], 1):
            lines.append(f"        {n}-{j} {sub}")
    return "\n".join(lines)
