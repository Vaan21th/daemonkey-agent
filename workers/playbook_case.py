"""经验个案：问题 / 做法 / 试错过 / 出处。只写 data/playbooks/。"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

SECTIONS = ("前置条件", "问题", "步骤", "试错过", "常见坑", "经验教训", "出处")
REQUIRED = ("问题", "步骤", "试错过", "出处")
_PLACEHOLDER = frozenset({"", "无", "暂无", "暂无记录", "无特殊前置条件"})
_PLAYBOOK_MARK = re.compile(r"(?m)^##\s+(步骤|试错过|常见坑)\s*$")


def split_sections(text: str) -> dict[str, str]:
    fm_end_m = re.search(r"(?m)^---\s*$", (text or "")[4:])
    fm_end = (fm_end_m.start() + 4) if fm_end_m else -1
    body = text[fm_end + 4:] if fm_end >= 0 else (text or "")
    sections: dict[str, str] = {}
    cur = None
    buf: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m and m.group(1).strip() in SECTIONS:
            if cur:
                sections[cur] = "\n".join(buf).strip()
            cur = m.group(1).strip()
            buf = []
        elif cur is not None:
            buf.append(line)
    if cur:
        sections[cur] = "\n".join(buf).strip()
    return sections


def render_markdown(
    title: str,
    task_type: str,
    sections: dict[str, str],
    *,
    tags: list[str] | None = None,
    created_at: str = "",
    used_count: int = 0,
    version: int = 1,
    comment: str = "抽取",
) -> str:
    now = datetime.now(timezone.utc)
    created = created_at or now.isoformat()
    safe = str(title).strip().replace("\n", " ").replace("\r", " ").replace('"', '\\"')
    tags_yaml = f"tags: [{', '.join(tags)}]\n" if tags else ""
    fm = (
        "---\n"
        f'title: "{safe}"\n'
        f"task_type: {task_type}\n"
        f"created_at: {created}\n"
        f"used_count: {used_count}\n"
        f"agentskills_version: {version}\n"
        f"{tags_yaml}"
        "---\n\n"
    )
    parts = [fm, f"# {title}\n\n", f"<!-- playbook · 由 OPUS 在 {now.strftime('%Y-%m-%d %H:%M UTC')} {comment} -->\n\n"]
    for name in SECTIONS:
        body = (sections.get(name) or "").strip() or "暂无记录"
        parts.append(f"## {name}\n\n{body}\n\n")
    return "".join(parts)

def validate_integrity(content: str) -> dict:
    sec = split_sections(content)
    missing = [n for n in REQUIRED if (sec.get(n) or "").strip() in _PLACEHOLDER]
    src = sec.get("出处", "")
    source_ok = bool(re.search(r"(?i)(session|file|path|draft)\s*[:：]", src))
    if not source_ok:
        missing.append("出处(无 session/file/path)")
    return {"ok": not missing, "missing": missing, "sections": sec}


def source_block(session_id: str = "", quote: str = "", paths: list[str] | None = None) -> str:
    lines = []
    if session_id:
        lines.append(f"- session: {session_id}")
    if quote:
        lines.append(f"- quote: {quote.strip()[:240]}")
    for p in paths or []:
        rel = str(p).replace("\\", "/")
        lines.append(f"- file: {rel}")
    if not lines:
        lines.append("- session: unknown")
    return "\n".join(lines)


def save_case(
    title: str,
    task_type: str,
    steps: str,
    problem: str,
    trials: str,
    source: str = "",
    prerequisites: str = "",
    pitfalls: str = "",
    lessons: str = "",
    tags: list[str] | None = None,
    session_id: str = "",
    quote: str = "",
) -> dict:
    from workers.playbooks import save_playbook, _INDEX_LOCK, _load_index, _save_index

    src = (source or "").strip() or source_block(session_id, quote)
    if "file:" not in src:
        src = src + "\n- file: data/playbooks/_pending.md"
    sections = {
        "前置条件": prerequisites, "问题": problem, "步骤": steps,
        "试错过": trials, "常见坑": pitfalls, "经验教训": lessons, "出处": src,
    }
    preview = render_markdown(title, task_type, sections, tags=tags)
    gate = validate_integrity(preview)
    if not gate["ok"]:
        raise ValueError(f"个案四件套不齐: {', '.join(gate['missing'])}")
    pb = save_playbook(
        title=title, task_type=task_type, steps=steps,
        prerequisites=prerequisites, pitfalls=pitfalls, lessons=lessons, tags=tags,
    )
    path = Path(pb["path"])
    rel = f"data/playbooks/{path.name}"
    sections["出处"] = (source or "").strip() or source_block(session_id, quote)
    if "file:" not in sections["出处"]:
        sections["出处"] += f"\n- file: {rel}"
    content = render_markdown(title, task_type, sections, tags=tags)
    path.write_text(content, encoding="utf-8")
    with _INDEX_LOCK:
        index = _load_index()
        meta = index.get("playbooks", {}).get(pb["id"], {})
        meta["has_case"] = True
        meta["source_session"] = session_id or ""
        _save_index(index)
    try:
        from workers.memory_index import incremental_update
        incremental_update("skill", content, section=f"{pb['slug']}:{task_type}")
    except Exception:
        pass
    pb["path"] = str(path)
    return pb

def _tool(ok: bool, output: str = "", error: str = "") -> dict:
    return {"ok": ok, "output": output, "error": error}


def append_trial(playbook_id: str, note: str) -> dict:
    from workers.playbooks import PLAYBOOK_DIR, _INDEX_LOCK, load_playbook
    note = (note or "").strip()
    if not note:
        return {"ok": False, "error": "empty_note"}
    with _INDEX_LOCK:
        loaded = load_playbook(playbook_id=playbook_id)
        if loaded.get("error"):
            return {"ok": False, "error": loaded["error"]}
        meta = loaded.get("meta") or {}
        slug = meta.get("slug") or ""
        path = PLAYBOOK_DIR / f"{slug}.md"
        if not path.exists():
            return {"ok": False, "error": "file_missing"}
        raw = path.read_text(encoding="utf-8")
        sec = split_sections(raw)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        old = (sec.get("试错过") or "").strip()
        if old in _PLACEHOLDER:
            old = ""
        line = f"- {stamp} · {note}"
        body = f"{old}\n{line}".strip() if old else line
        if re.search(r"(?m)^## 试错过\s*$", raw):
            content = re.sub(
                r"(?ms)^## 试错过\s*\n.*?(?=^## |\Z)",
                f"## 试错过\n\n{body}\n\n",
                raw,
                count=1,
            )
        else:
            content = raw.rstrip() + f"\n\n## 试错过\n\n{body}\n"
        path.write_text(content, encoding="utf-8")
    try:
        from workers.memory_index import incremental_update
        incremental_update("skill", content, section=f"{slug}:{meta.get('task_type') or 'general'}")
    except Exception:
        pass
    return {"ok": True, "id": playbook_id, "path": str(path)}


def case_snippets(playbook_id: str, *, problem_n: int = 72, trial_n: int = 88) -> dict:
    from workers.playbooks import load_playbook
    loaded = load_playbook(playbook_id=playbook_id)
    if loaded.get("error"):
        return {"problem": "", "trial": "", "source": ""}
    sec = split_sections(loaded.get("content") or "")
    problem = " ".join((sec.get("问题") or "").split())
    trials = [ln.strip() for ln in (sec.get("试错过") or "").splitlines() if ln.strip()]
    last = trials[-1] if trials else ""
    return {
        "problem": problem[:problem_n],
        "trial": last[:trial_n],
        "source": (sec.get("出处") or "").strip(),
    }


def refuse_loose_playbook(path: Path, content: str = "") -> str | None:
    from workers.playbooks import PLAYBOOK_DIR, ROOT
    resolved = path.resolve()
    try:
        resolved.relative_to(PLAYBOOK_DIR.resolve())
        return "操作手册请用 extract_playbook（extract / revise / distill）。不要 write_file 写 data/playbooks。"
    except ValueError:
        pass
    try:
        rel = resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return None
    text = content or ""
    looks = bool(_PLAYBOOK_MARK.search(text)) or "<!-- playbook" in text
    if looks and path.suffix.lower() in {".md", ".markdown"}:
        return f"{rel} 像操作手册。手册只许进 data/playbooks/，用 extract_playbook 存。"
    return None


def extract_action(args: dict) -> dict:
    title = (args.get("title") or "").strip()
    steps = (args.get("steps") or "").strip()
    problem = (args.get("problem") or "").strip()
    trials = (args.get("trials") or "").strip()
    for key, val, hint in (
        ("title", title, "title 必填"),
        ("steps", steps, "steps 必填"),
        ("problem", problem, "problem 必填 · 写清这次在解什么"),
        ("trials", trials, "trials 必填 · 没有失败就写「尚无失败路径」"),
    ):
        if not val:
            return _tool(False, error=hint)
    sid = (args.get("source") or "").strip()
    session = ""
    quote = ""
    if sid.lower().startswith("session:"):
        session = sid.split(":", 1)[1].strip()
    elif re.search(r"(?i)session\s*[:：]", sid):
        session = sid
    else:
        quote = sid
        try:
            from agent_tools import current_session_id
            session = str(current_session_id() or "")
            if session.startswith("t"):
                session = ""
        except Exception:
            session = ""
    try:
        result = save_case(
            title=title,
            task_type=(args.get("task_type") or "general").strip(),
            steps=steps, problem=problem, trials=trials,
            source=sid if re.search(r"(?i)(session|file|path)\s*[:：]", sid) else "",
            prerequisites=(args.get("prerequisites") or "").strip(),
            pitfalls=(args.get("pitfalls") or "").strip(),
            lessons=(args.get("lessons") or "").strip(),
            tags=args.get("tags") or [],
            session_id=session, quote=quote,
        )
    except ValueError as e:
        return _tool(False, error=str(e))
    return _tool(
        True,
        output=(
            "playbook saved\n"
            f"  id: {result['id']}\n"
            f"  path: {result['path']}\n"
            f"  title: {title}\n"
            "  落点: data/playbooks/ · 四件套已齐\n"
        ),
    )


def feedback_action(args: dict) -> dict:
    pid = str(args.get("playbook_id") or "").strip()
    if not pid:
        return _tool(False, error="feedback 需要 playbook_id")
    from workers.playbooks import record_playbook_result
    res = record_playbook_result(pid, bool(args.get("success")), str(args.get("note") or "").strip())
    if not res:
        return _tool(False, error=f"playbook {pid} 不存在")
    st = res.get("stale_state", "正常")
    note = res.get("note") or ""
    extra = ""
    if (not args.get("success")) and note:
        wb = res.get("writeback") or {}
        if not wb.get("ok"):
            return _tool(False, error=f"索引记了失败，试错过没写上: {wb.get('error') or 'unknown'}")
        extra = " · 失败已写入「试错过」"
    return _tool(
        True,
        output=(
            f"已记录反馈 · {pid} · success={bool(args.get('success'))} · "
            f"状态 [{st}] · stale_hits={res.get('stale_hits', 0)} · "
            f"use_success={res.get('use_success', 0)} · use_fail={res.get('use_fail', 0)}"
            + (f" · note: {note}" if note else "") + extra
        ),
    )
