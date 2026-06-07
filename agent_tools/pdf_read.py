"""
agent_tools/pdf_read.py
=======================

读 PDF 提取文本——离职月 用户 大概率会让 OPUS 看 offer / 合同 / 论文。

设计：
  - pypdf（纯 Python，无系统依赖，轻量 338KB）
  - 默认抓全文，可指定 pages（"1-3" / "1,3,5" / "all"）
  - 返回纯文本（去掉 PDF 自带的位置坐标 / 字体元数据）
  - max_chars 截断，默认 8000；标注被截断时哪一页停下了

不做：
  - OCR（图片型 PDF 这里返回空，让 OPUS 知道是扫描件再决定）
  - 图片提取（用 read_file 直接 read PDF 的二进制走 vision 模型才有意义）
  - 表格结构化（pypdf 抓的表格是行序，可读性 ok）

AUTO 档——只读本地 PDF。
"""

from __future__ import annotations

import re
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


DEFAULT_MAX_CHARS = 8000


def _parse_pages(pages_str: str, total_pages: int) -> list[int]:
    """
    'all' / '' / None → 全部
    '1-3' → [0,1,2]（用户输入 1-indexed，内部转 0-indexed）
    '1,3,5' → [0,2,4]
    '1-3,5' → [0,1,2,4]
    """
    pages_str = (pages_str or "").strip().lower()
    if not pages_str or pages_str == "all":
        return list(range(total_pages))

    result: set[int] = set()
    for part in pages_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                start = max(1, int(a.strip()))
                end = min(total_pages, int(b.strip()))
                for p in range(start, end + 1):
                    result.add(p - 1)
            except ValueError:
                continue
        else:
            try:
                p = int(part)
                if 1 <= p <= total_pages:
                    result.add(p - 1)
            except ValueError:
                continue
    return sorted(result)


def _clean_text(raw: str) -> str:
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n[ \t]+", "\n", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def _summarize(args: dict) -> str:
    path = args.get("path", "")
    pages = (args.get("pages") or "all").strip()
    return f"pdf_read  path={path}  pages={pages}"


def _run(args: dict) -> ToolResult:
    path_str = (args.get("path") or "").strip()
    if not path_str:
        return ToolResult(ok=False, output="", error="path is required")

    pdf_path = Path(path_str)
    if not pdf_path.is_absolute():
        pdf_path = Path.cwd() / pdf_path

    if not pdf_path.exists():
        return ToolResult(ok=False, output="", error=f"file not found: {pdf_path}")
    if not pdf_path.is_file():
        return ToolResult(ok=False, output="", error=f"not a file: {pdf_path}")

    if pdf_path.suffix.lower() != ".pdf":
        return ToolResult(
            ok=False, output="",
            error=f"not a .pdf file (suffix: {pdf_path.suffix}). 用 read_file 读其他格式",
        )

    size = pdf_path.stat().st_size
    if size > 50 * 1024 * 1024:  # 50MB cap
        return ToolResult(
            ok=False, output="",
            error=f"PDF too large: {size / 1024 / 1024:.1f}MB (cap 50MB). 拆开后再读",
        )

    max_chars = int(args.get("max_chars") or DEFAULT_MAX_CHARS)
    max_chars = max(500, min(max_chars, 50000))

    try:
        from pypdf import PdfReader
    except ImportError:
        return ToolResult(ok=False, output="", error="pypdf not installed. run: pip install pypdf")

    try:
        reader = PdfReader(str(pdf_path))
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"failed to open PDF: {type(e).__name__}: {e}")

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return ToolResult(
                ok=False, output="",
                error="PDF is encrypted/password-protected. 不支持自动破解",
            )

    total = len(reader.pages)
    if total == 0:
        return ToolResult(ok=False, output="", error="PDF has 0 pages")

    pages_to_read = _parse_pages((args.get("pages") or "all"), total)
    if not pages_to_read:
        return ToolResult(
            ok=False, output="",
            error=f"no valid pages in {args.get('pages')!r}; pdf has {total} pages",
        )

    chunks: list[str] = []
    truncated_at: int | None = None
    total_chars = 0

    for page_idx in pages_to_read:
        try:
            page_text = reader.pages[page_idx].extract_text() or ""
        except Exception as e:
            page_text = f"[页 {page_idx + 1} 解析失败: {type(e).__name__}]"
        page_text = _clean_text(page_text)

        page_block = f"\n--- 页 {page_idx + 1}/{total} ---\n{page_text}"
        if total_chars + len(page_block) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 200:
                chunks.append(page_block[:remaining])
            truncated_at = page_idx + 1
            break
        chunks.append(page_block)
        total_chars += len(page_block)

    info_lines = [
        f"pdf_read · {pdf_path.name}",
        f"path: {pdf_path}",
        f"size: {size} bytes  ·  pages: {total}",
        f"requested: {len(pages_to_read)} pages  ·  extracted: {total_chars} chars",
    ]

    if truncated_at:
        unread = [p + 1 for p in pages_to_read if p + 1 > truncated_at]
        info_lines.append(
            f"[truncated at page {truncated_at}; {len(unread)} pages still unread; "
            f"call again with pages='{truncated_at + 1}-{pages_to_read[-1] + 1}' to continue]"
        )

    body = "".join(chunks).strip()
    if not body:
        info_lines.append(
            "[no extractable text — likely a scanned PDF (image-based). "
            "需要 OCR——目前还没实现 ocr_image 工具]"
        )

    return ToolResult(ok=True, output="\n".join(info_lines) + "\n\n" + body)


SPEC = ToolSpec(
    name="pdf_read",
    description=(
        "Extract text from a PDF file. Use for: 用户's contracts/offers (离职月), "
        "research papers, manuals, anything in PDF.\n"
        "  - pages: 'all' (default) | '1-3' | '1,3,5' | '1-3,5-7'\n"
        "  - max_chars: 500-50000 (default 8000)\n"
        "Returns clean text with page markers. If PDF is scanned (image-based), returns empty body "
        "with a hint—then ask 用户 to use OCR or paste text.\n"
        "AUTO tier (read-only)."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to .pdf file (absolute or relative to cwd)"},
            "pages": {
                "type": "string",
                "description": "Pages to read: 'all' / '1-3' / '1,3,5' / '1-3,5-7' (1-indexed). Default 'all'.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Max chars of output (500-50000, default 8000)",
            },
        },
        "required": ["path"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
