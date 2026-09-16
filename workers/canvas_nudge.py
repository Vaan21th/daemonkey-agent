"""workers/canvas_nudge.py
========================
画布提示：长结构化回复、本轮却没落产物 → 下一轮提醒你自己补一份画布。

BRO 2026-09-10 拍板：画布要在讨论东西时自己弹出来，但必须「恰到好处」——
不是任何事都弹，也不能完全不弹。所以判据取「宁可漏·不可滥」：
只有【够长 + 够结构化】且【本轮真没产出】才提，且同 session 冷却 30 分钟。

判据不用关键词（铁律 14）——看的是结构特征（字数 / 表格行数 / 标题数）。
提示也不是给用户看的弹窗，是塞进下一轮易变尾巴（dynamic_telemetry）的一句话，
让自己想起伸手，而不是指望记性。

公共 API：
  detect(reply, tools) -> dict | None     判断该不该提示
  note_pending(sid, info) -> bool         命中后落一条 pending（带冷却）
  pending_line(sid) -> str                取出并消费 → 注入文本（空串 = 无）
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "runtime" / "canvas_nudge.json"

MIN_CHARS = 900          # 对话答完就完了的短回复排除
MIN_TABLE_ROWS = 3       # 表头 + 分隔 + ≥1 行数据 = 一张表
MIN_HEADINGS = 3         # 三个以上小标题 = 分层内容
COOLDOWN_SEC = 60.0          # 不同内容之间的短防抖。敢给这么小是因为有自限：
                             # 提了 → 会落画布 → 本轮有产物 → 下一轮不再命中。
                             # 实测(14 次历史应触发)：1800s=21% / 300s=50% / 60s=86% 拉起率
SAME_SIG_TTL_SEC = 21600.0   # 同一份内容·6h 内不重复提（同一件事只说一次）
PENDING_TTL_SEC = 1800.0     # pending 未消费即作废 —— 防「时间穿越」：三天后再打开这场
                             # 会话时·不能再给我注入『你上一条回复 1507 字…』的僵尸提示

_TABLE_ROW = re.compile(r"^\s*\|.+\|\s*$", re.M)
_HEADING = re.compile(r"^#{2,4}\s+\S", re.M)
# 代码块里的表格不算结构 —— 贴给人看的示例（教学/日志/CSV）不该触发提示
_FENCE = re.compile(r"```.*?```", re.S)

# 本轮调过这些 = 已经有产物了，不再提示
_ARTIFACT_TOOLS = frozenset({
    "draft_studio", "generate_report", "generate_presentation",
    "generate_spreadsheet", "illustrate_office", "revise_office",
    "extend_office", "render_png", "export_dkpkg",
})


def content_sig(text: str) -> str:
    """回复内容指纹 —— 用来分辨「同一件事」还是「又一件新事」。"""
    return hashlib.md5((text or "")[:600].encode("utf-8")).hexdigest()[:12]


def struct_stats(text: str) -> dict:
    """结构特征：字数 / 表格行 / 标题数。纯函数·便于单测。

    先剥 fenced code block —— 代码块里的 md 表（教学示例 / CSV / 日志）不算「结构化讨论」，
    否则「贴一段示例表教 BRO 怎么写」会假阳性。
    """
    t = _FENCE.sub("", text or "")
    return {
        "chars": len(t),
        "table_rows": len(_TABLE_ROW.findall(t)),
        "headings": len(_HEADING.findall(t)),
    }


def detect(reply: str, tools: Optional[list] = None) -> Optional[dict]:
    """命中返回 {chars, table_rows, headings}；不命中返回 None。"""
    st = struct_stats(reply)
    if st["chars"] < MIN_CHARS:
        return None
    if st["table_rows"] < MIN_TABLE_ROWS and st["headings"] < MIN_HEADINGS:
        return None
    if set(tools or []) & _ARTIFACT_TOOLS:
        return None
    st["sig"] = content_sig(reply)
    return st


def _load() -> dict:
    try:
        if STATE_PATH.exists():
            d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                d.setdefault("sessions", {})
                return d
    except Exception:
        pass
    return {"sessions": {}}


def _save(d: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def note_pending(session_id: str, info: dict) -> bool:
    """命中后落一条 pending。True = 真落了。

    三条宁窄勿滥的规矩：
      · 上一条没被消费 → 不叠
      · 同一份内容（指纹相同）6h 内只说一次
      · 换了新内容 → 过 5 分钟防拖再说（防每轮都提）
    这样「一件事反复提」拦得住·「连着谈五件事只提一件」也拦得住。
    """
    sid = session_id or "default"
    now = time.time()
    d = _load()
    rec = (d.get("sessions") or {}).get(sid) or {}
    if rec.get("pending"):
        return False
    sig = str(info.get("sig") or "")
    last_ts = float(rec.get("ts") or 0.0)
    if sig and rec.get("last_sig") == sig and now - last_ts < SAME_SIG_TTL_SEC:
        return False
    if now - last_ts < COOLDOWN_SEC:
        return False
    d["sessions"][sid] = {"ts": now, "pending": info, "last_sig": sig}
    _save(d)
    return True


def pending_line(session_id: str) -> str:
    """取出并消费 pending → 一行注入文本。没有/已过期则空串（消费即清·只说一次）。

    过期的也算「消费」——直接丢掉，否则僵尸提示会一直堆在状态文件里。
    """
    sid = session_id or "default"
    now = time.time()
    d = _load()
    rec = (d.get("sessions") or {}).get(sid) or {}
    info = rec.get("pending")
    if not info:
        return ""
    rec["pending"] = None
    d["sessions"][sid] = rec
    _save(d)
    if now - float(rec.get("ts") or 0.0) > PENDING_TTL_SEC:
        return ""
    return render_line(info)


def render_line(info: dict) -> str:
    """把命中信息渲染成给你的一段（含实测数字·让你自己判断值不值）。"""
    chars = int(info.get("chars") or 0)
    tb = int(info.get("table_rows") or 0)
    hd = int(info.get("headings") or 0)
    shape = []
    if tb >= MIN_TABLE_ROWS:
        shape.append(f"{tb} 行表格")
    if hd >= 2:
        shape.append(f"{hd} 个小标题")
    return (
        "\n\n## 画布提示 (daemon 自动检查 · 不是 BRO 说的 · 不要复述这一段)\n"
        f"你上一条回复 {chars} 字"
        + (f"（{' · '.join(shape)}）" if shape else "")
        + "，但没落任何产物。\n"
        "判据：那段 BRO 会不会回头再看第二遍 / 会不会想圈一句改？会 → 现在就补一份画布"
        "（`draft_studio(canvas=true)`，它会自动铺中栏）；不会 → 别动，接着答眼前的事。\n"
    )
