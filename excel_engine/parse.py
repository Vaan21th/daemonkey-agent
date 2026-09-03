"""markdown 表 / 结构化 sheets → [{name, headers, rows}]。"""
from __future__ import annotations

import re

_SPLIT = re.compile(r"\n---\n")
_H1 = re.compile(r"^#{1,3}\s+(.+)$")
_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_NUM = re.compile(r"^-?\d+$")
_FLOAT = re.compile(r"^-?\d+\.\d+$")


def _cell(raw: str):
    text = (raw or "").strip()
    if not text:
        return ""
    if text.startswith("="):
        return text
    if _NUM.match(text):
        try:
            return int(text)
        except ValueError:
            return text
    if _FLOAT.match(text):
        try:
            return float(text)
        except ValueError:
            return text
    return text


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _table_from_lines(lines: list[str]) -> tuple[list[str], list[list]] | None:
    rows_raw = [ln for ln in lines if "|" in ln]
    if len(rows_raw) < 2:
        return None
    header = _split_row(rows_raw[0])
    body_src = rows_raw[1:]
    if body_src and _SEP.match(body_src[0]):
        body_src = body_src[1:]
    if not header or not any(header):
        return None
    rows = []
    width = len(header)
    for ln in body_src:
        cells = [_cell(c) for c in _split_row(ln)]
        if len(cells) < width:
            cells += [""] * (width - len(cells))
        rows.append(cells[:width])
    return header, rows


def parse_markdown(body: str) -> list[dict]:
    text = (body or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    chunks = [c.strip() for c in _SPLIT.split(text) if c.strip()]
    out: list[dict] = []
    for i, chunk in enumerate(chunks, 1):
        lines = chunk.splitlines()
        name = f"Sheet{i}"
        table_lines = []
        for ln in lines:
            m = _H1.match(ln.strip())
            if m and not table_lines:
                name = m.group(1).strip()[:31] or name
                continue
            table_lines.append(ln)
        parsed = _table_from_lines(table_lines)
        if not parsed:
            continue
        headers, rows = parsed
        out.append({"name": name, "headers": headers, "rows": rows})
    return out


def _norm_sheet(raw, index: int) -> dict | None:
    if not isinstance(raw, dict):
        return None
    headers = raw.get("headers") or raw.get("cols") or []
    rows = raw.get("rows") or []
    if not isinstance(headers, list) or not headers:
        return None
    headers = [str(h).strip() or f"C{i+1}" for i, h in enumerate(headers)]
    width = len(headers)
    clean = []
    if not isinstance(rows, list):
        rows = []
    for row in rows:
        if isinstance(row, dict):
            cells = [_cell(str(row.get(h, ""))) for h in headers]
        elif isinstance(row, list):
            cells = [_cell("" if c is None else str(c)) for c in row]
        else:
            continue
        if len(cells) < width:
            cells += [""] * (width - len(cells))
        clean.append(cells[:width])
    name = str(raw.get("name") or raw.get("title") or f"Sheet{index}")[:31]
    return {"name": name or f"Sheet{index}", "headers": headers, "rows": clean}


def parse_sheets(body: str | None = None, sheets=None) -> list[dict]:
    if isinstance(sheets, list) and sheets:
        out = []
        for i, raw in enumerate(sheets, 1):
            item = _norm_sheet(raw, i)
            if item:
                out.append(item)
        if out:
            return out
    return parse_markdown(body or "")
