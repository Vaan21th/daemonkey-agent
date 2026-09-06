"""真会话金丝雀：提问 → 真 FTS → load → 失败写回 → 再问同一句。

不打总分。口号只看用户能不能感觉到「这本手册因你这次失败变了」。
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = "http://127.0.0.1:7860"
MARK = "canaryavoid20260906"
FAIL = "canary_avoid_20260906"
NATURAL = (
    f"Windows 金丝雀换行保真 {MARK} 写文件总把 LF 吃成 CRLF，"
    "按已有操作手册处理。"
)
Q2 = NATURAL


def _token() -> str:
    env = ROOT / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPUS_API_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("没有 OPUS_API_TOKEN")


H = {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


def _seed() -> dict:
    from workers.playbook_case import save_case
    return save_case(
        title=f"金丝雀换行保真 {MARK}",
        task_type="setup",
        steps=(
            "1. 用 python_exec 执行：raise RuntimeError('" + FAIL + "')\n"
            "2. 不要调用 extract_playbook action=feedback"
        ),
        problem=f"Windows 写文件把 LF 吃成 CRLF · {MARK}",
        trials="尚无失败路径",
        session_id="sess-slogan-avoid",
        quote=NATURAL,
        tags=["canary", MARK],
    )


def _inject(q: str) -> str:
    from workers.closure_check import relevant_playbooks
    return relevant_playbooks(q, limit=2, session_id="")


def _chat(message: str, sid: str) -> dict:
    r = requests.post(
        BASE + "/chat",
        headers=H,
        json={"message": message, "session_id": sid, "auto_confirm": "confirm"},
        timeout=240,
    )
    r.raise_for_status()
    return r.json()


def _tools(sid: str) -> list[dict]:
    rows = []
    path = ROOT / "sessions" / f"{sid}.jsonl"
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        meta = rec.get("meta") or {}
        for tc in meta.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw = fn.get("arguments") or tc.get("arguments") or tc.get("args") or {}
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except json.JSONDecodeError:
                    raw = {"_raw": raw}
            name = fn.get("name") or tc.get("name") or ""
            args = raw if isinstance(raw, dict) else {}
            if name == "catalog_call" and isinstance(args.get("args"), dict):
                name = str(args.get("name") or name)
                args = args.get("args") or {}
            rows.append({"name": name, "args": args})
    return rows


def _load_logged(pid: str, after_ts: str) -> bool:
    p = ROOT / "data" / "runtime" / "inject_used.jsonl"
    if not p.exists():
        return False
    for line in p.read_text(encoding="utf-8").splitlines():
        if pid not in line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (rec.get("ts") or "") >= after_ts and rec.get("playbook_id") == pid:
            return True
    return False


def _loaded(tools: list[dict], pid: str) -> bool:
    for t in tools:
        args = t.get("args")
        if t.get("name") != "extract_playbook" or not isinstance(args, dict):
            continue
        if (args.get("action") or "").lower() != "load":
            continue
        if pid in str(args.get("playbook_id") or "") or MARK in str(args):
            return True
    return False


def _feedback(tools: list[dict]) -> bool:
    for t in tools:
        args = t.get("args")
        if t.get("name") == "extract_playbook" and isinstance(args, dict):
            if (args.get("action") or "").lower() == "feedback":
                return True
    return False


def _usage(body: dict) -> dict:
    u = body.get("usage") or {}
    return {
        "in": int(u.get("input_tokens") or 0),
        "out": int(u.get("output_tokens") or 0),
        "cache": int(u.get("cache_read_tokens") or 0),
    }


def _add(a: dict, b: dict) -> dict:
    return {k: int(a.get(k) or 0) + int(b.get(k) or 0) for k in ("in", "out", "cache")}


def _reran_fail(tools: list[dict]) -> bool:
    for t in tools:
        if t.get("name") == "python_exec" and FAIL in str(t.get("args") or ""):
            return True
    return False


def main() -> int:
    ping = requests.get(BASE + "/api/ping-test", timeout=5)
    if ping.status_code != 200:
        raise SystemExit("daemon 没起来")
    main_pb = _seed()
    pid = main_pb["id"]
    raw_path = ROOT / "data" / "playbooks" / f"{main_pb['slug']}.md"
    before = _inject(NATURAL)
    live_fts = pid in before or MARK in before
    tag = time.strftime("%H%M%S")
    started = datetime.now(timezone.utc).isoformat()
    sid1 = f"api-avoid-t1-{tag}"
    sid2 = f"api-avoid-t2-{tag}"
    turn1 = _chat(NATURAL, sid1)
    tools1 = _tools(sid1)
    loaded = _loaded(tools1, pid) or _load_logged(pid, started)
    used = _usage(turn1)
    raw_after = raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""
    wrote = "自动 · python_exec 失败" in raw_after and FAIL in raw_after
    after = _inject(NATURAL)
    recall = "硬约束" in after and ("自动 ·" in after or FAIL in after)
    turn2 = _chat(Q2, sid2)
    used = _add(used, _usage(turn2))
    tools2 = _tools(sid2)
    reply2 = turn2.get("reply") or ""
    avoided = loaded and wrote and not _reran_fail(tools2)
    cited = any(x in reply2 for x in (FAIL, "试错过", "避开", "硬约束", "禁止再走"))
    evidence = {
        "live_fts_hit": live_fts,
        "model_loaded": loaded,
        "auto_writeback_kept_exception": wrote,
        "feedback_called": _feedback(tools1),
        "next_recall_hard_constraint": recall,
        "t2_avoided_same_fail": avoided,
        "t2_cited_trial": cited,
    }
    if not live_fts:
        slogan = "未达标 · 真 FTS 没召回"
    elif not loaded:
        slogan = "未达标 · 真会话没 load"
    elif not wrote:
        slogan = "未达标 · 写回没留下失败正文"
    elif _feedback(tools1):
        slogan = "未达标 · 还靠 feedback"
    elif not recall:
        slogan = "未达标 · 下次注入没有硬约束"
    elif not avoided:
        slogan = "未达标 · 看见了还照走同一条失败"
    elif not cited:
        slogan = "避开了但没说出来 · 口号未满"
    else:
        slogan = "手册环这一刀用户可感知 · 不代表整产品已落地"
    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "standard": "只为你而成长 · 真会话",
        "playbook_id": pid,
        "sessions": {"t1": sid1, "t2": sid2},
        "usage": used,
        "evidence": evidence,
        "slogan": slogan,
        "reply2_head": reply2[:280],
        "inject_after_head": after[:400],
    }
    out = ROOT / "data" / "runtime" / "playbook_slogan_live.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
