"""
agent_tools/draft_studio.py
============================

Daemonkey 在对话里"出品"——内容制作 / 产品设计 / 产品开发 / 文档撰写 四个维度
共用一个工具，按 `domain` 参数路由。

档位：CONFIRM
  和 generate_report 同级别——产出一份文件，BRO 应该看见"Daemonkey 打算给我做
  一份《XXX》"再决定。这是 BRO 在 WebUI 工作室上能看到的工坊产出。

NLP 触发场景（Daemonkey 自己判断 domain）：
  - "给我写一个 AI 创业的选题"        → domain=content, kind=选题
  - "来一份关于 X 的口播稿"            → domain=content, kind=口播稿
  - "出个咖啡 App 的 spec"             → domain=design,  kind=spec
  - "画一下新手用户的旅程"             → domain=design,  kind=用户旅程
  - "列一下 Daemonkey 这周的 TODO"   → domain=dev,     kind=TODO
  - "做一份 Cloudflared 部署的技术调研" → domain=dev,     kind=技术调研
  - "写一条「微信桥怎么部署」的 wiki" → domain=docs,    kind=wiki
  - "整理一份 Daemonkey daemon 的 FAQ"      → domain=docs,    kind=FAQ

落盘：
  data/<domain>/<YYYYMMDD-HHMMSS>-<safe_title>.md
  每个文件头有 yaml frontmatter (title / kind / created_at / domain)

输出（给 LLM）：
  文件路径 + 大小 + 一行 BRO 提示（"BRO 在 WebUI 看 <icon> <label> 维度"）
"""
from __future__ import annotations

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


_DOMAIN_ICONS = {
    "content": "🎬",
    "design": "🎨",
    "dev": "💻",
    "docs": "📄",
}


def _summarize(args: dict) -> str:
    domain = (args.get("domain") or "").strip().lower()
    title = (args.get("title") or "未命名").strip()
    kind = (args.get("kind") or "").strip()
    body = args.get("body") or ""
    icon = _DOMAIN_ICONS.get(domain, "📝")
    body_len = len(body)
    kind_str = f" · {kind}" if kind else ""
    return f"{icon} {domain}{kind_str} · 出品《{title}》({body_len} 字)"


def _run(args: dict) -> ToolResult:
    from workers.studio_workshop import WORKSHOP_META, create_workshop_item

    domain = (args.get("domain") or "").strip().lower()
    title = (args.get("title") or "").strip()
    body = args.get("body") or ""
    kind = (args.get("kind") or "").strip()
    _canvas = args.get("canvas")
    canvas = True if _canvas is None else bool(_canvas)

    if domain not in WORKSHOP_META:
        return ToolResult(
            ok=False, output="",
            error=(
                f"domain 必须是 content / design / dev / docs 之一 · 收到 {domain!r}。"
                f" 内容制作 → content · 产品设计 → design · 产品开发 → dev · 文档撰写 → docs。"
            ),
        )
    if not title:
        return ToolResult(
            ok=False, output="",
            error="title 必填 · 这是文档标题 + 落盘文件名 + 工作室卡片显示的标题",
        )
    if not body or not body.strip():
        return ToolResult(
            ok=False, output="",
            error="body 必填 · Daemonkey 自己组装好的完整 markdown 正文",
        )

    try:
        result = create_workshop_item(domain, title, body, kind=kind)
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except OSError as e:
        return ToolResult(
            ok=False, output="",
            error=f"写文件失败: {e}",
        )

    meta = WORKSHOP_META[domain]
    size_kb = result["size_bytes"] / 1024

    # 画布页：默认随 md 同产一份自包含 HTML（中栏舞台可直接打开 + 圈字批注）
    # 渲染失败不影响 md 落盘 —— 画布是增强，不是前置条件
    canvas_rel = ""
    if canvas:
        try:
            from workers.canvas_page import render_canvas_html, write_canvas_for

            canvas_rel = write_canvas_for(
                result["path"],
                render_canvas_html(
                    title, body, kind=kind, domain=domain,
                    icon=meta["icon"], label=meta["label"],
                ),
            )
        except Exception as e:
            canvas_rel = f"__ERR__{type(e).__name__}: {str(e)[:120]}"

    lines = [
        f"已落盘 · {result['name']}",
        f"  维度: {meta['icon']} {meta['label']}",
        f"  类型: {kind or '(未指定)'}",
        f"  路径: {result['path']}",
        f"  大小: {size_kb:.1f} KB",
        f"  正文: {len(body)} 字符",
    ]
    if canvas_rel.startswith("__ERR__"):
        lines.append(f"  画布: 渲染失败（md 不受影响）· {canvas_rel[7:]}")
    elif canvas_rel:
        lines.append(f"  画布: {canvas_rel}")
        lines.append("        ↑ 中栏舞台可直接打开 · 能圈字批注 · 改完铺回中栏")
    lines += [
        "",
        f"BRO 在 WebUI '{meta['icon']} {meta['label']}' 维度可见 · 或直接打开 {result['path']}。",
    ]
    out = "\n".join(lines)
    # 画布页铺中栏：打 [[DK-OPEN]] 标记 → tool_loop 抽成 open_path → 前端 flushOpenActions 自动 openStageLast
    # 铺中栏：声明 stage_path（打标记 / 说人话由 tool_loop 出口统一兑现 · 第2刀）
    _stage_rel = canvas_rel if (canvas_rel and not canvas_rel.startswith("__ERR__")) else ""
    return ToolResult(ok=True, output=out, stage_path=_stage_rel)


SPEC = ToolSpec(
    name="draft_studio",
    description=(
        "在 Daemonkey 工作室出品文档 · 落 data/<domain>/（markdown 档案 + 默认同产一份可上中栏画布的原型 HTML）。"
        " 适合: 选题/口播稿 (content) · spec/用户旅程 (design) · TODO/技术调研 (dev) · FAQ/wiki (docs)。"
        " 正式 docx 报告用 generate_report。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "enum": ["content", "design", "dev", "docs"],
                "description": (
                    "出品维度: content (内容制作 · 🎬) / design (产品设计 · 🎨) / "
                    "dev (产品开发 · 💻) / docs (文档撰写 · 📄)"
                ),
            },
            "title": {
                "type": "string",
                "description": "文档标题 · 用在文件名 + 工作室卡片显示 · 必填",
            },
            "body": {
                "type": "string",
                "description": "完整 markdown 正文。frontmatter 由工具加，正文不必含。",
            },
            "kind": {
                "type": "string",
                "description": (
                    "细分类型 · 写卡片副标题用 · 例如 content 维度的 '口播稿' / "
                    "design 维度的 'spec' / dev 维度的 'TODO' / docs 维度的 'FAQ'。"
                    "可空。"
                ),
            },
            "canvas": {
                "type": "boolean",
                "description": (
                    "默认 true · 是否同产一份可上中栏画布的 HTML"
                    "（自包含零依赖 · 能圈字批注 · 讨论方案和原型走它）"
                ),
            },
        },
        "required": ["domain", "title", "body"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
