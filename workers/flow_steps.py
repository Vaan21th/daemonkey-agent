"""workers/flow_steps.py
========================

沉淀闭环 v2 · 刀② · steps 线性工作流格式 (2026-06-10 BRO 拍板 · Coze 3.0 同向验证)
卷七十五 · v0.6.0 P2 · 并行组 (2026-07-10 BRO 痛点: 一步里想多个 app / 同 app 并行跑)

为什么从 litegraph 图转向 steps 清单
------------------------------------
- litegraph 图 LLM 生成极易错 (nodes/links/槽位索引) · 这是"工作流概念不深"的工程原因之一
- 执行者是 LLM · 上步产出走 upstream_outputs 松耦合传下步 · 端口级硬对齐没有意义
- steps 状态 = "第几步" · 落盘/恢复/每轮重注都简单 (铁律衰减治理第③档)
- 画布降级为只读视图: steps_to_litegraph() 自动投影一条链 · 老画布 UI 照常能看

两层结构 (BRO: "STEP1 STEP2 2-1 2-2 2-3 STEP3")
------------------------------------------------
- 主步骤 = 执行单位 · 一步 = 一个 app 跑一次 · 状态机记"第几主步"
- substeps = 站内清单 · 在一次 app 运行内部完成 · 作用: 进度可见 + 站内断点
- 子步骤常常运行时由导演蓝图动态展开 · 模板里可以只留固定项

并行组 (卷七十五 P2)
--------------------
一个主步既可以是【单 app 串行步】· 也可以是【并行组】: 组内 2~N 个分支同时跑 ·
各拿同一份上游 · 跑完输出合并喂下一步。 覆盖两种诉求 (同一套机制):
  - 多个不同 app 并行:  parallel=[{app:出图,goal},{app:搜索,goal}]
  - 同一 app 并行不同输入: parallel=[{app:浏览器,goal:搜A},{app:浏览器,goal:搜B}]

step 字段:
    单 app 步:
        app      (必填) app id (app-xxxxxxxx) 或 app 名字 (跑时解析)
        goal     (必填) 这一步要达成什么 · 会拼进该 app 的输入
        substeps (可选) list[str] 站内清单
    并行组步:
        parallel (必填) list · 2~4 个分支 · 每分支 = {app, goal, substeps?}
        goal     (可选) 组级说明 · 给人看这组一起干嘛
    公共:
        on_fail  (可选) 'stop' (默认) | 'goto:N' 回跳第 N 步 (留字段 · runner 刀③实现回跳)
"""

from __future__ import annotations

import re

_MAX_STEPS = 20
_MAX_SUBSTEPS = 12
_MAX_PARALLEL = 4          # 一个并行组最多几个分支 (token 安全 · 每分支都是一次完整 app 跑)
_APP_ID_RE = re.compile(r"^app-[0-9a-f]{8}$")
_ON_FAIL_RE = re.compile(r"^(stop|goto:\d{1,2})$")


def _clean_substeps(subs: object, ctx: str) -> list[str]:
    if not isinstance(subs, list):
        raise ValueError(f"{ctx}.substeps 必须是 list[str]")
    if len(subs) > _MAX_SUBSTEPS:
        raise ValueError(f"{ctx}.substeps 太长 (max {_MAX_SUBSTEPS})")
    return [str(s).strip() for s in subs if str(s).strip()]


def _validate_branch(br: object, ctx: str) -> dict:
    """并行组里的单个分支 · 结构同单 app 步的 {app, goal, substeps?}"""
    if not isinstance(br, dict):
        raise ValueError(f"{ctx} 必须是 dict")
    app = str(br.get("app") or "").strip()
    if not app:
        raise ValueError(f"{ctx}.app 必填 (app id 或 app 名字)")
    goal = str(br.get("goal") or "").strip()
    if not goal:
        raise ValueError(f"{ctx}.goal 必填 (这个并行分支要达成什么)")
    cleaned: dict = {"app": app, "goal": goal}
    subs = br.get("substeps")
    if subs:
        cleaned["substeps"] = _clean_substeps(subs, ctx)
    return cleaned


