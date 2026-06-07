"""agent_tools/create_workflow.py
================================

 K stage 2c · OPUS 给自己造一个 workflow

什么是 workflow:
    把多个 app + 原子工具串起来的 LiteGraph 流程
    用户 在出品工坊「工作流画布」点「加载已存工作流」就能拉出来跑

调用时机:
    - 用户 跟 OPUS 说「我想做 X · 你看怎么排工作流实现」
    - OPUS 设计完 → 直接 create_workflow 落档 · 用户 在画布里看到节点就能微调

跟 create_app 的区别:
    create_app           ← 独立原子模块 · 一个能力
    create_workflow      ← 把若干 app/工具按顺序连起来的图

tier:
    TIER_AUTO —— 只是落一个 json 文件 · 不动 .env / soul / 红线动作

数据格式:
    litegraph_json 必须是 LiteGraph.serialize() 的输出 ·
    最少有 {"nodes": [...], "links": [...], "last_node_id": N, "last_link_id": M}
    OPUS 自己手写时按下面 schema 出: 每个 node 至少 id/type/pos/properties
"""

from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    name = args.get("name") or "(未命名)"
    desc = (args.get("description") or "").strip()
    graph = args.get("litegraph_json") or {}
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    n_nodes = len(nodes) if isinstance(nodes, list) else 0
    parts = [f"造一个工作流 · 「{name}」 · {n_nodes} 个节点"]
    if desc:
        parts.append(f"  - 干啥: {desc[:60]}")
    return " · ".join(parts)


def _run(args: dict) -> ToolResult:
    from workers.workshop_assets import save_flow

    graph = args.get("litegraph_json")
    # 允许 OPUS 输入字符串 (JSON 文本) · 自动 parse
    if isinstance(graph, str):
        import json as _json
        try:
            graph = _json.loads(graph)
        except Exception as e:
            return ToolResult(
                ok=False, output="", error=f"litegraph_json 不是合法 JSON: {e}"
            )

    if not isinstance(graph, dict):
        return ToolResult(
            ok=False, output="", error="litegraph_json 必须是 dict (LiteGraph.serialize() 出的对象)"
        )

    try:
        flow = save_flow({
            "name": args.get("name") or "",
            "description": args.get("description") or "",
            "litegraph_json": graph,
            "created_by": "OPUS",
        })
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"save_flow 失败: {e}")

    n_nodes = 0
    nodes = graph.get("nodes")
    if isinstance(nodes, list):
        n_nodes = len(nodes)

    lines = [
        f"# ✓ 工作流已造 · `{flow['id']}`",
        f"  - 名字: {flow['name']}",
        f"  - 简介: {flow['description']}",
        f"  - 节点数: {n_nodes}",
    ]
    if n_nodes:
        types = []
        for nd in nodes[:6]:
            if isinstance(nd, dict):
                t = nd.get("type") or nd.get("title") or "?"
                types.append(str(t))
        if types:
            lines.append(f"  - 头几个节点: {' → '.join(types)}")
    lines.append("")
    lines.append("→ 用户 去出品工坊 · 「工作流画布」tab · 「加载工作流」能看到这条新流程。")
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="create_workflow",
    description=(
        "在出品工坊里造一个新 workflow · 把多个 app + 工具串起来的 LiteGraph 流程\n\n"
        "**🔴 关键调用次序 · 用户 说『排个 X 工作流』时第一刀就是这个工具**:\n"
        "  1. **先 create_workflow 落档** · 把 name + description + litegraph_json 落到\n"
        "     data/workshop/flows/<id>.json · 用户 在『⚛ 工作流画布』tab 点 📂 加载就能拉出来\n"
        "  2. 第二刀再去做实际事 (调试某个节点 / 验证某个 API / 测一段连线是否通)\n"
        "  3. 哪怕节点功能还没跑通 · 流程图先在 · 用户 至少有一份『OPUS 帮我排好的图』可看\n\n"
        "  跟 create_app 同理 — 不要把『落档』推到最后 · 推到最后碰上 typo / timeout 就丢图\n\n"
        "**什么时候调**:\n"
        "  - 用户 说「我想做 X · 你看怎么排工作流实现」时 · 第一刀\n"
        "  - OPUS 设计完一条多步骤管线 · create_workflow 落档让 用户 看图\n"
        "  - 缺工具就先 create_app 把工具落档 · 再来 create_workflow 用上它\n\n"
        "**litegraph_json 格式**:\n"
        "  工坊里 workflow 的节点都是 **app 节点** · type 必须是 `opus/app/<aid>` · 其中 aid 来自 `create_app` 返回的 id\n"
        "  最简形态 · 每个 node 至少含 id/type/pos/size/properties · 节点之间用 links 串起来:\n"
        "  ```json\n"
        '  {\n'
        '    "last_node_id": 2, "last_link_id": 1,\n'
        '    "nodes": [\n'
        '      {"id": 1, "type": "opus/app/app-66ac4190", "pos": [100, 100], "size": [220, 110], "properties": {}},\n'
        '      {"id": 2, "type": "opus/app/app-b08ffda6", "pos": [400, 100], "size": [220, 110], "properties": {}}\n'
        '    ],\n'
        '    "links": [[1, 1, 0, 2, 0, "string"]],\n'
        '    "groups": [], "config": {}, "version": 0.4\n'
        '  }\n'
        "  ```\n"
        "  - links 元素是 `[link_id, src_node_id, src_slot, dst_node_id, dst_slot, type]`\n"
        "  - 节点之间靠 LLM 看 system prompt 自动拼接 upstream outputs · 你不用手动 binding 参数\n\n"
        "**红线**:\n"
        "  - 节点 type 只能是 `opus/app/<aid>` · 工坊 engine (workers/workflow_engine.py) **只支持** 这一种 · 用 `opus/llm-text` / `opus/file-read` 这些会被 engine 拒掉\n"
        "  - 想用某个 app · 它必须先存在 (load_app(<aid>) 能拿到) · 缺工具就先 create_app 把它落档再 create_workflow\n"
        "  - scripted app (exec_kind=scripted) 进 workflow 0 token 直跑 HTTP · agentic app 进 workflow 才走 LLM · 工坊推荐多用 scripted\n"
        "  - 不要在 description 里写「让 用户 自己来填充」 · 你设计完就给个能跑的 baseline · 用户 微调"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "工作流名字 · 一句话讲清做啥 · 比如 '日报: 抓数据 → 整理 → 推微信'",
                "minLength": 2,
                "maxLength": 100,
            },
            "description": {
                "type": "string",
                "description": "工作流用途 · 用户 在卡片上看 · 1-3 句话",
                "minLength": 4,
                "maxLength": 400,
            },
            "litegraph_json": {
                "type": "object",
                "description": (
                    "LiteGraph.serialize() 出的图对象 · 含 nodes / links / last_node_id 等 · "
                    "OPUS 自己手写 JSON 也行 · 见上面格式说明"
                ),
            },
        },
        "required": ["name", "description", "litegraph_json"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
