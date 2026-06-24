"""
agent_tools/expand_trend_to_report.py
======================================

把工作室「今日趋势」里的某一条·一键展开成完整的 docx 报告。

档位：CONFIRM
  跑 LLM (要 token) + 落盘 docx · 用户 应该看见"OPUS 打算给我做一份《XXX 趋势报告》"。
  从 WebUI 趋势卡片"📑 写报告"按钮触发时 · 走 auto_confirm=confirm 快路径。

链路（ 用户 的诉求）：
  📡 信息雷达 (原料)
      ↓ trend_finder LLM 提炼
  🌊 今日趋势 / 军师视图
      ↓ 这个工具 LLM 展开
  📑 报告库 (docx 成品)

工作流：
  1. 读 data/trends.json · 找第 N 条趋势
  2. 调 LLM · 把 trend summary + refs 展开成 3000-4000 字 markdown 报告
  3. 内部调 report_engine.render_report · 落 docx 到 data/reports/
  4. 返回 docx 路径

NLP 触发：
  - 用户 在对话里"把第 2 个趋势写成报告" → expand_trend_to_report(trend_index=1)
  - WebUI 趋势卡片"📑 写报告"按钮 → 自动调 · index 由 UI 给

成本估算：
  - 输入 ~2k token (trend + refs + system prompt)
  - 输出 ~4k token (3000-4000 字中文报告)
  - claude-opus-4: ~$0.07/次
  - 触发不频繁（用户 主动点）· 一周几次OK
"""
from __future__ import annotations

import time

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


_REPORT_SYSTEM_PROMPT = (
    "你是用户的 AI 搭档。 "
    "你正在把一个雷达趋势展开成一份给用户内部用的报告。 "
    "用户看报告是为了「我能不能据此行动」 · 不要套话 · 不要总结性废话。"
)

_REPORT_USER_PROMPT_TEMPLATE = """请写一份关于「{title}」的工作室内部报告。

## 趋势元信息
- 标题: {title}
- 摘要: {summary}
- 强度评分: {intensity}/5
- 工作室视角: {angles_str}

## 参考的原始资讯（{n_refs} 条 · 来自雷达）
{refs_block}

---

请输出一份 markdown 格式的报告正文（不要 ``` 围栏 · 不要 # 一级标题 · 封面会自动加）·结构如下：

## 趋势概览
（200-300 字 · 简明扼要说清这是什么趋势 · 当前阶段在哪里）

## 核心信号
（500-700 字 · 从 refs 里提取具体事实 · 列点形式 · 每点标注信源）

## 前瞻性思考
（500-700 字 · 这个趋势如果成立 · 6 个月后 / 1 年后会怎样 · 用户 这种超级个体在那个时间点会看到什么）

## 工作室视角
（{angle_count}个 angle 各 200-400 字 · 每个 angle 是 用户 能切入的具体动作 · "可以做什么内容" / "可以出什么产品" / 等）

## 风险与不确定性
（300-400 字 · 不要回避 · 这个趋势可能是炒作的话 · 信号在哪 · 反方观点是什么）

## 下一步建议
（200-300 字 · 给 用户 列 3-5 个 immediate 动作 · 每个一句话 · 可立即执行）

## 信源
（列出 refs 里的所有 url · 一行一条）

---

要求：
- 全程中文
- 总长 3000-4500 字
- 不要堆砌形容词 · 不要"赋能"/"赛道"/"风口"这种空话
- 每段都该带具体的事实或具体的动作 · 不要纯推理
- 直接输出 markdown 正文（## 二级标题起）· 不要前后解释文字"""


def _summarize(args: dict) -> str:
    idx = args.get("trend_index")
    try:
        idx_i = int(idx)
    except (TypeError, ValueError):
        idx_i = -1
    if idx_i < 0:
        return "expand_trend_to_report (索引未指定)"
    return f"展开趋势 #{idx_i + 1} 为报告 (将调 LLM 写 3000-4500 字 + 落 docx)"


def _format_refs(refs: list[dict]) -> str:
    if not refs:
        return "(无参考资讯)"
    lines = []
    for i, r in enumerate(refs, 1):
        src = r.get("source", "?")
        title = (r.get("title") or "").strip().replace("\n", " ")
        url = r.get("url", "")
        lines.append(f"{i}. [{src}] {title}\n   {url}")
    return "\n".join(lines)


_ANGLE_NAMES = {
    "content": "🎬 内容制作",
    "design": "🎨 产品设计",
    "dev": "💻 产品开发",
    "docs": "📄 文档撰写",
    "service": "👥 用户服务",
}


