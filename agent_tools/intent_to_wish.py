"""
agent_tools/intent_to_wish.py
=============================

 G · wish-2dcf2b48 · 意图守护 · 模糊需求 → wish_add 草稿

为什么有这个工具
----------------
用户 跟 OPUS 聊天经常说『改一下 X 吧』『加个 Y』『我想要 Z』 — 模糊请求。
OPUS 现在的反应模式是**直接动手 write_file** · 跳过 wish 流程 · 没分支隔离 ·
没 用户 review · 结果就是 D + E 的反面教材 (d1d279c / 8e4389a)。

根因不是 OPUS 偷懒·是模糊请求跟 wish 工具的形式不匹配 — OPUS 缺一个
"先把模糊请求结构化"的中间层。

调用路径
--------
  用户 模糊请求 → OPUS 调 intent_to_wish → 拿到 wish 草稿 → review → 调 wish_add 落档 (status=pending)
                                                          ↓
                                          用户 在 UI 批准 → OPUS 勘察出方案 (daemon_phase=plan_pending)
                                                          ↓
                              用户 批方案 → 清 daemon_phase 自动开分支改代码 → status=review → 验收 live 自动 merge

调用时机
--------
- 听到『改一下』『加个』『我想要 X』 + 没指定具体文件
- 用户 描述一个能力但没拆细
- 你不确定这是不是值得开 wish · 让工具帮你判断
- 用户 直接说『来 wish 一下 X』

不调用的时机
------------
- 用户 给了完整的"在 X 文件里改 Y"明确指令 → 直接 write_file
- 用户 让你只看不改 (read_file / grep / 回答问题)
- 已经在 wish-XXX 分支上继续改原 wish 的事
"""

from __future__ import annotations

import json
import re
from typing import Optional

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


_SYSTEM_PROMPT = """你是 Daemonkey 工程的「心愿单结构化助手」。
输入是 用户 的模糊请求 (大白话)·输出是符合 wish_add schema 的草稿 JSON。

【目标】把 用户 的请求转成 6 个字段 + 1 个 rationale。

【字段规范】
  title         · 一句话讲清要做啥 · ≤ 50 字 · 描述目标·不要命令式 (好"信源直方图加折叠按钮·让 用户 看雷达不被高条干扰" / 差"加折叠按钮")
  why           · 至少 2 句 · 第 1 句"为什么这事值得做" + 第 2 句"不做会怎样" · 必须扣 用户 痛点·不许"OPUS 想要"
  design_sketch · 拆 1-3 步 markdown · 每步写"改哪个文件 + 改什么逻辑"·不知道文件就写 "TBD · 需要先 grep 确认"
  complexity    · "low" / "medium" / "high" (≤2h / 2-8h / >8h)
  estimated_hours · 数字 · 1-12
  priority      · 整数 1-5 (5=非常急·1=可有可无)
  rationale     · 给 OPUS 看的元解释 · "我为什么这么填这些字段" · 帮 OPUS 自己 review

【输出格式】
**严格输出 JSON** · 一个 object · 6 字段 + rationale · 不许加任何额外字段·不许加 ```json``` 围栏·直接吐 JSON 体。

【几个红线】
- 不许填 priority=5 除非 用户 原话有"急" / "马上" / "立刻" / "这个最重要"
- 不许把 estimated_hours 填 < 1 (LLM 通病·会低估)
- title 必须能让 用户 6 个月后看回来还知道在说啥
- design_sketch 不许写"实现 X"·要写"改 file_a.py 的 func_b · 加 logic_c"
"""


_USER_PROMPT_TEMPLATE = """用户 的请求：
\"\"\"{user_request}\"\"\"

当前上下文（如果有）：
\"\"\"{context}\"\"\"

把这条请求结构化为 wish_add 草稿 JSON。
"""


def _summarize(args: dict) -> str:
    req = (args.get("user_request") or "").strip()
    if len(req) > 60:
        req = req[:60] + "…"
    return f"把模糊请求转 wish 草稿: 「{req}」"


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _validate_draft(d: dict) -> tuple[Optional[str], dict]:
    """Returns (error_message, sanitized_dict). error_message=None means OK."""
    if not isinstance(d, dict):
        return "LLM 返回不是 JSON object", {}

    out: dict = {}
    title = (d.get("title") or "").strip()
    if not title or len(title) < 4:
        return "title 太短 (< 4 字符)", d
    if len(title) > 200:
        title = title[:200]
    out["title"] = title

    why = (d.get("why") or "").strip()
    if not why or len(why) < 10:
        return "why 太短 (< 10 字符 · 至少要 2 句)", d
    out["why"] = why

    out["design_sketch"] = (d.get("design_sketch") or "").strip()

    complexity = (d.get("complexity") or "medium").strip().lower()
    if complexity not in ("low", "medium", "high"):
        complexity = "medium"
    out["complexity"] = complexity

    try:
        hours = float(d.get("estimated_hours") or 4.0)
    except (TypeError, ValueError):
        hours = 4.0
    out["estimated_hours"] = max(1.0, min(12.0, hours))

    try:
        priority = int(d.get("priority") or 3)
    except (TypeError, ValueError):
        priority = 3
    out["priority"] = max(1, min(5, priority))

    out["rationale"] = (d.get("rationale") or "").strip()
    return None, out


