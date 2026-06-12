"""agent_tools/create_workflow.py
================================

 K stage 2c · AI 给自己造一个 workflow

什么是 workflow:
    把多个 app + 原子工具串起来的 LiteGraph 流程
    用户 在出品工坊「工作流画布」点「加载已存工作流」就能拉出来跑

调用时机:
    - 用户 跟 AI 说「我想做 X · 你看怎么排工作流实现」
    - AI 设计完 → 直接 create_workflow 落档 · 用户 在画布里看到节点就能微调

跟 create_app 的区别:
    create_app           ← 独立原子模块 · 一个能力
    create_workflow      ← 把若干 app/工具按顺序连起来的图

tier:
    TIER_AUTO —— 只是落一个 json 文件 · 不动 .env / soul / 红线动作

数据格式:
    litegraph_json 必须是 LiteGraph.serialize() 的输出 ·
    最少有 {"nodes": [...], "links": [...], "last_node_id": N, "last_link_id": M}
    AI 自己手写时按下面 schema 出: 每个 node 至少 id/type/pos/properties
"""

from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    name = args.get("name") or "(未命名)"
    desc = (args.get("description") or "").strip()
    steps = args.get("steps")
    if isinstance(steps, list) and steps:
        parts = [f"造一个工作流 · 「{name}」 · {len(steps)} 个主步骤"]
    else:
        graph = args.get("litegraph_json") or {}
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        n_nodes = len(nodes) if isinstance(nodes, list) else 0
        parts = [f"造一个工作流 · 「{name}」 · {n_nodes} 个节点 (老画布格式)"]
    if desc:
        parts.append(f"  - 干啥: {desc[:60]}")
    return " · ".join(parts)


