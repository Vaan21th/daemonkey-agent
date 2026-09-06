"""真手册会话：已有换行册 + 这次真实失败，再问同一句。不种金丝雀。"""
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
REAL_ID = "pb-windows-换行保真-opennewline-写-归一化匹配-还原-eol"
NATURAL = (
    "Windows 上用 Python 写文本文件，LF 总被吃成 CRLF。"
    "按已有操作手册处理。先在 data/runtime/scratch 写个两行 LF 文件验证，"
    "写完用字节读回来检查，不要把 LF 吃成 CRLF。"
)


def _token() -> str:
    env = ROOT / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPUS_API_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("没有 OPUS_API_TOKEN")


H = {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


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
        except Exception:
            continue
        if rec.get("role") in {"tool", "assistant"} or rec.get("type") in {
            "tool_call", "tool_result",
        }:
            rows.append(rec)
    return rows


def _blob(sid: str) -> str:
    path = ROOT / "sessions" / f"{sid}.jsonl"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def main() -> int:
    inj = _inject(NATURAL)
    stamp = datetime.now().strftime("%H%M%S")
    s1 = f"api-real-eol-t1-{stamp}"
    s2 = f"api-real-eol-t2-{stamp}"
    print("=== inject ===", flush=True)
    print(inj, flush=True)
    t0 = time.time()
    r1 = _chat(NATURAL, s1)
    print("=== t1 reply ===", flush=True)
    print((r1.get("reply") or r1.get("text") or "")[:1200], flush=True)
    time.sleep(1)
    r2 = _chat(NATURAL, s2)
    print("=== t2 reply ===", flush=True)
    print((r2.get("reply") or r2.get("text") or "")[:1200], flush=True)
    b1, b2 = _blob(s1), _blob(s2)
    trial = "os.linesep"
    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "playbook_id": REAL_ID,
        "sessions": {"t1": s1, "t2": s2},
        "inject_hits_real": REAL_ID in inj,
        "inject_has_trial": trial in inj,
        "inject_no_canary": "canary" not in inj.lower() and "金丝雀" not in inj,
        "t1_loaded_real": REAL_ID in b1,
        "t2_loaded_real": REAL_ID in b2,
        "t2_bare_open_write": (
            "newline" not in b2
            and ("open(" in b2 and ", 'w'" in b2 or ', "w"' in b2)
        ),
        "t2_mentions_avoid": any(
            x in (r2.get("reply") or r2.get("text") or "")
            for x in ("试错过", "避开", "newline", "os.linesep")
        ),
        "elapsed_s": round(time.time() - t0, 1),
        "usage": {
            "t1": r1.get("usage") or r1.get("usage_total"),
            "t2": r2.get("usage") or r2.get("usage_total"),
        },
    }
    out = ROOT / "data" / "runtime" / "playbook_real_eol.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    ok = (
        report["inject_hits_real"]
        and report["inject_has_trial"]
        and report["inject_no_canary"]
        and report["t1_loaded_real"]
        and report["t2_loaded_real"]
        and not report["t2_bare_open_write"]
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
