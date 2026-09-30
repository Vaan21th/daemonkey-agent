"""
workers/doc_ingest.py
=====================

把本地文档抽成统一 markdown 文本 —— 知识库入库的第一步(眼睛)。

支持: .md/.markdown/.txt 直读 · .docx(python-docx) · .pptx(python-pptx) · .pdf(pypdf 文本型)
不做: OCR(扫描件返回空并提示) · 图片 · 复杂表格结构化(表格按行拼可读文本)

设计取向:尽量保留 / 造出 `## 小节` 标题(PDF 按页 · PPTX 按幻灯片),
让 memory_index._chunk_markdown 能按节切块 · 检索命中时能 cite 回"第 N 页 / 第 N 页幻灯片"。

复用现有地基:PDF 走 pypdf(与 agent_tools/pdf_read.py 同款)· 不重造轮子。
"""

from __future__ import annotations

import re
from pathlib import Path

SUPPORTED_EXT = {
    # 纯文本族
    ".md", ".markdown", ".txt", ".text", ".log", ".rst", ".org",
    # Office
    ".docx", ".pptx", ".xlsx", ".xlsm",
    # 表格 / 数据
    ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml",
    # 网页
    ".html", ".htm",
    # 文档
    ".pdf",
}
MAX_BYTES = 50 * 1024 * 1024  # 50MB 上限,和 pdf_read 一致


class IngestError(Exception):
    """抽取失败(格式不支持 / 缺依赖 / 扫描件无文字 / 解析炸)——调用方给可读提示。"""


def _clean(raw: str) -> str:
    """折叠多余空白 · 去行首缩进 · 三连空行压成两个。"""
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n[ \t]+", "\n", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def _cjk_score(s: str) -> float:
    """一段文本「像不像中文」的得分 · 用于在几个解码候选里选最像的那个。

    为什么不直接用 charset_normalizer 的 best()：它按统计模型挑，样本短（几行中文 txt）
    时很容易猜成韩文/日文 —— 实测 "GBK 编码中文测试" 被解成 "긍쯤櫓匡꿎桿"。
    中文环境的实际分布里，中文字符占比才是最好的判据。
    """
    if not s:
        return -1.0
    cjk = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    # 替换符/控制符是解码失败的强信号，重罚
    bad = sum(1 for ch in s if ch == "\ufffd" or (ord(ch) < 32 and ch not in "\n\r\t"))
    return (cjk - bad * 3) / max(len(s), 1)


def _from_text(path: Path) -> str:
    """读纯文本 · 自动认编码。

    2026-10-01 BRO「我试了拖拽，txt 的不支持？？」—— 真因就在这行:
    以前是 read_text(encoding="utf-8", errors="replace") 硬按 UTF-8 读,
    中文 Windows 记事本另存的 GBK/GB18030 txt 会整篇变乱码,
    再被 extract() 末尾的「没抽到文字」档回去 —— 看起来就像「txt 不支持」。

    策略：① BOM 最确定 先吃 ② 严格 UTF-8 能过就过
    ③ 过不了就让 gb18030 与 charset_normalizer 两个候选比「中文占比」，谁像中文用谁。
    """
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass

    cands: list[str] = []
    try:
        cands.append(raw.decode("gb18030"))
    except UnicodeDecodeError:      # noqa: PERF203 — 单个候选失败不影响其他
        pass
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(raw).best()
        if best is not None:
            cands.append(str(best))
    except Exception:  # noqa: BLE001
        pass
    if cands:
        return max(cands, key=_cjk_score)
    return raw.decode("gb18030", errors="replace")


def _from_csv(path: Path) -> str:
    """CSV/TSV → 可读文本 · 自动 sniff 分隔符。"""
    import csv
    import io

    text = _from_text(path)
    try:
        sep = csv.Sniffer().sniff(text[:4096], delimiters=",\t;|").delimiter
    except Exception:  # noqa: BLE001 — 猜不出来按后缀给默认值
        sep = "\t" if path.suffix.lower() == ".tsv" else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=sep))
    if not rows:
        return ""
    head = rows[0]
    out: list[str] = []
    for row in rows[1:]:
        # 写成「表头: 值」而不是裸拼列 —— 检索命中后能看懂每列是什么
        pairs = [f"{head[i] if i < len(head) else f'第{i + 1}列'}: {v}"
                 for i, v in enumerate(row) if str(v).strip()]
        if pairs:
            out.append(" · ".join(pairs))
    if not out:                       # 只有表头就只摆表头
        out = [" | ".join(str(c) for c in head)]
    return f"CSV 共 {max(len(rows) - 1, 0)} 行\n" + "\n".join(out)


def _from_xlsx(path: Path) -> str:
    """Excel → 每个 sheet 一节 · 同样用「表头: 值」写法（检索友好）。"""
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    try:
        out: list[str] = []
        for ws in wb.worksheets:
            out.append(f"\n## {ws.title}")
            rows = [r for r in ws.iter_rows(values_only=True)
                    if any(c is not None and str(c).strip() for c in r)]
            if not rows:
                out.append("(空表)")
                continue
            head = [str(c) if c is not None else "" for c in rows[0]]
            for row in rows[1:]:
                pairs = [f"{head[i] or f'第{i + 1}列'}: {c}"
                         for i, c in enumerate(row) if c is not None and str(c).strip()]
                if pairs:
                    out.append(" · ".join(pairs))
            out.append(f"(共 {max(len(rows) - 1, 0)} 行)")
        return "\n".join(out)
    finally:
        # read_only 的工作簿一直攥着底层 zip 句柄；异常路径上也得关，否则 Windows 上文件被锁。
        # （IngestError 会 from exc 保留异常链，wb 随栈帧存活，靠末尾 try/except 兜底是兜不住的。）
        try:
            wb.close()
        except Exception:  # noqa: BLE001
            pass