def _run(args: dict) -> ToolResult:
    from workers.workshop_assets import save_flow

    steps = args.get("steps")
    graph = args.get("litegraph_json")
    # 允许 AI 输入字符串 (JSON 文本) · 自动 parse
    import json as _json
    if isinstance(steps, str):
        try:
            steps = _json.loads(steps)
        except Exception as e:
            return ToolResult(ok=False, output="", error=f"steps 不是合法 JSON: {e}")
    if isinstance(graph, str):
        try:
            graph = _json.loads(graph)
        except Exception as e:
            return ToolResult(ok=False, output="", error=f"litegraph_json 不是合法 JSON: {e}")

    if not steps and not isinstance(graph, dict):
        return ToolResult(
            ok=False, output="",
            error="必须提供 steps (推荐·线性步骤清单) 或 litegraph_json (老画布格式)",
        )

    try:
        flow = save_flow({
            "name": args.get("name") or "",
            "description": args.get("description") or "",
            "steps": steps or [],
            "litegraph_json": graph if isinstance(graph, dict) else None,
            "created_by": "AI",
        })
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"save_flow 失败: {e}")

    lines = [
        f"# ✓ 工作流已造 · `{flow['id']}`",
        f"  - 名字: {flow['name']}",
        f"  - 简介: {flow['description']}",
    ]
    if flow.get("steps"):
        from workers.flow_steps import format_steps
        lines.append(f"  - 格式: steps ({len(flow['steps'])} 个主步骤 · 画布视图已自动投影)")
        lines.append("")
        lines.append(format_steps(flow["steps"]))
        lines.append("")
        lines.append(f"→ 用户 认了就 `run_flow(action=start, flow_id={flow['id']})` 沿轨道跑 · 状态落盘可断点续跑。")
    else:
        lines.append(f"  - 格式: litegraph (老画布) · 节点数: {flow.get('node_count', 0)}")
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
        "  3. 哪怕节点功能还没跑通 · 流程图先在 · 用户 至少有一份『AI 帮我排好的图』可看\n\n"
        "  跟 create_app 同理 — 不要把『落档』推到最后 · 推到最后碰上 typo / timeout 就丢图\n\n"
        "**什么时候调**:\n"
        "  - 用户 说「我想做 X · 你看怎么排工作流实现」时 · 第一刀\n"
        "  - AI 设计完一条多步骤管线 · create_workflow 落档让 用户 看图\n"
        "  - 缺工具就先 create_app 把工具落档 · 再来 create_workflow 用上它\n\n"
        "**🟢 推荐格式 · steps 线性步骤清单 (沉淀闭环 v2 刀② · 2026-06-10 用户 拍板)**:\n"
        "  flow 本体 = `[{app, goal, substeps?, on_fail?}]` 这种线性 list · 画布视图由 steps 自动投影。\n"
        "  执行器是 `run_flow` (workers/flow_runner) · 状态全程落盘 data/workshop/runs/<run_id>.json ·\n"
        "  支持断点续跑 (某步挂了改完对应 app · resume from_step=N · 不用整条重来)。\n\n"
        "  steps 字段:\n"
        "  - `app` (必填) app-id 精确引用 (推荐) 或 app 名字 (唯一命中才行)\n"
        "  - `goal` (必填) 这一步要达成什么 · 会作为 step_goal 传给 app · 像导演给演员的剧本\n"
        "  - `substeps` (可选) list[str] 站内清单 · 比如分镜稿可以列『1-1 图片收集 · 1-2 图片生成 · 1-3 标题』·\n"
        "     作用是进度可见 + 站内断点 · 子步骤常常运行时由蓝图动态展开 · 模板里能写多确定就写多确定\n"
        "  - `on_fail` (可选) `stop` (默认) 或 `goto:N` 回跳第 N 步 · 字段留着 · runner 当前只 stop\n\n"
        "  示例 (做条带 IP 的科普视频):\n"
        "  ```json\n"
        '  [\n'
        '    {"app": "app-66ac4190", "goal": "出导演蓝图: 800-1500 字口播文案 + 分镜表 + IP 槽位",\n'
        '     "substeps": ["1-1 选题敲死", "1-2 文案口播", "1-3 分镜表", "1-4 IP 槽位标注"]},\n'
        '    {"app": "app-b08ffda6", "goal": "按分镜表收/生图", "substeps": ["2-1 图片收集", "2-2 图片生成", "2-3 过渡页"]},\n'
        '    {"app": "app-6f439831", "goal": "用 active voice 配音 (TTS)"},\n'
        '    {"app": "app-render", "goal": "FFmpeg 合成"}\n'
        '  ]\n'
        "  ```\n\n"
        "**老 litegraph_json 格式 · 仅在 用户 明确要用画布版才用**:\n"
        "  工坊里 workflow 的节点都是 **app 节点** · type 必须是 `opus/app/<aid>`\n"
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
        "  ```\n\n"
        "**红线**:\n"
        "  - steps 里的 app 必须先存在 (load_app(<aid>) 能拿到) · 缺工具就先 create_app 把它落档再 create_workflow\n"
        "  - 老 litegraph 走 workers/workflow_engine.py · 节点 type 只能是 `opus/app/<aid>` (用其他会被拒)\n"
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
            "steps": {
                "type": "array",
                "description": (
                    "**推荐** · 线性步骤清单 (沉淀闭环 v2 刀②本体格式) · 画布视图由这个自动投影 · "
                    "run_flow 沿这个执行带状态落盘"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "app": {"type": "string", "description": "app-xxxxxxxx (推荐) 或 app 名字 (唯一命中)"},
                        "goal": {"type": "string", "description": "这一步要达成什么 · 像导演给演员的一句话剧本"},
                        "substeps": {"type": "array", "items": {"type": "string"}, "description": "站内清单 · 进度可见用"},
                        "on_fail": {"type": "string", "description": "stop (默认) 或 goto:N"},
                    },
                    "required": ["app", "goal"],
                },
            },
            "litegraph_json": {
                "type": "object",
                "description": (
                    "**老画布格式 · 仅 用户 明确要画布版才传** · 否则用 steps · "
                    "LiteGraph.serialize() 出的图对象 · 含 nodes / links / last_node_id 等"
                ),
            },
        },
        "required": ["name", "description"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
