"""
agent_tools/read_file.py
========================

OPUS 的"读"——读项目里任何文本文件。

为什么不直接让 OPUS 跑 `cat` ——
  1. 跨平台一致（Windows 上 cat 是 Get-Content，输出格式不一样）
  2. 行号 / 范围读取一次到位（不用 OPUS 自己拼 awk/sed）
  3. 路径安全（限制在 Daemonkey 根目录之内 + 灵魂文件不允许写但允许读）
  4. 二进制保护（碰到 binary 直接报错，不污染上下文）

 III · 2026-05-26 · binary 误判修:
  - _looks_binary 返回 (bool, reason)·拒绝时给 LLM 看 hexdump + 失败位置·
    让它能判断"是真 binary 还是文本但有怪字符"
  - 加 force 参数·LLM 看完诊断觉得是误判·可以 force=True 强读 (latin-1 容错解码)
  - 加 encoding 参数·用户 已知文件是 GBK 之类时 OPUS 可以显式指定
  - 之前: 误判 → `file looks binary; refusing to dump` → OPUS fallback shell_exec Get-Content
    → PS 5.1 乱码污染 context (反面教材·用户 截图过)
  - 现在: 误判 → 详细错信 + force 选项 → 不用走 shell·结构化继续
"""

from __future__ import annotations

from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


ROOT = Path(__file__).resolve().parent.parent
MAX_OUTPUT_CHARS = 40000


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()


def _is_valid_utf8_text(head: bytes) -> bool:
    """head 是否是合法 UTF-8 文本（容忍 8192 边界切断尾部一个多字节字符）。"""
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError as e:
        # 读 head 只取了前 8192 字节·边界可能正好切断一个多字节字符（最长 4 字节）。
        # 若解码错误就发生在尾部（剩 < 4 字节）·截掉那截再验·成功就当合法 UTF-8。
        if e.start >= len(head) - 3:
            try:
                head[:e.start].decode("utf-8")
                return True
            except UnicodeDecodeError:
                return False
        return False


def _classify_bytes(b: bytes) -> tuple[bool, str]:
    """返回 (is_binary, reason)·reason 在拒绝时给 LLM 看·让它判断要不要 force=True"""
    head = b[:8192]
    n = len(head)
    nul_pos = head.find(b"\x00")
    if nul_pos != -1:
        return True, f"NUL byte (\\x00) at offset {nul_pos} of first {n} bytes"

    #  · 合法 UTF-8 文本（含中文 / emoji）直接放行。
    #   旧版 bug: decode("utf-8") 成功后·仍按"高位字节 >50%"判 binary——但中文 UTF-8 每个汉字
    #   3 字节全是高位字节·纯中文≈100% 高位·必被误杀。OWNER-NOTEBOOK.md 这种中文重的文件每次
    #   中招·OPUS 被迫 force=true（用户 看了很多次）。 根因: UTF-8 多字节序列的高位字节是文本·
    #   不是 binary 信号。 解码通过 = 文本·不再做高位比例判定。
    if _is_valid_utf8_text(head):
        return False, ""

    # 走到这里 = 不是合法 UTF-8（可能 legacy CJK 编码 gbk/gb18030·或真 binary）。
    # 这时高位 + 控制字符比例才是有意义的 binary 信号。
    if n >= 256:
        high = sum(1 for byte in head if byte >= 0x80 and byte not in (0x09, 0x0a, 0x0d))
        ctrl = sum(1 for byte in head if byte < 0x20 and byte not in (0x09, 0x0a, 0x0d))
        nonprint_ratio = (high + ctrl) / n
        if nonprint_ratio > 0.50:
            return True, (
                f"not valid UTF-8; {nonprint_ratio:.0%} of first {n} bytes high-bit/non-printable "
                f"(real binary, or legacy CJK encoding — try encoding='gb18030')"
            )

    return False, ""


def _hexdump_head(b: bytes, n_bytes: int = 64) -> str:
    head = b[:n_bytes]
    hex_part = " ".join(f"{x:02x}" for x in head)
    ascii_part = "".join(chr(x) if 0x20 <= x < 0x7f else "." for x in head)
    return f"hex: {hex_part}\nasc: {ascii_part}"