def _from_html(path: Path) -> str:
    """HTML → 正文文本 · 内置正则去标签（不引 bs4，纯净版少一个依赖）。
    保留 h1-h3 层级和段落换行，让 _chunk_markdown 还能按节切。
    """
    import html as _html
    import re as _re

    raw = _from_text(path)
    raw = _re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</(script|style|noscript|svg)>", " ", raw)
    raw = _re.sub(r"(?is)<h1[^>]*>", "\n# ", raw)
    raw = _re.sub(r"(?is)<h2[^>]*>", "\n## ", raw)
    raw = _re.sub(r"(?is)<h3[^>]*>", "\n### ", raw)
    raw = _re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = _re.sub(r"(?i)</(p|div|li|tr|section|article|table|h1|h2|h3|h4|h5|h6)>", "\n", raw)
    raw = _re.sub(r"(?s)<[^>]+>", " ", raw)
    return _html.unescape(raw)


def _from_docx(path: Path) -> str:
    import docx  # python-docx

    doc = docx.Document(str(path))
    lines: list[str] = []
    for para in doc.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        style = (para.style.name if para.style else "") or ""
        if style.lower().startswith("heading"):
            digits = "".join(ch for ch in style if ch.isdigit())
            level = min(int(digits), 4) if digits else 2
            lines.append(f"\n{'#' * level} {text}")
        else:
            lines.append(text)
    for table in doc.tables:
        for row in table.rows:
            cells = [(c.text or "").strip() for c in row.cells]
            if any(cells):
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _from_pptx(path: Path) -> str:
    from pptx import Presentation

    prs = Presentation(str(path))
    out: list[str] = []
    for i, slide in enumerate(prs.slides, 1):
        out.append(f"\n## 第 {i} 页幻灯片")
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            for para in shape.text_frame.paragraphs:
                text = "".join(run.text for run in para.runs).strip()
                if text:
                    out.append(text)
    return "\n".join(out)


def _from_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001 — 任何解密失败都当加密件挡回
            raise IngestError("PDF 加密/有密码 · 知识库不支持自动破解") from exc
    out: list[str] = []
    for i, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 — 单页炸不连累整篇
            text = ""
        text = _clean(text)
        out.append(f"\n## 第 {i} 页\n{text}")
    return "\n".join(out)


def _dispatch(ext: str, path: Path) -> tuple[str, str]:
    """按扩展名分发抽取 · 返回 (text, doc_type)。"""
    if ext in (".md", ".markdown"):
        return _from_text(path), "md"
    if ext in (".txt", ".text", ".log", ".rst", ".org"):
        return _from_text(path), "txt"
    if ext in (".csv", ".tsv"):
        return _from_csv(path), "csv"
    if ext in (".xlsx", ".xlsm"):
        return _from_xlsx(path), "xlsx"
    if ext in (".html", ".htm"):
        return _from_html(path), "html"
    if ext in (".json", ".yaml", ".yml", ".xml"):
        return _from_text(path), "text"
    if ext == ".docx":
        return _from_docx(path), "docx"
    if ext == ".pptx":
        return _from_pptx(path), "pptx"
    if ext == ".pdf":
        return _from_pdf(path), "pdf"
    raise IngestError(f"暂不支持的格式 {ext}")


def extract(path: str | Path) -> tuple[str, str, str]:
    """抽本地文档为 markdown 文本。

    Returns: (title, markdown_text, doc_type)
    Raises: IngestError —— 文件不存在 / 格式不支持 / 过大 / 缺依赖 / 无文字(扫描件)。
    """
    p = Path(path)
    if not p.is_absolute():
        p = Path.cwd() / p
    if not p.exists() or not p.is_file():
        raise IngestError(f"文件不存在或不是文件: {p}")

    ext = p.suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise IngestError(
            f"暂不支持 {ext or '（没有扩展名）'} · 现在支持 "
            "md / txt / log / rst / pdf / docx / pptx / xlsx / csv / json / yaml / xml / html"
        )
    if p.stat().st_size > MAX_BYTES:
        raise IngestError(f"文件过大 (>{MAX_BYTES // 1024 // 1024}MB) · 拆开后再灌")

    try:
        text, doc_type = _dispatch(ext, p)
    except IngestError:
        raise
    except ImportError as exc:
        raise IngestError(f"缺少解析依赖: {exc} · pip install 后重试") from exc
    except Exception as exc:  # noqa: BLE001 — 收敛成可读错误交给上层
        raise IngestError(f"解析失败: {type(exc).__name__}: {exc}") from exc

    text = _clean(text)
    if len(text.strip()) < 5:
        raise IngestError(
            "没抽到文字 · 大概率是扫描件 / 图片型文档 · 需要 OCR(暂未支持)"
        )
    return p.stem, text, doc_type
