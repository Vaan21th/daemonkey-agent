"""agent_tools/create_workflow.py
================================

卷四十四 K stage 2c · Daemonkey 给自己造一个 workflow

什么是 workflow:
    把多个 app + 原子工具串起来的 LiteGraph 流程
    BRO 在出品工坊「工作流画布」点「加载已存工作流」就能拉出来跑

调用时机:
    - BRO 跟 Daemonkey 说「我想做 X · 你看怎么排工作流实现」
    - Daemonkey 设计完 → 直接 create_workflow 落档 · BRO 在画布里看到节点就能微调

跟 create_app 的区别:
    create_app           ← 独立原子模块 · 一个能力
    create_workflow      ← 把若干 app/工具按顺序连起来的图

tier:
    TIER_AUTO —— 只是落一个 json 文件 · 不动 .env / soul / 红线动作

数据格式:
    litegraph_json 必须是 LiteGraph.serialize() 的输出 ·
    最少有 {"nodes": [...], "links": [...], "last_node_id": N, "last_link_id": M}
    Daemonkey 自己手写时按下面 schema 出: 每个 node 至少 id/type/pos/properties
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
    # 允许 Daemonkey 输入字符串 (JSON 文本) · 自动 parse
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
            "created_by": "Daemonkey",
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
        lines.append(f"→ BRO 认了就 `run_flow(action=start, flow_id={flow['id']})` 沿轨道跑 · 状态落盘可断点续跑。")
    else:
        lines.append(f"  - 格式: litegraph (老画布) · 节点数: {flow.get('node_count', 0)}")
        lines.append("")
        lines.append("→ BRO 去出品工坊 · 「工作流画布」tab · 「加载工作流」能看到这条新流程。")
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="create_workflow",
    description=(
        "在出品工坊造一个 workflow，把多个 app 串成可跑的流程。他说「排个工作流」时第一刀：先落档，再调节点。推荐 steps 线性清单；互不依赖的取材可写成 parallel 组（默认仍串行）。steps 字段、并行纪律、litegraph 老格式 → read_scenario(name='app_creation')。缺 app 先 create_app。steps 里的 app 必须已存在。"
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
                "description": "工作流用途 · BRO 在卡片上看 · 1-3 句话",
                "minLength": 4,
                "maxLength": 400,
            },
            "steps": {
                "type": "array",
                "description": (
                    "**推荐** · 线性步骤清单 (沉淀闭环 v2 刀②本体格式) · 画布视图由这个自动投影 · "
                    "run_flow 沿这个执行带状态落盘。 每一步要么是【单 app 步】(给 app + goal) · "
                    "要么是【并行组步】(给 parallel 数组 · 组内 2~4 个分支并发跑 · app 和 parallel 二选一)。"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "app": {"type": "string", "description": "单 app 步: app-xxxxxxxx (推荐) 或 app 名字 (唯一命中) · 与 parallel 二选一"},
                        "goal": {"type": "string", "description": "单 app 步必填: 这一步要达成什么 · 像导演给演员的一句话剧本。 并行组步这里可选 · 写组级说明"},
                        "substeps": {"type": "array", "items": {"type": "string"}, "description": "站内清单 · 进度可见用"},
                        "parallel": {
                            "type": "array",
                            "description": "并行组步: 2~4 个分支 · 组内并发跑 · 各拿同一份上游 · 跑完合并喂下一步。 与 app 二选一。 同一 app 可出现多次 (同 app 并行不同输入)",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "app": {"type": "string", "description": "这个分支跑哪个 app · app-xxxxxxxx 或名字"},
                                    "goal": {"type": "string", "description": "这个分支要达成什么"},
                                    "substeps": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": ["app", "goal"],
                            },
                        },
                        "on_fail": {"type": "string", "description": "stop (默认) 或 goto:N"},
                    },
                },
            },
            "litegraph_json": {
                "type": "object",
                "description": (
                    "**老画布格式 · 仅 BRO 明确要画布版才传** · 否则用 steps · "
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
