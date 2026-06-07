"""workers/workflow_engine.py
=============================

卷四十六续 12 · wish-165ea1f6 phase B · 工作流引擎 · 拓扑串跑 + node 数据流

scope (phase B 第一刀 · 故意做小):
  - 一条直线管线 (DAG) · 拓扑排序后顺序跑 · 不并发
  - 支持的 node kind:
      * `opus/app/<aid>` · 跑一个 OPUS 工坊 app · 走 app_runner.run_app
  - 暂不支持:
      * 循环 / 分支 / 错误重试 (Phase C 后续做)
      * 并发 (一条 pipeline 通常没几个 node · 串行够用)
      * 复杂数据类型 schema 校验 (上游 output dict 直接塞下游 inputs · 名字对上就行)

LiteGraph litegraph_json 结构 (workshop 里 .serialize() 出来的)::

    {
      "nodes": [
        {"id": 1, "type": "opus/app/app-abc123", "pos": [...], "size": [...],
         "inputs":  [{"name": "topic", "type": "string", "link": <link_id|null>}, ...],
         "outputs": [{"name": "script", "type": "string", "links": [<link_id>, ...]}, ...],
         "properties": {...}},
         ...
      ],
      "links": [[link_id, src_node, src_slot, dst_node, dst_slot, type], ...],
    }

数据流:
    上游 node 跑完后 · outputs[port_name] 落入 _node_outputs[node_id]
    下游 node 跑前 · 按 input port 找连进来的 link · 从 _node_outputs 拉值 · 拼进 inputs dict
    起始 node (没 input link) · 用 payload.entry_inputs 提供初值
"""

from __future__ import annotations

from typing import Any, Callable, Optional


def _build_topo_order(nodes: list[dict], links: list) -> list[int]:
    """拓扑排序 · 返回 node id 顺序

    LiteGraph link 格式: [link_id, src_node_id, src_slot, dst_node_id, dst_slot, type]
    """
    indeg: dict[int, int] = {n["id"]: 0 for n in nodes}
    adj: dict[int, list[int]] = {n["id"]: [] for n in nodes}

    for lk in links or []:
        if not isinstance(lk, (list, tuple)) or len(lk) < 5:
            continue
        src_id = lk[1]
        dst_id = lk[3]
        if src_id not in indeg or dst_id not in indeg:
            continue
        adj[src_id].append(dst_id)
        indeg[dst_id] += 1

    queue = [nid for nid, d in indeg.items() if d == 0]
    order: list[int] = []
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for nxt in adj[nid]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(nodes):
        ordered = set(order)
        cyclic = [n["id"] for n in nodes if n["id"] not in ordered]
        raise ValueError(f"workflow has cycles (node ids: {cyclic[:6]})")

    return order


def _resolve_link(links: list, link_id: int) -> Optional[tuple]:
    """从 links 表里找 link_id 的连线 · 返回 (src_node, src_slot) 或 None"""
    for lk in links or []:
        if not isinstance(lk, (list, tuple)) or len(lk) < 5:
            continue
        if lk[0] == link_id:
            return (lk[1], lk[2])
    return None


def _resolve_src_output_name(src_node: Optional[dict], src_slot: int) -> Optional[str]:
    """从源 node 拿 src_slot 对应的 output port name"""
    if not isinstance(src_node, dict):
        return None
    outs = src_node.get("outputs") or []
    if 0 <= src_slot < len(outs) and isinstance(outs[src_slot], dict):
        return outs[src_slot].get("name")
    return None


def _gather_inputs(
    node: dict,
    links: list,
    nodes_by_id: dict[int, dict],
    node_outputs: dict[int, dict],
    entry_inputs: dict,
) -> dict:
    """组装一个 node 的 inputs · 上游 output → 当前 node input

    优先级:
      1. 有连入 link · 从上游对应 output 拉值 (按 src port name)
      2. 没 link · 从 entry_inputs 拉 (key 可以是 '<node_id>.<input_name>' 或 '<input_name>')
      3. 都没 · 跳过这个字段 (LLM 用 default 或自己问)
    """
    inputs: dict = {}
    node_id = node.get("id")

    for slot_idx, inp in enumerate(node.get("inputs") or []):
        if not isinstance(inp, dict):
            continue
        port_name = inp.get("name") or f"in_{slot_idx}"
        link_id = inp.get("link")

        if link_id is not None:
            resolved = _resolve_link(links, link_id)
            if resolved is not None:
                src_node_id, src_slot = resolved
                src_outputs = node_outputs.get(src_node_id) or {}
                if src_outputs:
                    src_node = nodes_by_id.get(src_node_id)
                    out_name = _resolve_src_output_name(src_node, src_slot)
                    if out_name and out_name in src_outputs:
                        inputs[port_name] = src_outputs[out_name]
                    elif "output" in src_outputs:
                        inputs[port_name] = src_outputs["output"]
                    else:
                        try:
                            inputs[port_name] = next(iter(src_outputs.values()))
                        except StopIteration:
                            pass

        if port_name not in inputs:
            scoped_key = f"{node_id}.{port_name}"
            if entry_inputs.get(scoped_key) is not None:
                inputs[port_name] = entry_inputs[scoped_key]
            elif entry_inputs.get(port_name) is not None:
                inputs[port_name] = entry_inputs[port_name]

    return inputs


