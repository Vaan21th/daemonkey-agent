"""agent_tools/create_app.py
============================

卷四十四 K stage 2c · Daemonkey 给自己造一个 app 模块

什么是 app:
    一个独立子能力的封装 · 给自己挂一个名字 + 描述 + 系统提示词 + 工具白名单 + 模型提示
    BRO 在出品工坊「应用」tab 看到一个个卡片 · 点开 → 配置 → 运行

调用时机:
    - BRO 在主对话区跟 Daemonkey 说「建一个文字转语音的应用」/「再做个 X 应用」
    - Daemonkey 自己识别到画工作流时缺一个 app · 顺手 create_app 一个

跟 create_workflow 的区别:
    create_app          ← 独立模块 · 一个原子能力
    create_workflow     ← 把多个 app/工具串起来的 LiteGraph 流程

tier:
    TIER_AUTO —— 只是落一个 json 文件 · 不执行代码 · 不动 .env / soul / 红线
    BRO 之后在工坊里点「保存」/「删除」可控 · 完全是声明式资产
"""

from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    name = args.get("name") or "(未命名)"
    desc = (args.get("description") or "").strip()
    icon = args.get("icon") or "🧩"
    tools = args.get("tools") or []
    parts = [f"造一个新 app · {icon} 「{name}」"]
    if desc:
        parts.append(f"  - 用途: {desc[:60]}")
    if tools:
        parts.append(f"  - 工具白名单: {', '.join(tools[:6])}")
    return " · ".join(parts)


