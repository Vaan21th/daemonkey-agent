"""workers/advisor_live.py
=============================

wish-ea8922f7 · 顾问在场感 · 实时状态单一事实源 + 过程回放解析。

问题 (BRO 2026-07-28 截图诉求): 顾问被召唤后 UI 全程静默只显示一行"顾问已给出结论"——
BRO 要等 10-30s 不知道 daemon 是在思考还是卡死。

设计:
  - replan 工具 / 协同模式 (advisor_coop) 跑顾问时 · 把进度写进
    ``data/runtime/advisor_live.json`` (单一事实源)
  - 主 SSE 靠 push_tool_progress / advisor_status 事件实时推 (主路径)
  - live.json 给【刷新页面 / 另一标签页 / 手机端】恢复 live 卡用 (兜底)
  - trace 解析把 sessions/sub-<id>.jsonl 转成时间线节点 · 给"展开顾问过程"用

只写 data/runtime/ · 不碰灵魂层 · 文件读写全部 try 包住 (状态坏了不能搞崩顾问本体)。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
_LIVE_PATH = _ROOT / "data" / "runtime" / "advisor_live.json"
_SESSIONS = _ROOT / "sessions"

_SUB_ID_RE = re.compile(r"^[a-f0-9]{6,16}$")

# 活性判定 (顾问 KIMI K3 2026-07-28 验装现场逮住): daemon 重启/崩溃时 finish_live 跑不到 ·
# live.json 会永远停在 active:true → status 端点撒谎。 心跳超期 = 顾问大概率死了 · 标 stale。
_STALE_AFTER_SEC = 180  # 3 分钟没心跳 (单次 LLM+工具正常 <120s)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def write_live(
    *,
    mode: str,
    model_label: str,
    source: str,
    session_id: str = "",
) -> None:
    """顾问开跑 · 建 live 状态 (active:true)。"""
    try:
        _LIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "active": True,
            "mode": mode,
            "model_label": model_label,
            "source": source,               # replan_tool / coop_mode
            "session_id": session_id,
            "started_at": _now_iso(),
            "started_ts": time.time(),
            "last_ts": time.time(),
            "turn": 0,
            "last_action": "启动中",
            "last_think": "",
        }
        _LIVE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def update_live(*, turn: Optional[int] = None, action: str = "", think: str = "",
                files: Optional[int] = None) -> None:
    """顾问跑的过程中 · 更新轮次 / 最近动作 / 最近思考片段 / 已读文件数。"""
    try:
        if not _LIVE_PATH.exists():
            return
        payload = json.loads(_LIVE_PATH.read_text(encoding="utf-8"))
        if not payload.get("active"):
            return
        payload["last_ts"] = time.time()  # 每步心跳 · stale 判定的命
        if turn is not None:
            payload["turn"] = turn
        if action:
            payload["last_action"] = action[:120]
        if think:
            payload["last_think"] = think[:200]
        if files is not None:
            payload["files_read"] = files  # 协同模式金卡/刷新恢复卡都能显示"已读 N 个文件"
        _LIVE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def finish_live(*, ok: bool, iterations: int, sub_session_id: str = "",
                text: str | None = None, verdict: str | None = None) -> None:
    """顾问跑完 · active:false · 留最近一次活动的摘要 (status 端点可回"上次顾问")。
    text/verdict 可选 · 自动验收场景由 daemon_api 补写 · 前端 polling 自愈时读。"""
    try:
        if not _LIVE_PATH.exists():
            return
        payload = json.loads(_LIVE_PATH.read_text(encoding="utf-8"))
        payload["active"] = False
        payload["finished_at"] = _now_iso()
        payload["ok"] = ok
        payload["iterations"] = iterations
        if sub_session_id:
            payload["sub_session_id"] = sub_session_id
        if text is not None:
            payload["text"] = text[:3000]
        if verdict is not None:
            payload["verdict"] = verdict
        _LIVE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def read_live() -> dict:
    """status 端点用 · 文件不在/坏了都回 {active: false} · active 但心跳超期标 stale (纯读不改写)。"""
    try:
        if not _LIVE_PATH.exists():
            return {"active": False}
        payload = json.loads(_LIVE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"active": False}
    if payload.get("active"):
        try:
            age = time.time() - float(payload.get("last_ts") or payload.get("started_ts") or 0)
        except Exception:
            age = 0
        if age > _STALE_AFTER_SEC:
            payload["active"] = False
            payload["stale"] = True
            payload["stale_reason"] = f"心跳停顿 {int(age)}s · 顾问大概率已退出 (崩溃/重启)"
    return payload


def _clip(text: Any, n: int) -> str:
    s = (text if isinstance(text, str) else str(text or "")).strip()
    return s[:n] + ("…" if len(s) > n else "")


def parse_trace(sub_session_id: str) -> Optional[list[dict]]:
    """把 sessions/sub-<id>.jsonl 解析成时间线节点 · 给过程回放用。

    返回 None = 找不到 / 坏了。 节点 kinds:
      meta     · 顾问元信息 (model / 时间)
      task     · 初始任务 (user 首条)
      think    · 顾问思考 (assistant content)
      tool     · 工具调用 + 结果摘要 (assistant tool_calls + 后续 role=tool 回填)
      answer   · 最终结论 (最后一条有 content 的 assistant)
    """
    sid = (sub_session_id or "").strip()
    if sid.startswith("sub-"):
        sid = sid[4:]
    if not _SUB_ID_RE.match(sid):
        return None
    path = _SESSIONS / f"sub-{sid}.jsonl"
    if not path.exists():
        return None

    nodes: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None

    # 待回填的 tool 节点: tool_call_id -> node dict
    pending_tools: dict[str, dict] = {}

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        role = msg.get("role")

        if role == "_meta":
            nodes.append({
                "kind": "meta",
                "model": msg.get("model", ""),
                "ts": msg.get("ts", ""),
            })
            continue

        if role == "user":
            # 初始任务 (可能很长 · 截断)
            nodes.append({"kind": "task", "text": _clip(msg.get("content"), 300)})
            continue

        if role == "assistant":
            content = msg.get("content")
            if isinstance(content, list):  # 部分 provider content 是分块 list
                content = "".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )
            tool_calls = msg.get("tool_calls") or []
            if content and content.strip():
                nodes.append({"kind": "think", "text": _clip(content, 500)})
            for tc in tool_calls:
                fn = (tc or {}).get("function") or {}
                name = fn.get("name") or tc.get("name") or "?"
                args_raw = fn.get("arguments") or tc.get("arguments") or ""
                # args 摘要: 只取关键字段 · 别整坨 JSON 倒给 UI
                args_brief = ""
                try:
                    args_obj = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                    if isinstance(args_obj, dict):
                        pick = {k: args_obj[k] for k in ("path", "query", "pattern", "url", "goal") if k in args_obj}
                        args_brief = _clip(json.dumps(pick, ensure_ascii=False), 120) if pick else _clip(str(args_raw), 80)
                except Exception:
                    args_brief = _clip(str(args_raw), 80)
                node = {
                    "kind": "tool",
                    "name": name,
                    "args": args_brief,
                    "ok": None,          # 等 role=tool 回填
                    "result": "",
                }
                nodes.append(node)
                tc_id = tc.get("id") or ""
                if tc_id:
                    pending_tools[tc_id] = node
            continue

        if role == "tool":
            tc_id = msg.get("tool_call_id") or ""
            node = pending_tools.pop(tc_id, None)
            result_text = msg.get("content")
            if isinstance(result_text, list):
                result_text = "".join(
                    b.get("text", "") for b in result_text if isinstance(b, dict)
                )
            result_text = str(result_text or "")
            is_err = result_text.lstrip().startswith(("Error", "error", "❌")) or msg.get("is_error")
            if node is not None:
                node["ok"] = (not is_err)
                node["result"] = _clip(result_text, 150)
            continue

    # 最后一条 think 节点升级为 answer (顾问的最终结论)
    for node in reversed(nodes):
        if node["kind"] == "think":
            node["kind"] = "answer"
            node["text"] = node["text"][:2000] + ("…" if len(node["text"]) > 2000 else "")
            break

    return nodes
