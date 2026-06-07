"""
agent_tools/edit_file.py
========================

OPUS 的"精准改"——str_replace 局部替换。学 Cursor 的 StrReplace。

为什么造它 ( · chat.js 444K 整文件覆盖丢功能事故):
  write_file 只有"整文件覆盖" + read_file 一次只能看 40K 字符 →
  改一个 9000 行文件的某一段·也得把整文件重吐一遍·但看不见的 91% 只能靠记忆重建 →
  6/6 那次 (888e0ec) 就这么把语音/文档/视觉三块功能连人带码打回旧版·还语法全绿没人报警。
  request_restart.py 早就写着"用 edit_file"·可这工具一直没造出来——现在补上。

它怎么治本:
  只替换一段【唯一匹配】的文本·其余字节原地不动、不读、不重传。改 chat.js 的某个函数·
  根本不会碰到 (也不可能碰到) 那些没读到的代码。大文件编辑从"凭记忆重建整体"
  变成"只动你亲眼定位的那一段"。

安全语义 (照抄 Cursor 三条):
  1. old_string 必须【唯一命中】:
       0 处 → 报错 (你的视图过时了·先 read_file 重读那段·原样复制)
       >1 处且没传 replace_all → 报错 (前后多带几行上下文让它唯一)
  2. 改的是【磁盘当前内容】·old_string 对不上 = 当场撞墙失败·而不是默默碾过去。
     过时的编辑改不动 → 这就是安全感的来源。
  3. 写完回读校验 (utf-8 roundtrip) + edit_selfcheck 语法自检·失败自动回滚旧内容。

三档:
  - 默认 CONFIRM
  - 命中 .env / soul/ / .git/ / .venv/ / opus-soul / skills-cursor → GUARD
  (复用 write_file 的分类逻辑·防冗余)
"""

from __future__ import annotations

from pathlib import Path

from . import (
    TIER_CONFIRM,
    ToolResult,
    ToolSpec,
    register_tool,
)
from .write_file import _resolve, _classify, _branch_guard_warning


def _summarize(args: dict) -> str:
    p = args.get("path", "?")
    old = args.get("old_string", "") or ""
    new = args.get("new_string", "") or ""
    ra = "  [replace_all]" if args.get("replace_all") else ""
    return f"edit_file  {p}  -{len(old)}/+{len(new)} chars{ra}"


def _rollback(path: Path, original: str) -> str:
    try:
        path.write_text(original, encoding="utf-8")
        return " · 已回滚到改动前"
    except Exception:
        return " · 回滚也失败了 (磁盘上可能是坏的中间态·赶紧人工看)"


