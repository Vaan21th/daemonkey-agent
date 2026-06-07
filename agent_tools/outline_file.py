"""
agent_tools/outline_file.py
===========================

OPUS 的"文件目录"——一秒看清一个大文件的骨架 (所有定义 + 行号)。

为什么 (续 · 和 edit_file 配套的另一半):
  edit_file 给了精准凿子·但改 9500 行的 chat.js 前·得先知道"那段在哪一行"。
  read_file 一次只能看 40K (9%) · grep_files 又得先猜对名字。 outline_file 给一张目录:
  所有函数 / 类 / 常量定义 + 行号·OPUS 看着目录直接跳到目标行·再 read_file 那一段·
  再 edit_file 精准改。 至此 "定位 → 看细节 → 精准改" 这条链对大文件彻底闭合·
  不用再"摸黑整文件覆盖"。

支持:
  - .py            → ast 解析 (class / def / async def · 含类内一层 method · 顶层常量)
  - .js/.mjs/.ts   → 正则 (function / const-fn / arrow / class + // ─── section banner)
  - .md            → 标题 (#..######)
  - 其它           → 提示用 grep_files

AUTO tier · 纯读 · 不需要 用户 介入。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


ROOT = Path(__file__).resolve().parent.parent
MAX_OUTPUT_CHARS = 30000


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()


def _summarize(args: dict) -> str:
    return f"outline_file  {args.get('path', '?')}"


def _outline_python(text: str) -> list[tuple[int, str]]:
    """返回 [(lineno, 'kind name')]·按行号排序。"""
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [(e.lineno or 1, f"⚠️ SyntaxError: {e.msg} (ast 解析失败·只能给到这里)")]
    items: list[tuple[int, str]] = []

    def kind_of(node) -> str:
        if isinstance(node, ast.AsyncFunctionDef):
            return "async def"
        if isinstance(node, ast.FunctionDef):
            return "def"
        return "class"

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            items.append((node.lineno, f"{kind_of(node)} {node.name}"))
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        items.append((sub.lineno, f"    {kind_of(sub)} {sub.name}"))
        elif isinstance(node, ast.Assign):
            # 顶层常量 (如 _DOC_MIMES / ROOT / MAX_OUTPUT_CHARS) · 只取简单 NAME 目标
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    items.append((node.lineno, f"const {tgt.id}"))
    items.sort(key=lambda x: x[0])
    return items


# JS/TS 正则 (逐行扫·宁可多列几个·不漏关键定义)
_JS_CLASS = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)")
_JS_FUNC = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)")
_JS_ASSIGN_FN = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)"
)
_JS_ASSIGN_OTHER = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*[\[{]"
)
_JS_BANNER = re.compile(r"^\s*//\s*(.*[─=]{3,}.*|wish-\S+.*|卷[一二三四五六七八九十百\d]+.*)")


def _outline_js(text: str) -> list[tuple[int, str]]:
    items: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        m = _JS_CLASS.match(line)
        if m:
            items.append((i, f"class {m.group(1)}"))
            continue
        m = _JS_FUNC.match(line)
        if m:
            items.append((i, f"function {m.group(1)}"))
            continue
        m = _JS_ASSIGN_FN.match(line)
        if m:
            items.append((i, f"fn {m.group(1)}"))
            continue
        m = _JS_ASSIGN_OTHER.match(line)
        if m:
            items.append((i, f"const {m.group(1)}"))
            continue
        m = _JS_BANNER.match(line)
        if m:
            banner = m.group(1).strip().rstrip("─=").strip()
            if banner:
                items.append((i, f"§ {banner[:60]}"))
    return items


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)")


def _outline_md(text: str) -> list[tuple[int, str]]:
    items: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        m = _MD_HEADING.match(line)
        if m:
            depth = len(m.group(1))
            indent = "  " * (depth - 1)
            items.append((i, f"{indent}{'#' * depth} {m.group(2).strip()[:80]}"))
    return items


def _run(args: dict) -> ToolResult:
    raw = args.get("path")
    if not raw:
        return ToolResult(ok=False, output="", error="missing 'path'")
    path = _resolve(raw)
    if not path.exists():
        return ToolResult(ok=False, output="", error=f"file not found: {path}")
    if not path.is_file():
        return ToolResult(ok=False, output="", error=f"not a file: {path}")

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ToolResult(ok=False, output="", error="file 不是合法 UTF-8·先 read_file 确认编码")
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"{type(e).__name__}: {e}")

    suffix = path.suffix.lower()
    total = text.count("\n") + 1
    if suffix == ".py":
        items = _outline_python(text)
    elif suffix in (".js", ".mjs", ".ts", ".jsx", ".tsx"):
        items = _outline_js(text)
    elif suffix in (".md", ".markdown"):
        items = _outline_md(text)
    else:
        return ToolResult(
            ok=True,
            output=(
                f"# {path}  ({total} lines)\n"
                f"(outline 暂不支持 {suffix or '无扩展名'} · 用 grep_files 搜符号 · 或 read_file 带 start/end 翻)"
            ),
        )

    if not items:
        return ToolResult(
            ok=True,
            output=f"# {path}  ({total} lines)\n(没扫到定义 · 可能是数据/配置文件 · 用 read_file 直接看)",
        )

    header = f"# {path}  ({total} lines · {len(items)} symbols) — outline\n"
    body = header + "\n".join(f"{ln:>6} | {label}" for ln, label in items)

    truncated = False
    if len(body) > MAX_OUTPUT_CHARS:
        body = body[:MAX_OUTPUT_CHARS] + "\n\n... [outline 太长被截断·用 grep_files 缩小范围]"
        truncated = True

    body += (
        "\n\n→ 下一步: read_file(path, start_line=X, end_line=Y) 看某段细节 · "
        "再 edit_file 精准改。 别整文件 overwrite (缩水守卫会拦)。"
    )
    return ToolResult(ok=True, output=body, truncated=truncated)


SPEC = ToolSpec(
    name="outline_file",
    description=(
        "Show a file's structural outline — every function / class / top-level constant (and markdown "
        "headings) with line numbers. Use this BEFORE editing a big file (e.g. static/chat.js, 9000+ lines) "
        "to find where the thing you want to change lives, then read_file that line range, then edit_file it. "
        "This is the navigation half of safe big-file editing (read_file alone truncates at ~40K chars).\n"
        "Supports: .py (ast) · .js/.ts/.mjs/.jsx/.tsx (regex) · .md (headings)."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File to outline. Relative resolves from Daemonkey root.",
            },
        },
        "required": ["path"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