def _run(args: dict) -> ToolResult:
    from workers.workshop_assets import save_app
    import re

    # 卷四十四 K stage 2c++ · wish-96ee1b52 · 铁律 7 防御
    # 拒绝在 system_prompt / description 里出现 KEY-like 字符串 · 教 Daemonkey 改用 placeholder
    # 阈值: 16+ chars 连续字母+数字 (sk-fake-DEADBEEF 21 chars · 真 sk-xxx 通常 32-64)
    danger_patterns = [
        # OpenAI/Anthropic/DeepSeek 风格 sk-xxx KEY
        (r"\bsk-[A-Za-z0-9_\-]{16,}\b", "OpenAI/Anthropic 风格 KEY (sk-xxx)"),
        # AWS Access Key
        (r"\b(AKIA|ASIA)[A-Z0-9]{16}\b", "AWS Access Key"),
        # Bearer token (长字符串才算)
        (r"\bBearer\s+[A-Za-z0-9_\-\.]{32,}\b", "Bearer token"),
        # 通用 32+ hex (token)
        (r"\b[a-f0-9]{32,}\b", "32+ char hex token"),
    ]

    def _scan(text: str, field: str) -> str | None:
        if not text:
            return None
        for pat, kind in danger_patterns:
            if re.search(pat, text):
                return f"{field} 里出现疑似 {kind} · 请改用 ${{secret:<app_id>:<name>}} placeholder · 真值走 app_set_secret 落 secrets/"
        return None

    for field_name in ("system_prompt", "description"):
        msg = _scan(args.get(field_name) or "", field_name)
        if msg:
            return ToolResult(
                ok=False,
                output="",
                error=(
                    f"🔴 铁律 7 拒绝 · {msg}\n\n"
                    "正确流程:\n"
                    "  1. create_app(无 KEY · 用 placeholder 写 system_prompt)\n"
                    "  2. app_set_secret(app_id, 'api_key', '<真值>')\n"
                    "  3. 后续 shell_exec 用 ${secret:<app_id>:api_key} 引用"
                ),
            )

    try:
        app = save_app({
            "name": args.get("name") or "",
            "description": args.get("description") or "",
            "icon": args.get("icon") or "",
            "system_prompt": args.get("system_prompt") or "",
            "tools": args.get("tools") or [],
            "model_hint": args.get("model_hint") or "",
            "ui_form_schema": args.get("ui_form_schema") or [],
            "output_schema": args.get("output_schema") or [],
            "exec_kind": args.get("exec_kind") or "agentic",
            "exec_template": args.get("exec_template"),
            "asset_slots": args.get("asset_slots") or [],
            "created_by": "Daemonkey",
        })
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"save_app 失败: {e}")

    lines = [
        f"# ✓ 应用已造 · `{app['id']}`",
        f"  - 名字: {app['icon']} {app['name']}",
        f"  - 简介: {app['description']}",
    ]
    if app["system_prompt"]:
        first_line = app["system_prompt"].splitlines()[0]
        lines.append(f"  - 系统提示词: {first_line[:80]}…")
    if app["tools"]:
        lines.append(f"  - 工具白名单: {', '.join(app['tools'])}")
    if app["model_hint"]:
        lines.append(f"  - 推荐模型: {app['model_hint']}")
    if app["ui_form_schema"]:
        field_names = [f["name"] for f in app["ui_form_schema"]]
        lines.append(f"  - UI 表单字段: {', '.join(field_names)} ({len(field_names)} 项)")
    if app["output_schema"]:
        out_names = [f["name"] for f in app["output_schema"]]
        lines.append(f"  - 输出端口: {', '.join(out_names)} ({len(out_names)} 项 · 给工作流接下游用)")
    exec_kind = app.get("exec_kind") or "agentic"
    lines.append(f"  - 执行模式: {exec_kind}" + (" (0 LLM · 直接 HTTP)" if exec_kind == "scripted" else " (LLM session · 默认)"))
    if app.get("asset_slots"):
        slot_names = [s["name"] for s in app["asset_slots"]]
        lines.append(f"  - 资产槽: {', '.join(slot_names)} · 真值用 manage_app_asset(set) 登记")
    lines.append(f"  - 版本: v{app.get('version', 1)} · spec_version={app.get('spec_version', 1)}")
    for w in app.get("_warnings") or []:
        lines.append(f"  - ⚠ {w}")
    lines.append("")
    lines.append("→ BRO 去出品工坊 · 「应用」tab 能看到这张新卡片 · 点开可以编辑/调试。")
    if app["ui_form_schema"]:
        if exec_kind == "scripted":
            lines.append("→ 「测试」tab 已可用 · BRO 填表单 → 点『▶ 后端真跑』 → 直接 HTTP · 不烧 token。")
        else:
            lines.append("→ 「测试」tab 已可用 · BRO 填表单 → 拼成 prompt → 自动塞到主对话框。")
    if app["output_schema"]:
        lines.append("→ 工作流画布: 这个 app 是个节点 · 输出能接下游节点的输入端口。")
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="create_app",
    description=(
        "在出品工坊造一个新 app（独立子能力 · 一个 json 资产）。他说「建一个 X 应用 / 做一个 X 工具」时第一刀就调这个：先落档，再施工。六段标准、KEY 走 secret、ui_form、产物落点、反面教材 → 先 read_scenario(name='app_creation')。缺能力先 create_app，不要 python_exec 从零手搓。一次只造一个。真 KEY 不准写进任何字段。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "应用名字 · 一句话讲清是啥 · 比如 '文字转语音' / 'PR 周报生成器'",
                "minLength": 2,
                "maxLength": 80,
            },
            "description": {
                "type": "string",
                "description": "用途说明 · BRO 看卡片时一眼明白干嘛 · 1-3 句话",
                "minLength": 4,
                "maxLength": 400,
            },
            "icon": {
                "type": "string",
                "description": "单个 emoji · 卡片头像 · 比如 '🎙' / '📊' · 默认 🧩",
            },
            "system_prompt": {
                "type": "string",
                "description": (
                    "应用被调用时给底层 LLM 的角色 + 任务指令 · 写得越具体效果越好。"
                    "agentic app 必须含六段 markdown 标题: 角色/输入/动作/输出规范/坑清单"
                    "(+资产引用·有 asset_slots 时) · 缺段会被内核拒绝"
                ),
            },
            "asset_slots": {
                "type": "array",
                "description": (
                    "可选 · 声明这个 app 需要的用户个性资产槽 (配置页渲染依据)。"
                    "真值走 manage_app_asset 落 data/workshop/assets/<app_id>.json · 不写进 prompt。"
                    "例: [{name:'ip_images',type:'images',label:'IP 形象图'},"
                    "{name:'style_ref',type:'text',label:'画面风格参考'}]"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "槽名 · [a-zA-Z_][a-zA-Z0-9_]*"},
                        "type": {"type": "string", "enum": ["text", "json", "images", "file"]},
                        "label": {"type": "string", "description": "中文标签 · 给 BRO 看"},
                        "help": {"type": "string", "description": "提示文字"},
                    },
                    "required": ["name"],
                },
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "工具白名单 · 这个 app 允许调的 Daemonkey 工具名 · 比如 ['shell_exec', 'open_app'] · "
                    "留空表示允许所有工具"
                ),
            },
            "model_hint": {
                "type": "string",
                "description": "推荐底层模型 · 比如 'sonnet-4.5' · 留空表示用 BRO 当前默认模型",
            },
            "exec_kind": {
                "type": "string",
                "enum": ["agentic", "scripted"],
                "description": (
                    "执行模式 · 默认 'agentic' (向后兼容 phase B 行为)\n\n"
                    "**agentic** (默认 · LLM session 调度):\n"
                    "  - form 提交后走 LLM session · LLM 读 system_prompt · 调工具 (shell_exec / read_file 等) · 拿结果\n"
                    "  - 适合: '帮我整理周报' '分析竞品报告' '看图说话' '写代码改 bug' 这种需要智能决策的 app\n"
                    "  - 优点: 灵活 · 能处理边界情况 · 工具链丰富\n"
                    "  - 缺点: 慢 (LLM 思考 + 工具循环) · 贵 (每次烧 token · 即使只是参数转发)\n\n"
                    "**scripted** (0 LLM · 直接 HTTP 转发):\n"
                    "  - form 字段直接拼 HTTP 请求 · 不过 LLM · 后端拼好直接发 · 拿 response 提字段\n"
                    "  - 适合: GPT Image 2 / SOVITS / ElevenLabs / OpenAI Vision 这种纯 API 转发 app\n"
                    "  - 必填 exec_template · system_prompt 可空 (LLM 不会读)\n"
                    "  - 优点: 快 (秒级 vs 分钟级) · 省 ($0 vs $0.01-0.1) · 稳 (没 LLM 跑偏风险)\n"
                    "  - 缺点: 不能动态决策 · 输入格式固定 · 错误处理硬编码\n\n"
                    "**怎么选**:\n"
                    "  - app 主要功能是『按参数发请求拿结果』→ scripted\n"
                    "  - app 主要功能是『理解需求 + 多步执行』→ agentic\n"
                    "  - 混合场景 (LLM 拼参数 + 多次 API) → agentic · 但里面用 shell_exec 调 curl"
                ),
            },
            "exec_template": {
                "type": "object",
                "description": (
                    "**scripted app 必填** · agentic 不填 (写了也忽略)\n\n"
                    "HTTP 调用模板 · 故意做窄·避免变成 mini Jinja DSL:\n\n"
                    "```json\n"
                    "{\n"
                    '  "kind": "http",\n'
                    '  "routes": [\n'
                    '    {\n'
                    '      "when": "mode==edits",  // 简单等于匹配 · 不支持复杂表达式 · 或 \\"default\\" 兜底\n'
                    '      "method": "POST",\n'
                    '      "url": "https://aipg.work/v1/images/edits",  // 含 ${ui:field} ${secret:key} 插值\n'
                    '      "headers": {"Authorization": "Bearer ${secret:app-66ac4190:api_key}"},  // 铁律 7 推荐: ${secret:<app_id>:<name>} 三段式\n'
                    '      "body": {"prompt": "${ui:prompt}", "size": "${ui:size:1024x1024}"},\n'
                    '      "body_kind": "json",  // json / multipart_form / form_urlencoded / raw\n'
                    '      "timeout_sec": 300\n'
                    '    },\n'
                    '    {"when": "default", ...}  // 必须有一条 when=default 兜底\n'
                    '  ],\n'
                    '  "response": {\n'
                    '    "kind": "b64_save",  // json / text / binary_save / b64_save\n'
                    '    "extract": "data[0].b64_json",  // jq-like path (b64_save 必填)\n'
                    '    "save": {  // binary_save / b64_save 必填\n'
                    '      "dir": "data/workshop/outputs/${app_id}",\n'
                    '      "filename": "img-${ts}.png"\n'
                    '    },\n'
                    '    "mapping": {  // output_schema.name → 取值 path · __saved_path__ 特殊值\n'
                    '      "image_url": "__saved_path__",  // 保存后的相对 URL (前端会拼成 /workshop/outputs/...)\n'
                    '      "revised_prompt": "data[0].revised_prompt"\n'
                    '    }\n'
                    '  }\n'
                    "}\n"
                    "```\n\n"
                    "**插值语法 (只支持这些·没了)**:\n"
                    "  - ${ui:field}        · form 字段值\n"
                    "  - ${ui:field:default} · 字段缺失时用 default (default 是字面量·不递归)\n"
                    "  - ${secret:<app_id>:<name>} · 铁律 7 标准·走 workers.app_secrets 跟 shell_exec 同一存储\n"
                    "                                  daemon Daemonkey 先调 app_set_secret 落 KEY · 再用 placeholder 引用\n"
                    "  - ${secret:<name>}   · 单段简写·自动用 context.app_id (只能拿自己 app 的 secret · 不能跨 app)\n"
                    "  - ${upstream:node_id:port} · 工作流上游 node output (workflow_engine 用)\n"
                    "  - ${app_id} / ${ts} / ${ts_ms} · 自动注入\n\n"
                    "**multipart 上传文件**: body 字段值写 '@file:<path>' · 例 'image': '@file:${ui:input_path}'\n\n"
                    "**做不到的**:\n"
                    "  ❌ ${ui:a} + ${ui:b} (字符串拼接除外) ❌ 三元 ❌ 循环 ❌ 嵌套 \n"
                    "  需要这些 → 改用 exec_kind=agentic"
                ),
            },
            "output_schema": {
                "type": "array",
                "description": (
                    "可选 · 声明这个 app 的输出端口 · 给工作流编辑器把 app 当 node 时挂下游用 · "
                    "wish-165ea1f6 phase B 2026-05-26 上线。 不填默认 app 输出单个 'output' 字符串 "
                    "(LLM 最终回答全文 · 一般够用)。 填多端口时:\n\n"
                    "  - 比如图像生成 app: output_schema=[{name:'image_url',type:'string'},{name:'prompt_used',type:'string'}]\n"
                    "  - 比如 TTS app: output_schema=[{name:'audio_path',type:'file'},{name:'duration_sec',type:'number'}]\n\n"
                    "type 选项: string / number / boolean / array / object / file (输出形态比 input 多 array/object)。 "
                    "字段名要让下游节点能直观引用 · 不要叫 'data1','data2' 这种没语义的。 最多 10 个。"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "输出端口名 · [a-zA-Z_][a-zA-Z0-9_]*"},
                        "type": {
                            "type": "string",
                            "enum": ["string", "number", "boolean", "array", "object", "file"],
                        },
                        "label": {"type": "string", "description": "中文标签"},
                        "help": {"type": "string", "description": "提示文字"},
                    },
                    "required": ["name"],
                },
            },
            "ui_form_schema": {
                "type": "array",
                "description": (
                    "可选 · 声明这个 app 在工坊『测试』tab 显示的 UI 表单字段 · "
                    "BRO 重复跑同一 app 时不用每次打字。 详见上面 description 里的字段哲学 + 示例。 "
                    "字段名 (name) 必须是合法变量名 · 不能用保留字 (input/output/app/opus/now/today)。 "
                    "Phase A 阶段表单提交后 · 前端会把字段拼成自然语言 prompt 塞回主对话框 · "
                    "走 NLP First 路径 · 跟跟你正常说话调这个 app 完全等价。 "
                    "最多 20 个字段·复杂的输入应该走 NLP 而不是堆字段。"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "字段名 / 变量名 · [a-zA-Z_][a-zA-Z0-9_]* · 不能撞保留字",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["text", "textarea", "number", "select", "boolean", "file"],
                            "description": "字段类型 · text=单行文本 · textarea=多行 · select=下拉",
                        },
                        "label": {
                            "type": "string",
                            "description": "中文标签 · 给 BRO 看的人话 · 没填用 name",
                        },
                        "required": {
                            "type": "boolean",
                            "description": "是否必填 · 默认 false",
                        },
                        "default": {
                            "description": "默认值 · 类型跟 type 对应 · select 应填某个 option.value",
                        },
                        "help": {
                            "type": "string",
                            "description": "字段下方灰色提示文字 · 简短解释",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "仅 text/textarea · 字符上限",
                        },
                        "min": {
                            "type": "number",
                            "description": "仅 number · 下限",
                        },
                        "max": {
                            "type": "number",
                            "description": "仅 number · 上限",
                        },
                        "options": {
                            "type": "array",
                            "description": "仅 select · [{value, label}] 或纯字符串列表",
                        },
                        "accept": {
                            "type": "string",
                            "description": "仅 file · MIME 类型或后缀过滤 · 比如 'image/*' / '.wav'",
                        },
                    },
                    "required": ["name"],
                },
            },
        },
        "required": ["name", "description"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
