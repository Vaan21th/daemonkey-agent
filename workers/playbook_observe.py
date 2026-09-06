"""手册观察：load 之后的失败由 daemon 写回，不靠模型自觉。"""
from __future__ import annotations

import contextvars
import hashlib
import json
import re
from typing import Any

_EMPTY = frozenset({"", "无", "暂无", "暂无记录", "尚无失败路径"})
_SKIP_ERR = ("aborted", "用户取消", "unknown action", "必填", "not allowed")
_ST: contextvars.ContextVar[dict | None] = contextvars.ContextVar("pb_obs", default=None)


def begin() -> None:
    _ST.set({"loaded": [], "wrote": set()})


def _state() -> dict:
    st = _ST.get()
    if st is None:
        st = {"loaded": [], "wrote": set()}
        _ST.set(st)
    return st


def note_loaded(playbook_id: str) -> None:
    pid = (playbook_id or "").strip()
    if not pid:
        return
    loaded = _state()["loaded"]
    if pid not in loaded:
        loaded.append(pid)


def last_loaded() -> str:
    loaded = _state()["loaded"]
    return loaded[-1] if loaded else ""


def _err_fp(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())[:80]
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:12] if t else ""


def is_empty_experience(playbook_id: str) -> bool:
    from workers.playbook_case import case_snippets
    trial = (case_snippets(playbook_id).get("trial") or "").strip()
    body = trial[2:].strip() if trial.startswith("- ") else trial
    # 时间戳 · 正文
    if " · " in body:
        body = body.split(" · ", 1)[-1].strip()
    return body in _EMPTY


def real_trials(playbook_id: str, n: int = 3) -> list[str]:
    """去掉占位，只留真失败。正文在时间戳后面。"""
    from workers.playbook_case import split_sections
    from workers.playbooks import load_playbook
    loaded = load_playbook(playbook_id=playbook_id)
    if loaded.get("error"):
        return []
    rows = []
    for ln in (split_sections(loaded.get("content") or "").get("试错过") or "").splitlines():
        t = ln.strip().lstrip("- ").strip()
        if " · " in t:
            t = t.split(" · ", 1)[-1].strip()
        if t in _EMPTY or not t:
            continue
        rows.append(t)
    return rows[-n:]


def avoid_block(playbook_id: str) -> str:
    rows = real_trials(playbook_id)
    if not rows:
        return ""
    lines = [
        "【试错过是硬约束】这是本机上次为你踩过的路，禁止再走。"
        "步骤和试错过冲突时听试错过。回复必须点出避开了哪条。"
    ]
    for r in rows:
        lines.append(f"- {r}")
    return "\n".join(lines)


def downrank_empty(candidates: list[dict]) -> list[dict]:
    """空经验（只有占位试错过）排到后面，不占有真实试错的名额。"""
    if not candidates:
        return candidates
    real, hollow = [], []
    for pb in candidates:
        (hollow if is_empty_experience(pb.get("id") or "") else real).append(pb)
    return real + hollow


def note_extract(playbook_id: str, trials: str) -> None:
    from workers.playbooks import _INDEX_LOCK, _load_index, _save_index
    pid = (playbook_id or "").strip()
    if not pid:
        return
    hollow = (trials or "").strip() in _EMPTY
    with _INDEX_LOCK:
        index = _load_index()
        meta = index.get("playbooks", {}).get(pid)
        if not meta:
            return
        if hollow:
            meta["empty_trials"] = True
            meta["empty_streak"] = int(meta.get("empty_streak") or 0) + 1
        else:
            meta["empty_trials"] = False
            meta["empty_streak"] = 0
        _save_index(index)


def clear_empty_flag(playbook_id: str) -> None:
    from workers.playbooks import _INDEX_LOCK, _load_index, _save_index
    pid = (playbook_id or "").strip()
    if not pid:
        return
    with _INDEX_LOCK:
        index = _load_index()
        meta = index.get("playbooks", {}).get(pid)
        if not meta:
            return
        meta["empty_trials"] = False
        meta["empty_streak"] = 0
        _save_index(index)


def _unwrap(name: str, args: dict) -> tuple[str, dict]:
    if name != "catalog_call":
        return name, args
    inner = str(args.get("name") or "").strip()
    inner_args = args.get("args")
    if isinstance(inner_args, str) and inner_args.strip():
        try:
            parsed = json.loads(inner_args)
            inner_args = parsed if isinstance(parsed, dict) else {}
        except Exception:
            return name, args
    if not inner or not isinstance(inner_args, dict):
        return name, args
    return inner, inner_args


def _trial_text(playbook_id: str) -> str:
    from workers.playbook_case import split_sections
    from workers.playbooks import load_playbook
    loaded = load_playbook(playbook_id=playbook_id)
    if loaded.get("error"):
        return ""
    return split_sections(loaded.get("content") or "").get("试错过") or ""