def _run_app_node(
    node: dict,
    inputs: dict,
    upstream_outputs: dict,
    *,
    runtime: Any,
    progress: Optional[Callable[[str, dict], None]],
    cancel_check: Optional[Callable[[], bool]],
    max_iterations: int,
) -> dict:
    """跑一个 app 节点 · 卷四十六 III 补丁 5 · wish-11a7433e 落地

    分流:
      app.exec_kind == 'scripted' → workers.http_executor.run_scripted_app (0 LLM)
      其它 (agentic / 未声明)     → workers.app_runner.run_app (走 LLM)

    返回结构统一: {ok, outputs, text, error} (text 在 scripted 时为空字符串)
    """
    from workers.workshop_assets import load_app

    node_type = node.get("type") or ""
    if not node_type.startswith("opus/app/"):
        return {
            "ok": False, "error": f"unsupported node type: {node_type}",
            "outputs": {}, "text": "",
        }
    aid = node_type[len("opus/app/"):]
    app = load_app(aid)
    if not app:
        return {
            "ok": False, "error": f"app not found: {aid}",
            "outputs": {}, "text": "",
        }

    exec_kind = (app.get("exec_kind") or "").strip().lower()

    # scripted 分支 · 不走 LLM · 直接 HTTP
    if exec_kind == "scripted":
        from workers.http_executor import run_scripted_app
        result = run_scripted_app(
            app=app,
            inputs=inputs,
            runtime=runtime,
            progress=progress,
            upstream_outputs=upstream_outputs,
        )
        # 统一返回字段 (run_scripted_app 没 text / usage / iterations · 补空)
        return {
            "ok": result.get("ok", False),
            "outputs": result.get("outputs") or {},
            "text": "",
            "usage": {},
            "iterations": 0,
            "error": result.get("error"),
            "http": result.get("http") or {},
            "exec_kind": "scripted",
        }

    # agentic / 未声明 → 走 LLM
    from workers.app_runner import run_app
    result = run_app(
        app=app,
        inputs=inputs,
        runtime=runtime,
        progress=progress,
        cancel_check=cancel_check,
        upstream_outputs=upstream_outputs,
        max_iterations=max_iterations,
    )
    if isinstance(result, dict):
        result.setdefault("exec_kind", "agentic")
    return result


