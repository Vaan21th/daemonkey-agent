"""agent_tools/create_app.py
============================

 K stage 2c · OPUS 给自己造一个 app 模块

什么是 app:
    一个独立子能力的封装 · 给自己挂一个名字 + 描述 + 系统提示词 + 工具白名单 + 模型提示
    用户 在出品工坊「应用」tab 看到一个个卡片 · 点开 → 配置 → 运行

调用时机:
    - 用户 在主对话区跟 OPUS 说「建一个文字转语音的应用」/「再做个 X 应用」
    - OPUS 自己识别到画工作流时缺一个 app · 顺手 create_app 一个

跟 create_workflow 的区别:
    create_app          ← 独立模块 · 一个原子能力
    create_workflow     ← 把多个 app/工具串起来的 LiteGraph 流程

tier:
    TIER_AUTO —— 只是落一个 json 文件 · 不执行代码 · 不动 .env / soul / 红线
    用户 之后在工坊里点「保存」/「删除」可控 · 完全是声明式资产
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

    #  K stage 2c++ · wish-96ee1b52 · 铁律 7 防御
    # 拒绝在 system_prompt / description 里出现 KEY-like 字符串 · 教 OPUS 改用 placeholder
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
            "created_by": "OPUS",
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
    lines.append("")
    lines.append("→ 用户 去出品工坊 · 「应用」tab 能看到这张新卡片 · 点开可以编辑/调试。")
    if app["ui_form_schema"]:
        if exec_kind == "scripted":
            lines.append("→ 「测试」tab 已可用 · 用户 填表单 → 点『▶ 后端真跑』 → 直接 HTTP · 不烧 token。")
        else:
            lines.append("→ 「测试」tab 已可用 · 用户 填表单 → 拼成 prompt → 自动塞到主对话框。")
    if app["output_schema"]:
        lines.append("→ 工作流画布: 这个 app 是个节点 · 输出能接下游节点的输入端口。")
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="create_app",
    description=(
        "在出品工坊里造一个新 app · 独立子能力模块·一个 json 资产\n\n"
        "**🔴 关键调用次序 · 用户 说『建一个 X 应用』时第一刀就是这个工具**:\n"
        "  1. **先 create_app 落档 (签合同)** · 把 name + description + 推荐工具白名单\n"
        "     落到 data/workshop/apps/<id>.json · 用户 在工坊立刻看见卡片 ·  K stage 2c\n"
        "  2. 第二刀再去做实际事 (找资源 / 启服务 / 试调用 / 看 api 文档)\n"
        "  3. 即便环境没装好 / 服务没启起来 / 网络抽风 · app json 已落 · 用户 至少有一张\n"
        "     『我跟 OPUS 一起开了头』的卡片留下来 · **不会两手空空**\n\n"
        "  ❌ 反面教材 ( K stage 2c · GPT-SoVITS 实测): OPUS 花 17 分钟\n"
        "     全盘搜资源 → 看 api.py → 启服务 → 验 CUDA · 一个 typo 翻车整 turn 中断 ·\n"
        "     create_app 一次都没调 · 用户 F5 工坊还是空 · 17 分钟功夫一张卡片都没留\n"
        "  ✅ 正确流程: 检索完局部资源 (~3 分钟) 一确认有 → 立刻 create_app 落档 →\n"
        "     再去启服务 / 试调用 · 后续即便翻车 · 卡片在 · 用户 可在工坊看到这个 app\n\n"
        "**什么时候调**:\n"
        "  - 用户 说「建一个 X 应用」「做一个 X 工具」「再加个 Y app」时 · 第一刀\n"
        "  - OPUS 自己排工作流时发现缺一个原子能力·先 create_app 再 create_workflow\n"
        "  - 用户 在外面看到一个第三方 API (比如 ElevenLabs / OpenAI Vision) · 提供 KEY + 文档 ·\n"
        "    OPUS 把它封装成 app · system_prompt 写调用规约 · tools=['web_fetch', 'shell_exec']\n\n"
        "**字段哲学**:\n"
        "  - description 写给人看 · 一句话讲清这个 app 干嘛 (用户 在工坊卡片上看)\n"
        "  - system_prompt 写给将来调用这个 app 的 LLM 看 · 角色设定 + 风格约束 +\n"
        "    具体 endpoint/路径/key 占位符 (用 ${API_KEY} / ${SERVICE_PATH} 这种)\n"
        "  - tools 是这个 app 允许调的工具白名单 · 比如 ['shell_exec', 'open_app']\n"
        "    → 不写 = 默认能用所有 OPUS 工具 · 但建议白名单收紧 (Coze 五槽里的『技能』)\n"
        "  - model_hint 是推荐模型 · 比如 'sonnet-4.5' / 'deepseek-v4-pro' · 留空也行\n\n"
        "**红线**:\n"
        "  - 不要在 system_prompt 里写让 LLM 改 .env / soul / 红线动作的指令\n"
        "  - **🔴 铁律 7 · 严禁把 用户 的真 API KEY 写进 app json 任何字段** · 包括 description /\n"
        "    system_prompt / 自定义字段 / 自创 'config' 字段。 KEY 必须走 `app_set_secret` 落\n"
        "    `data/workshop/secrets/`·system_prompt 里只用 placeholder `${secret:<app_id>:<name>}`\n"
        "    引用·daemon 在 shell_exec 启动子进程时自动 resolve\n"
        "  - 装 API 应用的标准三步: create_app → app_set_secret → 用 placeholder 写 system_prompt\n"
        "  - 一次只造一个 app · 别一次塞多个\n\n"
        "**产物落点规范** ( K · 6.1):\n"
        "  - 生成媒体落 `data/workshop/outputs/<app_id>/<filename>` (按 app_id 分桶不串扰)\n"
        "  - 给 用户 看就在最终回答里写 markdown: `![alt](/workshop/outputs/<app_id>/x.png)`\n"
        "  - chat.js 把 `![](...)` 自动转 <img> · .wav 转 <audio> · .mp4 转 <video>·用户 直接看\n"
        "  - 不要用 HTML `<img>` 标签 (会被 escape) · 不要写 windows 绝对路径 (file:// 浏览器拒)\n\n"
        "**UI 表单字段 `ui_form_schema`** (wish-165ea1f6 · 2026-05-26 上线):\n"
        "  写出来 → 工坊「测试」tab 自动渲染表单 · 用户 不用每次打字 prompt · 重复跑同一 app 巨爽。\n"
        "  Phase A 落地路径 (NLP First): 用户 填完表单 → 前端把字段拼成自然语言 prompt → 塞主对话框 →\n"
        "  OPUS 接到后按 system_prompt 处理 · 跟正常对话一样。 没有黑魔法 · 只是省了打字。\n\n"
        "  **什么时候该写 ui_form_schema**:\n"
        "    ✅ 应用的输入参数稳定 · 字段固定 (SOVITS = 文字+情绪 · GPT-Image = 描述+尺寸)\n"
        "    ✅ 用户 会重复用 · 5 次以上 / 周\n"
        "    ❌ 应用是开放对话型 (聊天 / 头脑风暴) · 写了反而约束创造力\n\n"
        "  **示例 · SOVITS 文字转语音**:\n"
        "    ui_form_schema: [\n"
        "      {name: 'text',    type: 'textarea', label: '要合成的文字', required: true, max_chars: 35},\n"
        "      {name: 'emotion', type: 'select',   label: '情绪', options: ['平静','开心','悲伤','愤怒']},\n"
        "      {name: 'speed',   type: 'number',   label: '语速', default: 1.0, min: 0.5, max: 2.0}\n"
        "    ]\n\n"
        "  **字段命名规范**: name 必须是 [a-zA-Z_][a-zA-Z0-9_]* · 不能用保留字\n"
        "  (input/output/app/opus/now/today) · 字段名重复会被拒。\n\n"
        "  **system_prompt 引用 form 输入**: 写「用户 通过表单提供了以下输入: ...」让 LLM 知道字段对应关系。\n"
        "  Phase A 不做 ${ui:<name>} 模板插值 (那是 phase B 工作流引擎的活)·这里只是声明 UI。"
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
                "description": "用途说明 · 用户 看卡片时一眼明白干嘛 · 1-3 句话",
                "minLength": 4,
                "maxLength": 400,
            },
            "icon": {
                "type": "string",
                "description": "单个 emoji · 卡片头像 · 比如 '🎙' / '📊' · 默认 🧩",
            },
            "system_prompt": {
                "type": "string",
                "description": "应用被调用时给底层 LLM 的角色 + 任务指令 · 写得越具体效果越好",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "工具白名单 · 这个 app 允许调的 OPUS 工具名 · 比如 ['shell_exec', 'open_app'] · "
                    "留空表示允许所有工具"
                ),
            },
            "model_hint": {
                "type": "string",
                "description": "推荐底层模型 · 比如 'sonnet-4.5' · 留空表示用 用户 当前默认模型",
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
                    "                                  daemon OPUS 先调 app_set_secret 落 KEY · 再用 placeholder 引用\n"
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
                    "用户 重复跑同一 app 时不用每次打字。 详见上面 description 里的字段哲学 + 示例。 "
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
                            "description": "中文标签 · 给 用户 看的人话 · 没填用 name",
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
