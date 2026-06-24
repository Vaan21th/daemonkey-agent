"""
agent_tools/generate_report.py
================================

OPUS 通过自然语言生成 DOCX 报告。

档位：CONFIRM
  生成的是"产物"——用户 应该看见"OPUS 打算给我做一份《XXX》报告"这一步。
  即使误生成也只是落盘 data/reports/ 多个文件 · 不破坏任何东西。
  以后真的高频用了再考虑放成 AUTO。

NLP 触发场景（OPUS 自己决定调这个工具的时机）：
  - "把本周雷达整理成一份报告" → 调 generate_report
  - "把刚才那段对话整理成 docx" → 调 generate_report
  - "给我做一份《2026 Q2 AI 趋势观察》" → 调 generate_report
  - "把这几个客户的情况汇总成文档发给我" → 调 generate_report

入参约定：
  title (必填)   - 报告标题 · 用在封面 + 文件名
  body  (必填)   - 报告主体 markdown · OPUS 自己组装好的完整正文
                   * 不必加 # 一级标题（封面会用 title · 重复会让 docx 头部空一行）
                   * 可以用 ## ### + 段落 + 列表 + 表格 + 引用 + 代码块
                   * 行内图片 ![alt](xxx.png) 路径会去 embed_image_dir 找

  subtitle      - 副标题（封面用）· 例 '2026-05-23 → 2026-05-30'
  audience      - 面向 · 例 '用户 自看' / '面向：投资人'
  note          - 封面备注 · 一行短句说明文档背景
  footer        - 封面页脚 · 默认 'Daemonkey · 工作室出品'
  theme         - 'opus_studio' (默认 · 紫色) / 'midnight' (深蓝)
  include_cover - bool (默认 True) · 不要封面就传 false · 纯正文 docx
  embed_image_dir - 字符串 · 解析 body 中相对图片路径的基准目录
                    默认 data/reports/_assets/<safe_title>/

落盘：
  data/reports/<safe_title>__<YYYYMMDD-HHMM>.docx
  · safe_title 去掉/替换特殊字符 · 保留中文
  · 文件被 Word 占用时自动加 -v2 / -v3 (引擎层已处理)

输出（给 LLM）：
  生成的 docx 路径 + 大小 + 主题 + 字符数
"""
from __future__ import annotations

import re
import datetime
from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


_ROOT = Path(__file__).resolve().parent.parent
_REPORTS_DIR = _ROOT / "data" / "reports"