def validate_steps(raw: object) -> list[dict]:
    """规范化 + 校验 steps · 不合法抛 ValueError

    向后兼容: 没有 parallel 字段的步 = 原来的单 app 串行步 · 行为一字不变。
    """
    if not isinstance(raw, list) or not raw:
        raise ValueError("steps 必须是非空 list")
    if len(raw) > _MAX_STEPS:
        raise ValueError(f"steps 太长: {len(raw)} (max {_MAX_STEPS})")

    out: list[dict] = []
    for i, st in enumerate(raw):
        n = i + 1
        if not isinstance(st, dict):
            raise ValueError(f"steps[{i}] 必须是 dict")

        parallel = st.get("parallel")
        if parallel is not None:
            # ── 并行组步 ──
            if st.get("app"):
                raise ValueError(f"steps[{i}] · app 和 parallel 二选一 · 不能同时给")
            if not isinstance(parallel, list) or len(parallel) < 2:
                raise ValueError(
                    f"steps[{i}].parallel 必须是 ≥2 个分支的 list (只有一个分支就用 app 单步)"
                )
            if len(parallel) > _MAX_PARALLEL:
                raise ValueError(
                    f"steps[{i}].parallel 太多分支: {len(parallel)} (max {_MAX_PARALLEL} · 防 token 爆)"
                )
            branches = [
                _validate_branch(b, f"steps[{i}].parallel[{j}]")
                for j, b in enumerate(parallel)
            ]
            cleaned: dict = {"idx": n, "parallel": branches}
            group_goal = str(st.get("goal") or "").strip()
            if group_goal:
                cleaned["goal"] = group_goal
        else:
            # ── 单 app 串行步 (原逻辑) ──
            app = str(st.get("app") or "").strip()
            if not app:
                raise ValueError(f"steps[{i}].app 必填 (app id 或 app 名字 · 或用 parallel 并行组)")
            goal = str(st.get("goal") or "").strip()
            if not goal:
                raise ValueError(f"steps[{i}].goal 必填 (这一步要达成什么)")
            cleaned = {"idx": n, "app": app, "goal": goal}
            subs = st.get("substeps")
            if subs:
                cleaned["substeps"] = _clean_substeps(subs, f"steps[{i}]")

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


def _name_map() -> dict[str, str]:
    """app id → name 字典 (查不到的保持 ref 显示)"""
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
    return name_map


def _mk_node(nid: int, app_ref: str, title: str, pos: list[int], goal: str,
             disp: str, order: int, *, is_parallel: bool,
             step_idx: int, branch_idx: int | None = None) -> dict:
    ntype = f"opus/app/{app_ref}" if _APP_ID_RE.match(app_ref) else "opus/app/unresolved"
    # step_idx / branch_idx: 前端跑时染色靠这个映射回 run 状态 (并行步一步多节点 ·
    # node id 不再等于步序号 · 必须显式带上)。
    props = {
        "goal": goal, "app_ref": app_ref, "app_name": disp,
        "parallel": is_parallel, "step_idx": step_idx,
    }
    if branch_idx is not None:
        props["branch_idx"] = branch_idx
    return {
        "id": nid,
        "type": ntype,
        "title": title,
        "pos": pos,
        "size": [240, 110],
        "order": order,
        "mode": 0,
        "flags": {},
        "properties": props,
        "inputs": [{"name": "in", "type": "string", "link": None}],
        "outputs": [{"name": "out", "type": "string", "links": []}],
    }


def _mk_join(nid: int, pos: list[int], slot_names: list[str], order: int, step_idx: int) -> dict:
    """并行组汇合节点 (卷七十五续三)。

    litegraph 只按 input 槽画线·一个 input 槽只认一条 link → 并行分支没法直接扇入下一步的
    单个 in 槽 (只画得出最后一条)。 用一个我方全控的汇合节点 (N 个 in 槽·各接一路分支·
    1 个 out 接下一步) 绕开该约束——且这一步在 flow_runner 里【本就存在】: 并行组跑完会把
    各分支产出合并 (namespaced) 再喂下一步·汇合节点就是这步的可视化。 前端注册
    opus/flow_join 类型 (构造器不加槽·全靠 configure 从这里的序列化填)。
    """
    return {
        "id": nid,
        "type": "opus/flow_join",
        "title": "⋔ 汇合",
        "pos": pos,
        "size": [130, 26 + len(slot_names) * 18],
        "order": order,
        "mode": 0,
        "flags": {},
        "properties": {"step_idx": step_idx, "is_join": True},
        "inputs": [{"name": nm, "type": "string", "link": None} for nm in slot_names],
        "outputs": [{"name": "out", "type": "string", "links": []}],
    }


