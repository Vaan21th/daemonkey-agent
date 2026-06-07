"""
agent_tools/draft_studio.py
============================

OPUS 在对话里"出品"——内容制作 / 产品设计 / 产品开发 / 文档撰写 四个维度
共用一个工具，按 `domain` 参数路由。

档位：CONFIRM
  和 generate_report 同级别——产出一份文件，用户 应该看见"OPUS 打算给我做
  一份《XXX》"再决定。这是 用户 在 WebUI 工作室上能看到的工坊产出。

NLP 触发场景（OPUS 自己判断 domain）：
  - "给我写一个 AI 创业的选题"        → domain=content, kind=选题
  - "来一份关于 X 的口播稿"            → domain=content, kind=口播稿
  - "出个咖啡 App 的 spec"             → domain=design,  kind=spec
  - "画一下新手用户的旅程"             → domain=design,  kind=用户旅程
  - "列一下 Daemonkey 这周的 TODO"   → domain=dev,     kind=TODO
  - "做一份 Cloudflared 部署的技术调研" → domain=dev,     kind=技术调研
  - "写一条「微信桥怎么部署」的 wiki" → domain=docs,    kind=wiki
  - "整理一份 OPUS daemon 的 FAQ"      → domain=docs,    kind=FAQ

落盘：
  data/<domain>/<YYYYMMDD-HHMMSS>-<safe_title>.md
  每个文件头有 yaml frontmatter (title / kind / created_at / domain)

输出（给 LLM）：
  文件路径 + 大小 + 一行 用户 提示（"用户 在 WebUI 看 <icon> <label> 维度"）
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
            error="body 必填 · OPUS 自己组装好的完整 markdown 正文",
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

    lines = [
        f"已落盘 · {result['name']}",
        f"  维度: {meta['icon']} {meta['label']}",
        f"  类型: {kind or '(未指定)'}",
        f"  路径: {result['path']}",
        f"  大小: {size_kb:.1f} KB",
        f"  正文: {len(body)} 字符",
        "",
        f"用户 在 WebUI '{meta['icon']} {meta['label']}' 维度可见 · 或直接打开 {result['path']}。",
    ]
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="draft_studio",
    description=(
        "在 OPUS 工作室出品 markdown 文档 · 落 data/<domain>/ · WebUI 工坊维度自动可见。"
        " 适合: 选题 / 口播稿 / 视频脚本 (content) · spec / wireframe / 用户旅程 (design)"
        " · TODO / 周报 / 技术调研 (dev) · FAQ / wiki / 操作手册 (docs)。"
        " 想生成正式 docx 报告用 generate_report · 这个工具落 markdown · 工坊草稿用。"
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
                "description": (
                    "完整 markdown 正文 · OPUS 自己组装好。可以用 # ## 标题 / 列表 / 表格 / "
                    "代码块 / 引用 / 行内格式。文件头 yaml frontmatter 由工具自动加 · "
                    "正文不必含 frontmatter。"
                ),
            },
            "kind": {
                "type": "string",
                "description": (
                    "细分类型 · 写卡片副标题用 · 例如 content 维度的 '口播稿' / "
                    "design 维度的 'spec' / dev 维度的 'TODO' / docs 维度的 'FAQ'。"
                    "可空。"
                ),
            },
        },
        "required": ["domain", "title", "body"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