_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _safe_filename(title: str) -> str:
    """报告标题 → 安全的文件名片段（保留中文 · 替换危险字符）"""
    cleaned = _UNSAFE_FILENAME.sub("_", title.strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = cleaned.strip("._-")
    return cleaned[:80] or "report"


def _summarize(args: dict) -> str:
    """给 用户 在 CONFIRM 提示里看的一行摘要"""
    title = (args.get("title") or "未命名报告").strip()
    body = args.get("body") or ""
    body_len = len(body)
    theme = (args.get("theme") or "opus_studio").lower()
    parts = [
        f"生成报告《{title}》",
        f"({body_len} 字 · {theme} 主题)",
    ]
    if args.get("subtitle"):
        parts.insert(1, f"副标题: {args['subtitle']}")
    return " · ".join(parts)


def _run(args: dict) -> ToolResult:
    title = (args.get("title") or "").strip()
    body = args.get("body") or ""

    if not title:
        return ToolResult(
            ok=False, output="",
            error="title 必填 · 这是报告标题 + 落盘文件名的来源",
        )

    # 卷七十四续十五 · 两步法兜底 · body 没传/空 → 抓"LLM 本轮回复正文"当正文。
    # 给 tool call 长参数易丢的弱模型(DeepSeek 等)留一条不走结构化长参数的路:
    # 先把完整 markdown 写在回复里(文本流是强项)·再调本工具【不带 body】。
    # 前沿模型直接传 body·根本进不来这个分支·零影响。
    grabbed_from_turn = False
    if not body or not body.strip():
        try:
            from . import current_turn_text
            grabbed = (current_turn_text() or "").strip()
        except Exception:
            grabbed = ""
        if grabbed:
            body = grabbed
            grabbed_from_turn = True

    if not body or not body.strip():
        return ToolResult(
            ok=False, output="",
            error=(
                "没拿到正文 · 两种给法二选一:\n"
                "  ① 把完整 markdown 正文直接放进 body 参数(一步到位);\n"
                "  ② 先在你这条回复正文里写完整 markdown · 再调本工具【不带 body】 · "
                "我会自动抓你刚写的正文(适合长文档·或对长参数不稳的模型)。\n"
                "现在 body 为空、你这条回复也没有可抓的正文——请补上正文再调一次。"
            ),
        )

    theme = (args.get("theme") or "opus_studio").lower().strip()
    include_cover = bool(args.get("include_cover", True))

    cover = None
    if include_cover:
        cover = {"title": title}
        for key in ("subtitle", "audience", "note", "footer"):
            v = args.get(key)
            if v:
                cover[key] = str(v).strip()
        cover.setdefault("footer", "Daemonkey · 工作室出品")

    safe_title = _safe_filename(title)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    out_name = f"{safe_title}__{timestamp}.docx"
    out_path = _REPORTS_DIR / out_name

    embed_dir_arg = args.get("embed_image_dir")
    if embed_dir_arg:
        embed_dir = Path(str(embed_dir_arg)).resolve()
    else:
        embed_dir = _REPORTS_DIR / "_assets" / safe_title

    try:
        from report_engine import render_report
    except ImportError as e:
        return ToolResult(
            ok=False, output="",
            error=f"report_engine 未安装或 python-docx 缺失: {e}",
        )

    try:
        final_path = render_report(
            md_text=body,
            output_path=out_path,
            cover=cover,
            theme=theme,
            here_dir=embed_dir,
        )
    except ValueError as e:
        return ToolResult(ok=False, output="", error=f"渲染失败: {e}")
    except Exception as e:
        return ToolResult(
            ok=False, output="",
            error=f"渲染时发生意外异常: {type(e).__name__}: {e}",
        )

    if not final_path.exists():
        return ToolResult(
            ok=False, output="",
            error=f"渲染器声称写入了 {final_path} · 但磁盘上找不到这个文件",
        )

    # 补丁 · 同步落 markdown 源 · 供 WebUI 预览 + 未来重渲染
    # 文件名跟 docx 同名（差扩展名）· front-matter 记封面元数据 + body
    md_path = final_path.with_suffix(".md")
    try:
        front_matter_lines = ["---"]
        front_matter_lines.append(f"title: {title}")
        front_matter_lines.append(f"generated_at: {datetime.datetime.now().isoformat(timespec='seconds')}")
        front_matter_lines.append(f"theme: {theme}")
        if cover:
            for k in ("subtitle", "audience", "note", "footer"):
                v = cover.get(k)
                if v:
                    safe = str(v).replace("\n", " ").strip()
                    front_matter_lines.append(f"{k}: {safe}")
        front_matter_lines.append(f"docx: {final_path.name}")
        front_matter_lines.append("---")
        md_path.write_text(
            "\n".join(front_matter_lines) + "\n\n" + body,
            encoding="utf-8",
        )
    except Exception as e:  # 落 md 失败不影响 docx · 只 log
        import logging
        logging.getLogger("opus.generate_report").warning(
            "落 md 源失败 (docx 仍可用): %s", e,
        )

    size_kb = final_path.stat().st_size / 1024
    rel_path = final_path.relative_to(_ROOT) if _ROOT in final_path.parents else final_path

    lines = [
        f"已生成报告 · {final_path.name}",
        f"  路径: {rel_path}",
        f"  大小: {size_kb:.1f} KB",
        f"  主题: {theme}",
        f"  正文长度: {len(body)} 字符"
        + ("（来自本轮回复正文 · 两步法兜底）" if grabbed_from_turn else ""),
    ]
    if include_cover:
        lines.append(f"  封面: 含 title='{title}'"
                     + (f" + subtitle='{cover.get('subtitle')}'" if cover.get("subtitle") else ""))
    else:
        lines.append("  封面: 无（纯正文 docx）")
    lines.append("")
    lines.append("用户 在 WebUI '📑 报告' 维度可见 · 或在 data/reports/ 直接打开。")

    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="generate_report",
    description=(
        "把 markdown 正文一键渲染成精排 DOCX 报告 · 自动加封面 + 视觉规范 · "
        "落 data/reports/ · 之后 用户 在 WebUI 可下载。"
        "适合：本周雷达汇总 / 对客户的方案文档 / 把某段对话整理成档案 / 任何"
        "需要交付正式格式文档的场景。\n"
        "两种用法 · ① 直接把正文放 body 参数;② 长文档推荐——先把完整 markdown 正文"
        "写在你的回复里 · 再调本工具【只给 title · 不带 body】 · 工具自动抓你回复的正文。"
        "(② 适合正文很长、或当前模型对超长结构化参数不稳时 · 走文本流更稳)"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "报告标题 · 用在封面 + 文件名 · 必填",
            },
            "body": {
                "type": "string",
                "description": (
                    "报告主体 markdown · OPUS 自己组装好的完整正文。"
                    "不必含 # 一级标题（封面会用 title）。"
                    "支持 ## ### 标题 / 段落 / **加粗** / `代码` / 列表 / "
                    "表格 / > 引用 / ``` 代码块 / --- 分割线 / "
                    "![alt](xxx.png) 图片。\n"
                    "【可选】不传 body 时 · 工具自动抓你【本条回复的正文】当报告主体——"
                    "所以长文档可以:先把完整 markdown 写在回复里 · 再调本工具只给 title。"
                ),
            },
            "subtitle": {
                "type": "string",
                "description": "副标题 · 显示在封面 title 下方 · 可选",
            },
            "audience": {
                "type": "string",
                "description": "面向对象 · 显示在封面页脚 · 例 '面向：用户 自看' · 可选",
            },
            "note": {
                "type": "string",
                "description": "封面备注 · 一行说明文档背景 · 可选",
            },
            "footer": {
                "type": "string",
                "description": "封面页脚 · 默认 'Daemonkey · 工作室出品' · 可选",
            },
            "theme": {
                "type": "string",
                "enum": ["opus_studio", "midnight"],
                "description": "视觉主题 · 默认 opus_studio (紫色) · midnight 是深蓝",
            },
            "include_cover": {
                "type": "boolean",
                "description": "是否生成封面页 · 默认 True · 纯正文 docx 传 false",
            },
            "embed_image_dir": {
                "type": "string",
                "description": (
                    "解析 body 中相对图片路径 ![](xx.png) 的基准目录。"
                    "默认 data/reports/_assets/<safe_title>/。"
                    "提前把图放进这个目录 · OPUS 引用相对路径即可。"
                ),
            },
        },
        "required": ["title"],
        "additionalProperties": False,
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