def _run(args: dict) -> ToolResult:
    user_request = (args.get("user_request") or "").strip()
    if not user_request:
        return ToolResult(ok=False, output="", error="user_request 必填 · 把 用户 原话粘进来")

    context = (args.get("context") or "").strip() or "(没给上下文)"

    from daemon_runtime import RUNTIME, bg_max_tokens

    if RUNTIME.client is None:
        return ToolResult(
            ok=False, output="",
            error="RUNTIME.client 没初始化 · 这个工具需要在 daemon 主进程里跑 (Cursor 里测试请用 _run 直调)",
        )

    user_prompt = _USER_PROMPT_TEMPLATE.format(user_request=user_request, context=context)

    raw_output = ""
    try:
        if RUNTIME.provider == "anthropic":
            resp = RUNTIME.client.messages.create(
                model=RUNTIME.model,
                max_tokens=bg_max_tokens(),
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    raw_output += block.text
        else:
            resp = RUNTIME.client.chat.completions.create(
                model=RUNTIME.model,
                max_tokens=bg_max_tokens(),
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw_output = resp.choices[0].message.content or ""
    except Exception as e:
        return ToolResult(
            ok=False, output="",
            error=f"LLM 调用失败: {type(e).__name__}: {e}",
        )

    body = _strip_json_fence(raw_output)
    try:
        draft = json.loads(body)
    except json.JSONDecodeError as e:
        return ToolResult(
            ok=False, output="",
            error=f"LLM 没吐合法 JSON: {e}\n\n原始输出 (前 600 字符):\n{body[:600]}",
        )

    err, clean = _validate_draft(draft)
    if err:
        return ToolResult(
            ok=False, output="",
            error=f"草稿不合规: {err}\n\nLLM 原始输出 (前 600 字符):\n{body[:600]}",
        )

    lines = [
        "# 📝 心愿草稿 · 请 review 后调 wish_add 落档",
        "",
        f"**title**: {clean['title']}",
        f"**complexity**: {clean['complexity']} · ~{clean['estimated_hours']}h · priority {'⭐' * clean['priority']}",
        "",
        "**why**:",
    ]
    for ln in clean["why"].splitlines()[:10]:
        lines.append(f"  > {ln}")
    if clean["design_sketch"]:
        lines.append("")
        lines.append("**design_sketch**:")
        for ln in clean["design_sketch"].splitlines()[:15]:
            lines.append(f"  > {ln}")
    if clean["rationale"]:
        lines.append("")
        lines.append("**rationale (LLM 自己解释为啥这么填)**:")
        for ln in clean["rationale"].splitlines()[:6]:
            lines.append(f"  > {ln}")

    lines += [
        "",
        "---",
        "",
        "**下一步建议**:",
        "1. 你 (OPUS) 看一遍·觉得字段对就直接调 `wish_add` · 把上面 6 个字段贴进去",
        "2. 觉得 LLM 帮你想浅了·可以再调一次 intent_to_wish · 把 context 写得更细",
        "3. 落档后默认 status=pending · 用户 在 WebUI 心愿单点「批准」· OPUS 勘察出方案等批 · 批了才写码 (态)",
        "",
        "⚠ **不要直接 write_file 改代码** · 没进 wish 流程就改 = 没分支隔离 = 出错没法回退",
    ]

    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="intent_to_wish",
    description=(
        "【铁律 0 · 模糊请求时的强制第一调用】把 用户 的模糊请求结构化为 wish_add 草稿。\n\n"
        "**触发条件 (任一命中 · 第一个工具调用必须是这个)**:\n"
        "  - 用户 用词: 『改一下』/『加个』/『弄个』/『让 X 更醒目』/『搞点 Y』/『我想要 X』/『来 wish 一下 X』\n"
        "  - 用户 给的是目标描述·不是文件路径 + 操作指令\n"
        "  - 你听完不能立刻写出 design_sketch (改哪个文件 + 第几行 + 改成啥)\n\n"
        "**严格禁止 (在调本工具之前)**:\n"
        "  - ❌ 不许先 grep_files / read_file / web_fetch / shell_exec 自己『摸清楚』\n"
        "  - ❌ 不许先 write_file 改任何东西\n"
        "  - ❌ 不许先 wish_create 跳过意图守护直接进 wish 流程\n"
        "  > 反面教材: session api-2026-05-25_002346_9f1bc0 · 跳过本工具先 grep+read 然后改文件 = 工艺羞辱\n\n"
        "**为什么必须第一动作**: 这工具的目的是『让 用户 看见 OPUS 怎么理解模糊请求』· 不是『让 OPUS 给出最准确方案』。用户 看草稿可以 push back/refine·这是工程纪律不是 token 优化。草稿浅没关系·重点是 用户 进了 review 流程。\n\n"
        "**何时不调本工具**:\n"
        "  - 用户 给了明确『在 X 文件 N 行改 Y』 → 走铁律 1 (wish_create + 分支 + 改)\n"
        "  - 只读任务 (『chat.js 有什么可以优化』『心愿单几条 drafted』) → 调研类工具直接用\n"
        "  - 已经在 wish-XXX 分支上继续打磨原 wish → 直接改\n\n"
        "**调用之后**:\n"
        "  - 工具会返回渲染好的 6 字段草稿 markdown (title / why / design_sketch / complexity / hours / priority / rationale)\n"
        "  - 你 review 字段·觉得 OK → 调 `wish_add` 落档 (status=drafted)\n"
        "  - 草稿不准 → 再调一次 intent_to_wish · context 写细一点·或者直接调 wish_add 自己改字段\n"
        "  - **不要自动 wish_add** · 等你 review·这是设计约束"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "user_request": {
                "type": "string",
                "description": "用户 的原话 · 越接近原句越好 · 不要总结",
                "minLength": 4,
            },
            "context": {
                "type": "string",
                "description": (
                    "可选 · 当前对话上下文 / 卷号 / 涉及哪些文件 / 用户 之前说过什么相关的事 · "
                    "context 越详细 LLM 草稿越准"
                ),
            },
        },
        "required": ["user_request"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