def _run(args: dict) -> ToolResult:
    raw = args.get("path")
    if not raw:
        return ToolResult(ok=False, output="", error="missing 'path'")
    old_string = args.get("old_string")
    new_string = args.get("new_string")
    if old_string is None:
        return ToolResult(ok=False, output="", error="missing 'old_string'")
    if new_string is None:
        return ToolResult(ok=False, output="", error="missing 'new_string'")
    if old_string == "":
        return ToolResult(ok=False, output="", error="old_string 为空·无法定位。给一段要替换的真实文本。")
    if old_string == new_string:
        return ToolResult(ok=False, output="", error="old_string == new_string · 没有任何改动")
    replace_all = bool(args.get("replace_all"))

    path = _resolve(raw)
    if not path.exists():
        return ToolResult(
            ok=False, output="",
            error=f"file not found: {path}\nedit_file 只改已存在的文件·新建请用 write_file mode=create。",
        )
    if not path.is_file():
        return ToolResult(ok=False, output="", error=f"not a file: {path}")

    try:
        original = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ToolResult(
            ok=False, output="",
            error="file 不是合法 UTF-8·edit_file 不做编码猜测。先 read_file 确认编码再说。",
        )
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"{type(e).__name__}: {e}")

    count = original.count(old_string)
    if count == 0:
        return ToolResult(
            ok=False, output="",
            error=(
                "old_string 在文件里【一处都没匹配到】。\n"
                "常见原因: 你的视图过时 / 空白·缩进对不上 / 跨行内容漏了字 / 把行号前缀也复制进去了。\n"
                "→ 先 read_file 带 start_line/end_line 重读那一段·把要改的文本【原样】复制出来再 edit_file。\n"
                "  (read_file 输出的 '   12 | code' 里·行号和 ' | ' 是元数据·别复制进 old_string。)"
            ),
        )
    if count > 1 and not replace_all:
        return ToolResult(
            ok=False, output="",
            error=(
                f"old_string 匹配到 {count} 处·【不唯一】·拒绝改 (怕改错地方)。\n"
                "二选一:\n"
                "  · 扩大 old_string——前后多带几行上下文·让它在全文里只命中一处 (推荐·最安全)\n"
                "  · 传 replace_all=true——确认这 {count} 处都要改成一样的"
            ),
        )

    updated = original.replace(old_string, new_string)

    # 安全兜底: 替换后文件几乎为空 = 大概率误操作 (old_string 几乎是全文)
    if not updated.strip():
        return ToolResult(
            ok=False, output="",
            error="拒绝: 替换后整个文件几乎为空·疑似 old_string 吃掉了全文。检查 old_string 范围。",
        )

    try:
        path.write_text(updated, encoding="utf-8")
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"write failed: {type(e).__name__}: {e}")

    # utf-8 roundtrip 回读校验 (silent encoding loss / concurrent write 兜底)
    try:
        written = path.read_text(encoding="utf-8")
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"verify read-back failed: {e}{_rollback(path, original)}")
    if written != updated:
        return ToolResult(
            ok=False, output="",
            error=f"verify roundtrip mismatch (疑似编码丢失 / 并发覆盖 / 磁盘错){_rollback(path, original)}",
        )

    n_repl = count if replace_all else 1
    delta = len(updated) - len(original)
    base = (
        f"edited {path}\n"
        f"replaced {n_repl} occurrence(s) · size {len(original)} → {len(updated)} chars "
        f"({delta:+d}) · verified=utf-8-roundtrip"
    )

    warn = _branch_guard_warning(path)
    if warn:
        base = f"{base}\n\n{warn}"

    try:
        from workers.edit_selfcheck import selfcheck
        sc_ok, sc_warn = selfcheck([str(path)])
        if not sc_ok:
            base = f"{base}\n\n{sc_warn}"
    except Exception:
        pass

    return ToolResult(ok=True, output=base)


SPEC = ToolSpec(
    name="edit_file",
    description=(
        "Surgically edit an EXISTING text file by replacing one unique snippet (str_replace). "
        "STRONGLY PREFERRED over write_file for any file more than a few hundred lines long — "
        "it touches ONLY the matched region, so you never reconstruct (and silently lose) the rest "
        "of the file. This is how you safely edit big files like static/chat.js.\n\n"
        "Rules:\n"
        "  - old_string must match EXACTLY ONE place. Include 3-5 lines of surrounding context to make it unique.\n"
        "  - 0 matches → fails (your view is stale; re-read the region with read_file start_line/end_line, "
        "copy the text verbatim — do NOT include read_file's 'NNN | ' line-number prefix).\n"
        "  - >1 match → fails unless replace_all=true.\n"
        "  - On success: utf-8 roundtrip verify + syntax self-check; auto-rolls back on verify failure.\n\n"
        "Workflow for big files: read_file the region → copy the exact snippet → edit_file with that as old_string.\n"
        "Confirm tier (GUARD for .env / soul/ / .git/ / .venv / opus-soul / skills-cursor paths)."
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Target file (must already exist). Relative resolves from Daemonkey root.",
            },
            "old_string": {
                "type": "string",
                "description": (
                    "Exact text to replace. Must uniquely identify ONE location "
                    "(include enough surrounding context). Whitespace/indentation must match the file exactly."
                ),
            },
            "new_string": {
                "type": "string",
                "description": "Replacement text. The rest of the file is left untouched byte-for-byte.",
            },
            "replace_all": {
                "type": "boolean",
                "description": "Replace EVERY occurrence instead of requiring uniqueness. Default false.",
            },
        },
        "required": ["path", "old_string", "new_string"],
    },
    run=_run,
    summarize=_summarize,
    classify=_classify,
)


register_tool(SPEC)