def _summarize(args: dict) -> str:
    p = args.get("path", "?")
    rng = ""
    if args.get("start_line") or args.get("end_line"):
        rng = f"  lines {args.get('start_line', 1)}-{args.get('end_line', 'end')}"
    enc = args.get("encoding")
    force = args.get("force")
    suffix = ""
    if force:
        suffix += "  [force]"
    if enc:
        suffix += f"  [enc={enc}]"
    return f"read_file  {p}{rng}{suffix}"


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
        size = path.stat().st_size
    except OSError as e:
        return ToolResult(ok=False, output="", error=f"stat failed: {e}")

    if size > 5 * 1024 * 1024:
        return ToolResult(ok=False, output="",
                          error=f"file too large ({size} bytes); use grep_files or read with start_line/end_line")

    try:
        raw_bytes = path.read_bytes()
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"{type(e).__name__}: {e}")

    force = bool(args.get("force"))
    encoding = (args.get("encoding") or "").strip().lower()

    skip_binary_check = force or (encoding and encoding not in ("utf-8", "utf8"))
    if not skip_binary_check:
        is_binary, reason = _classify_bytes(raw_bytes)
        if is_binary:
            dump = _hexdump_head(raw_bytes, 64)
            return ToolResult(
                ok=False,
                output="",
                error=(
                    f"file looks binary ({size} bytes): {reason}.\n\n"
                    f"--- first 64 bytes ---\n{dump}\n\n"
                    "Decision aid for OPUS:\n"
                    "  - If header looks like text (mostly printable ASCII / CJK UTF-8 fragments) → "
                    "retry with force=true (latin-1 lossy decode) or encoding='gb18030' if you know it's CJK legacy.\n"
                    "  - If header looks binary (PK\\x03\\x04 zip / \\x89PNG / SQLite / msgpack) → "
                    "don't force-read; use a parser tool instead (json/sqlite3/zipfile via python_exec)."
                ),
            )

    if encoding and encoding not in ("utf-8", "utf8"):
        try:
            text = raw_bytes.decode(encoding, errors="replace")
        except LookupError:
            return ToolResult(ok=False, output="",
                              error=f"unknown encoding: {encoding!r}. try 'gb18030' / 'latin-1' / 'utf-16'.")
    elif force:
        text = raw_bytes.decode("utf-8", errors="replace")
    else:
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as e:
            return ToolResult(
                ok=False,
                output="",
                error=(
                    f"file is not valid UTF-8: {e}. "
                    "Daemonkey refuses silent GBK fallback to prevent mojibake. "
                    "Choose one:\n"
                    "  - force=true (latin-1 replace · garbled but readable)\n"
                    "  - encoding='gb18030' (legacy CJK files)\n"
                    "  - encoding='utf-16' (Windows Notepad default)\n"
                    "If this file is really legacy GBK and should be migrated:\n"
                    "  `Get-Content <path> -Encoding GB18030 | Set-Content <path> -Encoding utf8`"
                ),
            )

    lines = text.splitlines()
    total = len(lines)

    start = args.get("start_line")
    end = args.get("end_line")
    if start or end:
        s = max(1, int(start or 1))
        e = min(total, int(end or total))
        selected = lines[s - 1:e]
        numbered = "\n".join(f"{i + s:>5} | {ln}" for i, ln in enumerate(selected))
        header = f"# {path}  (lines {s}-{e} of {total})\n"
        body = header + numbered
    else:
        numbered = "\n".join(f"{i + 1:>5} | {ln}" for i, ln in enumerate(lines))
        header = f"# {path}  ({total} lines)\n"
        body = header + numbered

    truncated = False
    if len(body) > MAX_OUTPUT_CHARS:
        body = body[:MAX_OUTPUT_CHARS] + f"\n\n... [truncated; full was {len(body)} chars]"
        truncated = True

    return ToolResult(ok=True, output=body, truncated=truncated)


SPEC = ToolSpec(
    name="read_file",
    description=(
        "Read a text file from the Daemonkey project (or absolute path on the host). "
        "Returns the file with line numbers prepended. Use start_line/end_line for big files.\n\n"
        "**Binary detection** ( III · 2026-05-26 调宽容):\n"
        "  - 误判时 error 信息含: 拒绝原因 + 前 64 字节 hexdump · 让你判断是不是真 binary\n"
        "  - 看到 header 像文本 (UTF-8 CJK 片段 / 大量 ASCII) → 用 force=true 强读\n"
        "  - 看到真 binary header (PK\\x03\\x04 / \\x89PNG / SQLite) → 别 force · 换 parser\n"
        "  - **永远不要** fallback 到 `shell_exec Get-Content` —— PS 5.1 编码踩坑会污染 context (反面教材)\n\n"
        "**Encoding**:\n"
        "  - 默认严格 UTF-8 · 拒绝隐式 GBK 回退 (防 mojibake ·  P)\n"
        "  - 用户 已知文件是 GBK / UTF-16 / latin-1 → 显式传 encoding='gb18030' 之类\n"
        "  - 解码错误时 LLM 会看到具体失败位置 + 选项菜单"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to file. Relative paths resolve from Daemonkey root.",
            },
            "start_line": {
                "type": "integer",
                "description": "Optional start line (1-indexed, inclusive).",
            },
            "end_line": {
                "type": "integer",
                "description": "Optional end line (1-indexed, inclusive).",
            },
            "force": {
                "type": "boolean",
                "description": (
                    "Force-read even if binary-looking. Uses latin-1 errors='replace' decode · "
                    "garbled chars become ? / replacement char · still readable. "
                    "Only use when you've seen the hexdump diagnostic and confirmed it's text-with-quirks."
                ),
            },
            "encoding": {
                "type": "string",
                "description": (
                    "Explicit encoding (e.g. 'gb18030' / 'utf-16' / 'latin-1'). "
                    "Overrides default UTF-8 strict. Use when 用户 said the file is legacy CJK."
                ),
            },
        },
        "required": ["path"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
