"""agent_tools/update_app.py
============================

续 12 · wish-165ea1f6 phase A · 改已有 app 的任意字段

什么时候调:
    - 用户 在工坊看到一张已有卡片 · 跟 OPUS 说「给这个 app 加一个表单」
    - 用户 说「把 SOVITS app 的 model_hint 改成 gpt-sovits-v2」
    - OPUS 自己审视一张老 app 时发现缺 ui_form_schema · 补一发
    - 不要用来「重命名 app」 — name/description 改了卡片就换味道了 · 建议新造 app

tier:
    TIER_CONFIRM —— 改 app 等于改了一个 用户 可见资产 · 用户 应该明确点确认
    跟 create_app (TIER_AUTO) 不同 · 因为 create 是新增 · update 是覆盖

字段语义:
    - app_id (必填) · app-<8hex>
    - 其余字段都是可选 · 不传就保留原值
    - ui_form_schema 传 [] 等于「清空 form」 · 传 null 不动 (但 JSON 里没法传 null 区分 missing/null·
      所以 tool 设计上 None == 不动 · [] == 清空)

实现:
    load_app + dict spread (新值覆盖老值) + save_app · save_app 自带 validation
"""

from __future__ import annotations

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    aid = args.get("app_id") or "(missing)"
    changed = [k for k in (
        "name", "description", "icon", "system_prompt",
        "tools", "model_hint", "ui_form_schema",
        "output_schema", "exec_kind", "exec_template",
    ) if k in args and args[k] is not None]
    if not changed:
        return f"改 app · {aid} · (没指定要改的字段?)"
    return f"改 app · {aid} · 字段: {', '.join(changed)}"