def run_workflow(
    *,
    flow: dict,
    entry_inputs: dict,
    runtime: Any,
    progress: Optional[Callable[[str, dict], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    max_iterations_per_node: int = 12,
) -> dict:
    """按拓扑顺序串跑一条 workflow · 返回每个节点的 outputs

    Args:
        flow: workshop_assets.load_flow 出来的 dict · 含 litegraph_json
        entry_inputs: 起始 node 的初值 · key 可以是 '<node_id>.<input_name>' 或 '<input_name>'
        runtime: daemon RUNTIME
        progress: SSE hook · 工程层透传 + 自己 push node_start/node_done
        cancel_check: 取消信号
        max_iterations_per_node: 每个 app node 内部 tool_loop 上限

    Returns:
        {
            'ok': bool,
            'nodes': {node_id: {'outputs': dict, 'text': str, ...}, ...},
            'final': {node_id, outputs}  # 终止节点 (没下游的最后一个) 的 output
            'error': str | None,
        }
    """
    graph = flow.get("litegraph_json") or {}
    if not isinstance(graph, dict):
        return {"ok": False, "nodes": {}, "final": None,
                "error": "litegraph_json missing or not a dict"}

    nodes_raw = graph.get("nodes") or []
    links = graph.get("links") or []

    if not nodes_raw:
        return {"ok": False, "nodes": {}, "final": None,
                "error": "workflow has no nodes"}

    nodes_by_id = {n["id"]: n for n in nodes_raw if isinstance(n, dict) and "id" in n}

    try:
        order = _build_topo_order(nodes_raw, links)
    except ValueError as e:
        return {"ok": False, "nodes": {}, "final": None, "error": str(e)}

    if progress:
        try:
            progress("flow_start", {
                "node_count": len(order),
                "node_types": [nodes_by_id[nid].get("type") for nid in order],
            })
        except Exception:
            pass

    node_outputs: dict[int, dict] = {}
    node_meta: dict[int, dict] = {}
    last_run_id: Optional[int] = None

    for nid in order:
        if cancel_check and cancel_check():
            return {"ok": False, "nodes": node_meta, "final": None, "error": "cancelled by user"}

        node = nodes_by_id[nid]
        node_type = node.get("type") or ""

        inputs = _gather_inputs(node, links, nodes_by_id, node_outputs, entry_inputs)

        if progress:
            try:
                progress("node_start", {
                    "node_id": nid, "type": node_type,
                    "input_keys": list(inputs.keys()),
                })
            except Exception:
                pass

        if node_type.startswith("opus/app/"):
            result = _run_app_node(
                node, inputs,
                upstream_outputs={
                    str(src_id): outs for src_id, outs in node_outputs.items()
                },
                runtime=runtime,
                progress=progress,
                cancel_check=cancel_check,
                max_iterations=max_iterations_per_node,
            )
        else:
            result = {
                "ok": False,
                "error": (
                    f"phase B 仅支持 opus/app/<aid> 节点 · "
                    f"node {nid} 是 {node_type} · 跳过"
                ),
                "outputs": {}, "text": "",
            }

        node_meta[nid] = result
        if not result.get("ok"):
            if progress:
                try:
                    progress("node_error", {
                        "node_id": nid, "type": node_type,
                        "error": result.get("error"),
                    })
                except Exception:
                    pass
            return {"ok": False, "nodes": node_meta, "final": None,
                    "error": f"node {nid} ({node_type}) failed: {result.get('error')}"}

        outs = result.get("outputs") or {}
        node_outputs[nid] = outs
        last_run_id = nid

        if progress:
            try:
                progress("node_done", {
                    "node_id": nid, "type": node_type,
                    "outputs_keys": list(outs.keys()),
                    "text_preview": (result.get("text") or "")[:300],
                })
            except Exception:
                pass

    final = {"node_id": last_run_id, "outputs": node_outputs.get(last_run_id, {})} if last_run_id else None
    if progress:
        try:
            progress("flow_done", {
                "ok": True,
                "node_count": len(order),
                "final_node_id": last_run_id,
            })
        except Exception:
            pass

    return {"ok": True, "nodes": node_meta, "final": final, "error": None}


# ---------------------------------------------------------------------------
# helpers · 卷四十六 III 补丁 5 · 给 daemon_api 用
# ---------------------------------------------------------------------------

def flow_requires_llm(graph: dict) -> dict:
    """扫一个 litegraph_json · 判断这条 workflow 是否需要 LLM client

    返回:
        {
            'requires_llm': bool,         # True 表示至少有一个 agentic app · 需要 RUNTIME.client
            'scripted_apps': [aid, ...],  # 全 scripted 节点列表
            'agentic_apps': [aid, ...],   # 走 LLM 的节点列表
            'missing_apps': [aid, ...],   # 在 graph 里但 load_app 拉不到的节点
            'unknown_types': [type, ...], # 非 opus/app/* 的节点 type
        }

    daemon_api 用这个判断: 全 scripted 就不查 RUNTIME.client · 有 agentic 才硬卡 503
    """
    from workers.workshop_assets import load_app

    out = {
        "requires_llm": False,
        "scripted_apps": [],
        "agentic_apps": [],
        "missing_apps": [],
        "unknown_types": [],
    }

    if not isinstance(graph, dict):
        return out
    nodes = graph.get("nodes") or []
    if not isinstance(nodes, list):
        return out

    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = node.get("type") or ""
        if not ntype.startswith("opus/app/"):
            if ntype:
                out["unknown_types"].append(ntype)
            continue
        aid = ntype[len("opus/app/"):]
        try:
            app = load_app(aid)
        except Exception:
            app = None
        if not app:
            out["missing_apps"].append(aid)
            # 缺 app · 保守假定它是 agentic (避免 false positive 跳过 LLM 检查)
            out["agentic_apps"].append(aid)
            out["requires_llm"] = True
            continue
        exec_kind = (app.get("exec_kind") or "").strip().lower()
        if exec_kind == "scripted":
            out["scripted_apps"].append(aid)
        else:
            out["agentic_apps"].append(aid)
            out["requires_llm"] = True

    return out
