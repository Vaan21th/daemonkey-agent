"""中栏批注改 Office：按意图伸手，别让 Flash 先回看再搜记忆。"""
from __future__ import annotations

import re

_HEADS = ("中栏画布上批了", "【中栏批注】")
_FILE = re.compile(r"文件：\s*(\S+)")
_PATH = re.compile(r"path=\s*(\S+)", re.I)
_OFFICE = re.compile(r"\.(pptx?|docx?|xlsx?)$", re.I)
_NUM = re.compile(r"^\d+\.\s*")
_LLM_LINE = re.compile(
    r"\bextend_office\b|body=按批注写新增页|body=按批注把这一页改成",
    re.I,
)
_TOOLS = frozenset({
    "revise_office", "extend_office", "illustrate_office", "inspect_office",
})
_HINT = (
    "\n中栏批注按意图伸手："
    "圈字改句 → revise_office(excerpt, body=那一句)；"
    "某页加图 → illustrate_office(page, x, y, prompt)；"
    "某页后插页 → extend_office(after=页码, body=新页 markdown)；"
    "换这一页版式 → revise_office(page, body=整页 markdown，带 <!-- layout -->)。"
    "禁止 generate_presentation 整份重出。能留的原页必须留下。\n"
)


def office_note_lock(message: str) -> bool:
    text = message or ""
    if not any(h in text for h in _HEADS):
        return False
    for rx in (_PATH, _FILE):
        m = rx.search(text)
        if m and _OFFICE.search(m.group(1)):
            return True
    return False


_LINE = re.compile(
    r"revise_office\s+path=(?P<path>\S+)"
    r"(?:\s+page=(?P<page>\d+))?"
    r"(?:\s+x=[\d.]+)?"
    r"(?:\s+y=[\d.]+)?"
    r"(?:\s+excerpt=(?P<excerpt>.+?))?"
    r"\s+body=(?P<body>.+?)\s*$",
    re.I,
)
_ILLUST = re.compile(
    r"illustrate_office\s+path=(?P<path>\S+)"
    r"\s+page=(?P<page>\d+)"
    r"(?:\s+x=(?P<x>[\d.]+))?"
    r"(?:\s+y=(?P<y>[\d.]+))?"
    r"(?:\s+w=(?P<w>[\d.]+))?"
    r"(?:\s+image=(?P<image>\S+))?"
    r"(?:\s+prompt=(?P<prompt>.+))?"
    r"\s*$",
    re.I,
)
_OPEN = re.compile(r"[ \t]*\[\[DK-OPEN\]\](\S+)[ \t]*")


def take_open_marks(text: str) -> tuple[str, list[str]]:
    """剥掉回复里的 [[DK-OPEN]]，留给前端铺中栏。"""
    paths: list[str] = []

    def _grab(m: re.Match) -> str:
        paths.append((m.group(1) or "").replace("\\", "/"))
        return ""

    cleaned = _OPEN.sub(_grab, text or "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, [p for p in paths if p]


def apply_office_note_gate(message: str, thinking: str | None) -> tuple[set[str] | None, str | None, str]:
    """返回 (allowed_tools 或 None, thinking, 追加到 system_suffix 的一句)。"""
    if not office_note_lock(message):
        return None, thinking, ""
    tv = (thinking or "auto").strip().lower() or "auto"
    if tv == "auto":
        thinking = "off"
    return set(_TOOLS), thinking, _HINT


def _instr_lines(message: str) -> list[str]:
    return [raw.strip() for raw in (message or "").splitlines() if _NUM.match(raw.strip())]


def needs_llm_notes(message: str) -> bool:
    """插页 / 换版式 / 加图缺 prompt 才过模型。提示词里的工具名不算。"""
    for line in _instr_lines(message):
        if _LLM_LINE.search(line):
            return True
        if re.search(r"\billustrate_office\b", line, re.I):
            if not re.search(r"\b(?:prompt|image)=", line, re.I):
                return True
    return False


def parse_illust_calls(message: str) -> list[dict]:
    out: list[dict] = []
    for line in _instr_lines(message):
        m = _ILLUST.search(line)
        if not m:
            continue
        prompt = (m.group("prompt") or "").strip()
        image = (m.group("image") or "").strip()
        if " image=" in prompt and not image:
            prompt, image = prompt.rsplit(" image=", 1)
            prompt, image = prompt.strip(), image.strip()
        if not prompt and not image:
            return []
        item = {"path": m.group("path"), "page": int(m.group("page"))}
        if m.group("x"):
            item["x"] = float(m.group("x"))
        if m.group("y"):
            item["y"] = float(m.group("y"))
        if m.group("w"):
            item["w"] = float(m.group("w"))
        if image:
            item["image"] = image
        if prompt:
            item["prompt"] = prompt
        out.append(item)
    return out


def parse_note_calls(message: str) -> list[dict]:
    if needs_llm_notes(message):
        return []
    out: list[dict] = []
    for raw in (message or "").splitlines():
        m = _LINE.search(raw.strip())
        if not m:
            continue
        body = (m.group("body") or "").strip()
        excerpt = (m.group("excerpt") or "").strip()
        if not excerpt or not body or body.startswith("按批注写出"):
            return []
        item = {"path": m.group("path"), "excerpt": excerpt, "body": body}
        if m.group("page"):
            item["page"] = int(m.group("page"))
        out.append(item)
    return out


def try_apply_office_notes(message: str) -> str | None:
    """圈字 / 加图参数齐了就直接改。插页和换版式仍交给模型写正文。"""
    if not office_note_lock(message):
        return None
    if needs_llm_notes(message):
        return None
    illusts = parse_illust_calls(message)
    calls = parse_note_calls(message)
    if not illusts and not calls:
        return None
    chunks: list[str] = []
    if illusts:
        from agent_tools.illustrate_office import _run as _illust

        path = illusts[0]["path"]
        for c in illusts:
            args = dict(c)
            args["path"] = path
            r = _illust(args)
            if not r.ok:
                chunks.append(r.error or "illustrate_office 失败")
                break
            chunks.append(r.output or "")
            hit = _OPEN.search(r.output or "")
            if hit:
                path = hit.group(1)
    if calls:
        from agent_tools.revise_office import _run

        path = calls[0]["path"]
        for c in calls:
            args = dict(c)
            args["path"] = path
            r = _run(args)
            if not r.ok:
                chunks.append(r.error or "revise_office 失败")
                break
            chunks.append(r.output or "")
            hit = _OPEN.search(r.output or "")
            if hit:
                path = hit.group(1)
    return "\n\n".join(chunks).strip() or None