def _tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in re.finditer(r"[0-9A-Za-z]{4,}|[\u4e00-\u9fff]{2,}", text or "")}


def _book_tokens(playbook_id: str) -> set[str]:
    from workers.playbook_case import split_sections
    from workers.playbooks import load_playbook
    loaded = load_playbook(playbook_id=playbook_id)
    meta = loaded.get("meta") or {}
    sec = split_sections(loaded.get("content") or "")
    blob = " ".join([
        playbook_id, meta.get("slug") or "", loaded.get("title") or "",
        sec.get("问题") or "",
    ])
    return _tokens(blob)


def pick_writeback_id(error: str, args: dict | None = None) -> str:
    """多册 load 过：看失败正文/参数跟哪本重合。重合不上宁可不写，别串册。"""
    loaded = list(_state()["loaded"])
    if not loaded:
        return ""
    if len(loaded) == 1:
        return loaded[0]
    args = args if isinstance(args, dict) else {}
    hay = _tokens(" ".join(
        [error] + [str(args.get(k) or "") for k in ("code", "command", "path", "cwd")]
    ))
    scored = [(len(hay & _book_tokens(pid)), pid) for pid in loaded]
    best = max((n for n, _ in scored), default=0)
    if best <= 0:
        return ""
    tied = [pid for n, pid in scored if n == best]
    return tied[-1]


def already_noted(playbook_id: str, compact: str) -> bool:
    if not compact:
        return False
    return compact in _trial_text(playbook_id)


def _fail_blob(result: Any) -> str:
    err = str(getattr(result, "error", "") or "").strip()
    out = str(getattr(result, "output", "") or "").strip()
    if out and (not err or re.match(r"(?i)exit code \d+$", err)):
        return f"{err} {out}".strip()
    return err or out


def _compact_fail(text: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    m = re.search(
        r"((?:RuntimeError|ValueError|TypeError|OSError|FileNotFoundError|"
        r"KeyError|Exception): .{1,120})",
        t,
    )
    if m:
        return m.group(1).strip()[:160]
    return t[:160]


def _should_skip_fail(name: str, err: str) -> bool:
    if not name or not err:
        return True
    low = err.lower()
    if any(s in err or s in low for s in _SKIP_ERR):
        return True
    from workers.closure_check import SIDE_EFFECT_TOOLS
    return name not in SIDE_EFFECT_TOOLS


def auto_writeback(tool_name: str, error: str, args: dict | None = None) -> dict:
    """本轮 load 过手册之后，关键步骤失败 → 写回对得上的那本。每册每轮最多一次。"""
    if _should_skip_fail(tool_name, error):
        return {"ok": False, "skipped": True}
    pid = pick_writeback_id(error, args)
    if not pid:
        return {"ok": False, "skipped": True, "reason": "ambiguous"}
    compact = _compact_fail(error)
    fp = _err_fp(f"{tool_name}:{compact}")
    wrote = _state()["wrote"]
    key = f"{pid}:{fp}"
    if key in wrote or pid in {x.split(":", 1)[0] for x in wrote}:
        return {"ok": False, "skipped": True, "reason": "already"}
    if already_noted(pid, compact):
        return {"ok": False, "skipped": True, "reason": "dup"}
    from workers.playbook_case import append_trial
    note = f"自动 · {tool_name} 失败: {compact}"
    res = append_trial(pid, note)
    if res.get("ok"):
        wrote.add(key)
        clear_empty_flag(pid)
    return res


def observe_tool(spec: Any, args: dict | None, result: Any) -> None:
    name = getattr(spec, "name", "") or ""
    args = args if isinstance(args, dict) else {}
    name, args = _unwrap(name, args)
    ok = bool(getattr(result, "ok", False))
    if name == "extract_playbook" and (args.get("action") or "").lower() == "load" and ok:
        note_loaded(str(args.get("playbook_id") or ""))
        return
    if ok or name == "extract_playbook":
        return
    auto_writeback(name, _fail_blob(result), args)


def propose_cluster_hint(fresh: list[dict], message: str = "") -> str:
    """同簇 ≥3 提出蒸馏议，不入库、不写 how_now。"""
    from workers.playbook_cluster import peers_of
    from workers.playbook_distill import upsert_proposal
    if len(fresh) < 1:
        return ""
    pb = fresh[0]
    slug = pb.get("slug") or ""
    peers = peers_of(slug, query=message, k=5)
    leaf_ids = [pb.get("id") or ""]
    leaf_ids += [p.get("id") or "" for p in peers]
    leaf_ids = [x for x in leaf_ids if x]
    rec = upsert_proposal(leaf_ids, title=f"建议蒸馏 · {pb.get('title') or slug}")
    if not rec:
        return ""
    return (
        f"  同簇已有 {len(rec.get('leaf_ids') or [])} 份，已提出蒸馏 "
        f"proposal_id={rec['id']}。补 how_now 用 distill，确认前不入库。叶子未动。"
    )
