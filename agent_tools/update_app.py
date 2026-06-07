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
        "改一个已有 app 的字段 · 包括给老 app 补 ui_form_schema (UI 表单)\n\n"
        "**典型场景**:\n"
        "  - 用户 在工坊看到一张老卡片 · 跟你说『给它加个表单』\n"
        "  - 用户 跟你聊到一个 app 用得不顺手 · 想改 system_prompt / 加 tool / 换 model\n"
        "  - 你自己审视到一个 app 缺 ui_form_schema · 主动补\n\n"
        "**只传你要改的字段** · 没传的字段保留原值。\n"
        "**特殊情形**:\n"
        "  - `ui_form_schema: []` 显式清空表单 · 这个 app 回归纯 NLP 触发\n"
        "  - 改 name/description 等于换卡片『名片』· 谨慎\n\n"
        "**ui_form_schema 字段哲学** · 跟 create_app 完全一样:\n"
        "  - 每个元素是 {name, type, label, required, default, help, ...} 的 dict\n"
        "  - type: text / textarea / number / select / boolean / file\n"
        "  - name 必须是合法变量名 · 不能撞保留字 (input/output/app/opus/now/today)\n"
        "  - select 必须有 options\n"
        "  - 最多 20 个字段\n\n"
        "**重命名注意**: 把 name 改成完全不同的语义等于偷换卡片 · 建议新造 + 软删老的。"
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
                "description": (
                    "新 output schema · 不传保留原值 · 传 [] 清空 · phase B 工作流给 LiteGraph "
                    "output ports 用。 不填默认单 'output' string 端口。 type 选 string/number/boolean/"
                    "array/object/file。 详见 create_app 同字段说明。"
                ),
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
                "description": (
                    "改执行模式 · agentic (LLM session) 或 scripted (0 LLM 直接 HTTP)。 "
                    "改成 scripted 时必须同时传 exec_template · 不然 daemon save 时拒绝。 "
                    "改成 agentic 时 exec_template 可以保留但不会用 · 想清空就传 exec_template={} "
                    "详见 create_app 同字段说明。"
                ),
            },
            "exec_template": {
                "type": "object",
                "description": (
                    "改 HTTP 模板 · 仅 scripted app 用 · 传 {} 清空。 "
                    "schema: {kind:'http', routes:[{when,method,url,headers,body,body_kind,timeout_sec}], "
                    "response:{kind,extract,save,mapping}}。 "
                    "插值: ${ui:field} / ${ui:field:default} / ${secret:k} / ${upstream:nid:port} / "
                    "${app_id} / ${ts}。 详见 create_app 同字段说明。"
                ),
            },
        },
        "required": ["app_id"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