def _run(args: dict) -> ToolResult:
    try:
        trend_index = int(args.get("trend_index", -1))
    except (TypeError, ValueError):
        return ToolResult(
            ok=False, output="",
            error="trend_index 必须是整数 · 0 = 第一个趋势 · 1 = 第二个 · 以此类推",
        )

    theme = (args.get("theme") or "opus_studio").lower().strip()

    from workers.trend_finder import load_trends

    trends_data = load_trends()
    trends = trends_data.get("trends") or []
    if not trends:
        return ToolResult(
            ok=False, output="",
            error="trends.json 里没有趋势 · 先让 OPUS 生成今日趋势再来。 "
                  "(可调 generate_trends 或在 WebUI 点'让 OPUS 重新总结')",
        )

    if trend_index < 0 or trend_index >= len(trends):
        return ToolResult(
            ok=False, output="",
            error=f"trend_index 越界 · 当前只有 {len(trends)} 个趋势 · "
                  f"索引应 0 到 {len(trends) - 1}",
        )

    trend = trends[trend_index]
    title = trend.get("title", "未命名趋势")
    summary = trend.get("summary", "")
    intensity = trend.get("intensity", 3)
    angles = trend.get("angles") or []
    refs = trend.get("refs") or []

    angles_str = (
        " · ".join(f"{_ANGLE_NAMES.get(a, a)}" for a in angles)
        if angles else "(暂无)"
    )

    user_prompt = _REPORT_USER_PROMPT_TEMPLATE.format(
        title=title,
        summary=summary,
        intensity=intensity,
        angles_str=angles_str,
        angle_count=max(1, len(angles)),
        n_refs=len(refs),
        refs_block=_format_refs(refs),
    )

    from daemon_runtime import RUNTIME, bg_max_tokens

    if RUNTIME.client is None:
        return ToolResult(
            ok=False, output="",
            error="RUNTIME.client 没初始化 · daemon 没启动 · 这个工具需要在 daemon 主进程里跑",
        )

    started = time.time()
    raw_output = ""
    usage_info = {}

    try:
        if RUNTIME.provider == "anthropic":
            resp = RUNTIME.client.messages.create(
                model=RUNTIME.model,
                max_tokens=bg_max_tokens(),
                system=_REPORT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    raw_output += block.text
            try:
                usage_info = {
                    "input_tokens": getattr(resp.usage, "input_tokens", 0),
                    "output_tokens": getattr(resp.usage, "output_tokens", 0),
                }
            except Exception:
                pass
        else:
            resp = RUNTIME.client.chat.completions.create(
                model=RUNTIME.model,
                max_tokens=bg_max_tokens(),
                messages=[
                    {"role": "system", "content": _REPORT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw_output = resp.choices[0].message.content or ""
            try:
                usage_info = {
                    "input_tokens": getattr(resp.usage, "prompt_tokens", 0),
                    "output_tokens": getattr(resp.usage, "completion_tokens", 0),
                }
            except Exception:
                pass
    except Exception as e:
        return ToolResult(
            ok=False, output="",
            error=f"LLM 调用失败: {type(e).__name__}: {e}",
        )

    elapsed_ms = int((time.time() - started) * 1000)
    body = raw_output.strip()
    # 移除可能的 markdown 围栏（虽然 prompt 里说不要 · 防御性）
    if body.startswith("```"):
        body = body.split("\n", 1)[-1] if "\n" in body else body
        if body.endswith("```"):
            body = body.rsplit("```", 1)[0]
        body = body.strip()

    if len(body) < 300:
        return ToolResult(
            ok=False, output="",
            error=f"LLM 输出太短 ({len(body)} 字) · 可能是 timeout 或限制 · "
                  f"raw: {raw_output[:300]}",
        )

    # 调 generate_report 走 report_engine
    report_title = f"{title} · 趋势报告"
    subtitle = f"强度 {intensity}/5 · {angles_str}"

    try:
        from report_engine import render_report
        from pathlib import Path
        import datetime
        import re

        ROOT = Path(__file__).resolve().parent.parent
        reports_dir = ROOT / "data" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        unsafe = re.compile(r'[\\/:*?"<>|\r\n\t]+')
        safe_title = unsafe.sub("_", report_title.strip())[:80] or "report"
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        out_path = reports_dir / f"{safe_title}__{ts}.docx"

        cover = {
            "title": report_title,
            "subtitle": subtitle,
            "audience": "用户 内部参考",
            "note": "从今日趋势一键展开 · OPUS 工作室出品",
            "footer": "Daemonkey · 工作室",
        }

        final_path = render_report(
            md_text=body,
            output_path=out_path,
            cover=cover,
            theme=theme,
            here_dir=reports_dir / "_assets" / safe_title,
        )
    except Exception as e:
        return ToolResult(
            ok=False, output="",
            error=f"报告 docx 渲染失败 (LLM 输出已拿到 · 但 report_engine 出错): "
                  f"{type(e).__name__}: {e}\n\n"
                  f"LLM 输出前 500 字:\n{body[:500]}",
        )

    size_kb = final_path.stat().st_size / 1024
    rel = final_path.relative_to(final_path.parent.parent.parent)

    lines = [
        f"已生成趋势报告 · {final_path.name}",
        f"  趋势: 「{title}」(强度 {intensity}/5)",
        f"  工作室视角: {angles_str}",
        f"  报告长度: {len(body)} 字",
        f"  docx 路径: {rel}",
        f"  docx 大小: {size_kb:.1f} KB",
        f"  LLM 耗时: {elapsed_ms} ms",
    ]
    if usage_info:
        lines.append(f"  token: in {usage_info.get('input_tokens', 0)} / "
                     f"out {usage_info.get('output_tokens', 0)}")
    lines.append("")
    lines.append("用户 在 WebUI '📑 报告库' 维度可见 · 也可在底栏点'下载'。")

    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="expand_trend_to_report",
    description=(
        "把今日趋势里的某一条 · 用 LLM 展开成 3000-4500 字的完整 docx 报告 · "
        "自动落 data/reports/。 适合: 用户 在趋势卡片上点'写报告' · 或对话里"
        "「把第 N 个趋势做成报告」。这是 信息雷达→今日趋势→报告库 链路上"
        "「趋势→报告」这一环的快路径。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "trend_index": {
                "type": "integer",
                "description": (
                    "trends.json 里第几个趋势 · 0-indexed · "
                    "0 = 第一个 · 1 = 第二个 · 以此类推"
                ),
            },
            "theme": {
                "type": "string",
                "description": "docx 主题: opus_studio (默认) / manju",
            },
        },
        "required": ["trend_index"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
