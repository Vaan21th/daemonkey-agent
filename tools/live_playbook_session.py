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
MARK = "canaryeol20260906"
FAIL = "canary_fake_result_20260906"
NATURAL = (
    f"Windows 金丝雀换行保真 {MARK} 写文件总把 LF 吃成 CRLF，"
    "按已有操作手册处理。"
)
EXPLICIT = (
    f"先用 extract_playbook action=load 加载标题含「金丝雀换行保真 {MARK}」的操作手册，"
    f"再按手册第一步用 python_exec 复现。不要绕过，不要 feedback。"
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
    steps = (
        "1. 用 python_exec 执行：raise RuntimeError('" + FAIL + "')\n"
        "2. 看到这个 RuntimeError 就停，不要改代码绕过\n"
        "3. 不要调用 extract_playbook action=feedback"
    )
    a = save_case(
        title=f"金丝雀换行保真 {MARK}",
        task_type="setup",
        steps=steps,
        problem=f"Windows 写文件把 LF 吃成 CRLF · {MARK}",
        trials="尚无失败路径",
        session_id="sess-slogan-canary",
        quote=NATURAL,
        tags=["canary", MARK],
    )
    b = save_case(
        title=f"金丝雀换行空经验 {MARK}",
        task_type="setup",
        steps="1. 打开文件\n2. 写回去",
        problem=f"Windows 写文件把 LF 吃成 CRLF · {MARK}",
        trials="尚无失败路径",
        session_id="sess-slogan-hollow",
        quote="空经验占位",
        tags=["canary", MARK],
    )
    c = save_case(
        title=f"金丝雀换行对照 {MARK}",
        task_type="setup",
        steps="1. 指定 newline\n2. 再写回",
        problem=f"Windows 写文件把 LF 吃成 CRLF · {MARK}",
        trials="尚无失败路径",
        session_id="sess-slogan-peer",
        quote="同簇对照",
        tags=["canary", MARK],
    )
    return {"main": a, "hollow": b, "peer": c}


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


def main() -> int:
    ping = requests.get(BASE + "/api/ping-test", timeout=5)
    if ping.status_code != 200:
        raise SystemExit("daemon 没起来")
    seeded = _seed()
    main_pb = seeded["main"]
    pid = main_pb["id"]
    raw_path = ROOT / "data" / "playbooks" / f"{main_pb['slug']}.md"
    before = _inject(NATURAL)
    live_fts = pid in before or MARK in before
    propose = "proposal_id=pp-" in before
    tag = time.strftime("%H%M%S")
    started = datetime.now(timezone.utc).isoformat()
    sid1 = f"api-slogan-t1-{tag}"
    sid2 = f"api-slogan-t2-{tag}"
    turn1 = _chat(NATURAL, sid1)
    tools1 = _tools(sid1)
    loaded = _loaded(tools1, pid) or _load_logged(pid, started)
    used = _usage(turn1)
    prompt_kind = "natural"
    if not loaded:
        sid1b = f"api-slogan-t1b-{tag}"
        turn1b = _chat(EXPLICIT, sid1b)
        tools1b = _tools(sid1b)
        used = _add(used, _usage(turn1b))
        if _loaded(tools1b, pid) or _load_logged(pid, started):
            loaded = True
            prompt_kind = "explicit"
            tools1 = tools1 + tools1b
            sid1 = sid1b
        else:
            prompt_kind = "missed"
    raw_after = raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""
    wrote = FAIL in raw_after or "自动 · python_exec 失败" in raw_after
    after = _inject(NATURAL)
    recall = FAIL in after or "自动 · python_exec 失败" in after
    hollow_lost = (seeded["hollow"]["id"] not in after) or (pid in after)
    turn2 = _chat(Q2, sid2)
    used = _add(used, _usage(turn2))
    reply2 = turn2.get("reply") or ""
    used_trial = FAIL in reply2 or "自动 ·" in reply2 or "假 result" in reply2 or "试错过" in reply2
    evidence = {
        "live_fts_hit": live_fts,
        "cluster_proposed": propose,
        "model_loaded": loaded,
        "prompt_kind": prompt_kind,
        "auto_writeback": wrote,
        "feedback_called": _feedback(tools1),
        "next_recall_sees_trial": recall,
        "empty_lost_slot": hollow_lost and wrote,
        "model_used_trial": used_trial,
    }
    if not evidence["live_fts_hit"]:
        slogan = "未达标 · 真 FTS 都没召回这本手册"
    elif not evidence["model_loaded"]:
        slogan = "未达标 · 手册在手里，真会话没有 load，失败写不回去"
    elif not evidence["auto_writeback"]:
        slogan = "未达标 · load 了但失败没自动写回"
    elif evidence["feedback_called"]:
        slogan = "未达标 · 还是靠模型自觉 feedback，不是 daemon 自己写"
    elif not evidence["next_recall_sees_trial"]:
        slogan = "未达标 · 写了但下次同一句看不见"
    elif evidence["prompt_kind"] == "explicit" and not evidence["model_used_trial"]:
        slogan = "管道能长，自然问法不会长 · 口号未满"
    elif evidence["prompt_kind"] == "explicit":
        slogan = "机械闭环成立，自然问法不 load · 口号未满"
    elif not evidence["model_used_trial"]:
        slogan = "下次能看见失败，回答没吃进去 · 口号未满"
    else:
        slogan = "手册环用户可感知 · 只这一环，不代表整产品已落地"
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