def _run(args: dict) -> ToolResult:
    from ._hotpath_guard import require_scenario
    blocked = require_scenario("app_creation")
    if blocked:
        return ToolResult(ok=False, output="", error=blocked)

    from workers.workshop_assets import load_app, save_app

    aid = (args.get("app_id") or "").strip()
    if not aid:
        return ToolResult(ok=False, output="", error="app_id 必填")
    if not aid.startswith("app-"):
        return ToolResult(
            ok=False, output="",
            error=f"app_id 必须以 'app-' 开头 · 收到: {aid}",
        )

    existing = load_app(aid)
    if existing is None:
        return ToolResult(
            ok=False, output="",
            error=f"app {aid} 不存在 · 回收站里的也算不存在 · 先 restore 再 update",
        )

    spec = dict(existing)
    changes: list[str] = []

    for field in ("name", "description", "icon", "system_prompt", "model_hint"):
        if field in args and args[field] is not None:
            new_val = str(args[field]).strip()
            if new_val != (existing.get(field) or ""):
                spec[field] = new_val
                changes.append(field)

    if "tools" in args and args["tools"] is not None:
        new_tools = args["tools"]
        if not isinstance(new_tools, list):
            return ToolResult(
                ok=False, output="",
                error="tools 必须是 list[str]",
            )
        cleaned = [str(t).strip() for t in new_tools if str(t).strip()]
        if cleaned != list(existing.get("tools") or []):
            spec["tools"] = cleaned
            changes.append("tools")

    if "ui_form_schema" in args and args["ui_form_schema"] is not None:
        new_schema = args["ui_form_schema"]
        if not isinstance(new_schema, list):
            return ToolResult(
                ok=False, output="",
                error="ui_form_schema 必须是 list (或 [] 清空)",
            )
        spec["ui_form_schema"] = new_schema
        changes.append("ui_form_schema")

    if "output_schema" in args and args["output_schema"] is not None:
        new_out = args["output_schema"]
        if not isinstance(new_out, list):
            return ToolResult(
                ok=False, output="",
                error="output_schema 必须是 list (或 [] 清空)",
            )
        spec["output_schema"] = new_out
        changes.append("output_schema")

    if "exec_kind" in args and args["exec_kind"] is not None:
        new_kind = str(args["exec_kind"]).strip().lower()
        if new_kind not in {"agentic", "scripted"}:
            return ToolResult(
                ok=False, output="",
                error=f"exec_kind 必须是 'agentic' 或 'scripted' · 收到: {new_kind}",
            )
        if new_kind != (existing.get("exec_kind") or "agentic"):
            spec["exec_kind"] = new_kind
            changes.append("exec_kind")

    if "exec_template" in args and args["exec_template"] is not None:
        new_tpl = args["exec_template"]
        if new_tpl == {}:
            spec["exec_template"] = None
            changes.append("exec_template (清空)")
        elif not isinstance(new_tpl, dict):
            return ToolResult(
                ok=False, output="",
                error="exec_template 必须是 dict (或 {} 清空)",
            )
        else:
            spec["exec_template"] = new_tpl
            changes.append("exec_template")

    if not changes:
        return ToolResult(
            ok=True,
            output=(
                f"# (无变更) `{aid}`\n"
                "  - 你传的字段值跟现有完全一致 · 没改任何东西。\n"
                "  - 如果想清空 ui_form_schema · 显式传 `ui_form_schema: []`"
            ),
        )

    spec["id"] = aid
    spec["created_at"] = existing.get("created_at") or ""

    try:
        updated = save_app(spec)
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"save_app 失败: {e}")

    lines = [
        f"# ✓ 应用已更新 · `{updated['id']}`",
        f"  - 名字: {updated['icon']} {updated['name']}",
        f"  - 改了字段: {', '.join(changes)}",
    ]
    if "ui_form_schema" in changes:
        form = updated.get("ui_form_schema") or []
        if form:
            names = [f["name"] for f in form]
            lines.append(f"  - UI 表单: {', '.join(names)} ({len(names)} 项)")
            lines.append("  - 「测试」tab 即可填表单调这个 app")
        else:
            lines.append("  - UI 表单已清空")
    lines.append("")
    lines.append("→ 用户 去工坊 · 这张卡片现在是最新版。")
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="update_app",
    description=(
        "改已有工坊 app 的字段（只传要改的）。每次应带 change_note。六段标准见 read_scenario('app_creation')。ui_form_schema:[] 清空表单。改 name 等于换名片，谨慎。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "app_id": {
                "type": "string",
                "description": "目标 app 的 id · 必须以 'app-' 开头",
            },
            "name": {
                "type": "string",
                "description": "新名字 · 不传保留原值",
            },
            "description": {
                "type": "string",
                "description": "新简介 · 不传保留原值",
            },
            "icon": {
                "type": "string",
                "description": "新图标 emoji · 不传保留原值",
            },
            "system_prompt": {
                "type": "string",
                "description": "新系统提示词 · 不传保留原值",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "新工具白名单 · 不传保留 · 传 [] 等于清空白名单 (允许所有工具)",
            },
            "model_hint": {
                "type": "string",
                "description": "新推荐模型 · 不传保留原值",
            },
            "ui_form_schema": {
                "type": "array",
                "description": (
                    "新 UI 表单 schema · 不传保留原值 · 传 [] 清空。 "
                    "每个元素 {name, type, label, required, default, help, max_chars, "
                    "min, max, options, accept}"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": [
                                "text", "textarea", "number",
                                "select", "boolean", "file",
                            ],
                        },
                        "label": {"type": "string"},
                        "required": {"type": "boolean"},
                        "help": {"type": "string"},
                    },
                    "required": ["name"],
                },
            },
            "output_schema": {
                "type": "array",
                "description": "新输出端口。不传保留，[] 清空。形状见 read_scenario('app_creation')。",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["string", "number", "boolean", "array", "object", "file"],
                        },
                        "label": {"type": "string"},
                        "help": {"type": "string"},
                    },
                    "required": ["name"],
                },
            },
            "exec_kind": {
                "type": "string",
                "enum": ["agentic", "scripted"],
                "description": "改执行模式。改 scripted 必须同传 exec_template。怎么选 → read_scenario('app_creation')。",
            },
            "exec_template": {
                "type": "object",
                "description": "改 HTTP 模板。仅 scripted；{} 清空。形状见 read_scenario('app_creation')。",
            },
        },
        "required": ["app_id"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