def steps_to_litegraph(steps: list[dict]) -> dict:
    """steps → litegraph 只读投影 · 画布 tab 能看到 · 不用于执行

    并行组 (卷七十五 P2): 组内分支在同一列纵向堆叠 · 上一步的每个节点扇形连到本组每个分支 ·
    本组每个分支再扇形连到下一步 —— 画布上一眼看出"这一步是几路并行"。
    """
    name_map = _name_map()

    COL_W = 300
    ROW_H = 140

    nodes: list[dict] = []
    links: list[list] = []
    node_by_id: dict[int, dict] = {}
    node_id = 0
    link_id = 0
    prev_ids: list[int] = []
    col_x = 80  # 走位游标: 并行组占两列 (分支列 + 汇合列) · 串行步占一列

    def _link(oid: int, oslot: int, tid: int, tslot: int) -> None:
        """连一条 origin.out[oslot] → target.in[tslot]。 扇出走 output.links 数组 (litegraph
        支持一出多连);扇入必须落到不同 target 槽 (一个 in 槽只认一条·汇合节点给足 N 个槽)。"""
        nonlocal link_id
        link_id += 1
        links.append([link_id, oid, oslot, tid, tslot, "string"])
        node_by_id[oid]["outputs"][oslot]["links"].append(link_id)
        node_by_id[tid]["inputs"][tslot]["link"] = link_id

    for i, st in enumerate(steps):
        if st.get("parallel"):
            branches = st["parallel"]
            span = (len(branches) - 1) * ROW_H
            y0 = 140 - span // 2
            branch_ids: list[int] = []
            for j, br in enumerate(branches):
                node_id += 1
                app_ref = br["app"]
                disp = name_map.get(app_ref, app_ref)
                node = _mk_node(
                    node_id, app_ref, f"{i + 1}.{j + 1} {disp}",
                    [col_x, y0 + j * ROW_H], br["goal"], disp, node_id - 1, is_parallel=True,
                    step_idx=i + 1, branch_idx=j,
                )
                nodes.append(node)
                node_by_id[node_id] = node
                branch_ids.append(node_id)
            # 上一步 → 每个分支 (扇出 · 走 output.links 数组 · litegraph 能画全)
            for pid in prev_ids:
                for cid in branch_ids:
                    _link(pid, 0, cid, 0)
            # 汇合节点: 每个分支扇入它的独立 in 槽 → 绕开"单 in 槽一条线"的死约束
            node_id += 1
            join_id = node_id
            slot_names = [f"{i + 1}.{j + 1}" for j in range(len(branches))]
            join = _mk_join(join_id, [col_x + COL_W, 140], slot_names, node_id - 1, i + 1)
            nodes.append(join)
            node_by_id[join_id] = join
            for j, bid in enumerate(branch_ids):
                _link(bid, 0, join_id, j)
            prev_ids = [join_id]
            col_x += COL_W * 2  # 分支列 + 汇合列
        else:
            node_id += 1
            app_ref = st["app"]
            disp = name_map.get(app_ref, app_ref)
            node = _mk_node(
                node_id, app_ref, f"{i + 1}. {disp}",
                [col_x, 140], st["goal"], disp, node_id - 1, is_parallel=False,
                step_idx=i + 1,
            )
            nodes.append(node)
            node_by_id[node_id] = node
            for pid in prev_ids:
                _link(pid, 0, node_id, 0)
            prev_ids = [node_id]
            col_x += COL_W

    return {
        "nodes": nodes,
        "links": links,
        "groups": [],
        "config": {},
        "last_node_id": node_id,
        "last_link_id": link_id,
        "version": 0.4,
        "_generated_from": "steps",  # 标记: 这是投影 · 改流程请改 steps · 不要手工连线
    }


_MARKS = {"done": "[x]", "failed": "[!]", "running": "[>]"}


def format_steps(steps: list[dict], *, current: int = 0, statuses: dict | None = None,
                 branch_statuses: dict | None = None) -> str:
    """steps → 人话单行清单 (注入上下文 / 工具回显共用)

    current: 当前执行到第几步 (0=未开始) · statuses: {idx: 'done'/'failed'/...}
    branch_statuses: {(idx, branch_j): status} · 并行组分支级状态 (可选)
    """
    lines: list[str] = []
    statuses = statuses or {}
    for st in steps:
        n = st["idx"]
        mark = _MARKS.get(statuses.get(n, ""), "[ ]")
        if current and n == current and statuses.get(n) not in ("done", "failed"):
            mark = "[>]"

        if st.get("parallel"):
            group_goal = st.get("goal") or "并行组"
            lines.append(f"  {mark} STEP{n} ∥ 并行组 · {group_goal}")
            for j, br in enumerate(st["parallel"]):
                bmark = ""
                if branch_statuses is not None:
                    bmark = _MARKS.get(branch_statuses.get((n, j), ""), "[ ]") + " "
                lines.append(f"        ∥ {bmark}{br['app']} · {br['goal']}")
        else:
            lines.append(f"  {mark} STEP{n} {st['app']} · {st['goal']}")
            for j, sub in enumerate(st.get("substeps") or [], 1):
                lines.append(f"        {n}-{j} {sub}")
    return "\n".join(lines)
