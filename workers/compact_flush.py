"""压缩前把还没进本子的事实落盘。失败不挡折。

OpenClaw 的不变量：compact 不能是唯一副本。这里不跑整轮 tool loop，
只抽 JSON 短条，写入走 update_bro_note 的路由（日期故事进 events）。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

_SECTIONS = frozenset({"profile", "events", "rules", "dialogue", "summary", "risks"})
_MAX_FACTS = 3
_MAX_CHARS = 160
_TRANSCRIPT_CAP = 6000

_FLUSH_HINT = (
    "只提取关于「他」的长期事实：偏好、边界、正在过的日子、关系里刚钉死的约定。\n"
    "不要任务进度、不要代码、不要工具输出、不要复述系统提示。\n"
    "最多 3 条。每条 content 不超过 160 字，必须是他真说过或刚确认的。\n"
    "section 只能是 profile / events / rules / dialogue。\n"
    "没有就 {\"facts\":[]}\n"
    "只输出 JSON。"
)


def flush_enabled() -> bool:
    v = (os.environ.get("OPUS_COMPACT_FLUSH") or "1").strip().lower()
    return v not in ("0", "false", "off", "no")


def recent_transcript(messages: list[dict], *, cap: int = _TRANSCRIPT_CAP) -> str:
    """最近对人说的话。跳过工具结果和已有摘要。"""
    chunks: list[str] = []
    for msg in messages:
        role = msg.get("role") or ""
        if role not in ("user", "assistant"):
            continue
        text = _plain_text(msg.get("content"))
        if not text:
            continue
        if "<compaction-summary>" in text:
            continue
        chunks.append(f"{role}: {text}")
    blob = "\n".join(chunks)
    if len(blob) > cap:
        blob = blob[-cap:]
    return blob


def _plain_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        bits = []
        for part in content:
            if isinstance(part, dict) and part.get("type") in (None, "text"):
                t = part.get("text") or ""
                if t:
                    bits.append(str(t))
        return "\n".join(bits).strip()
    return ""


def accept_fact(section: str, content: str) -> bool:
    sec = (section or "").strip().lower()
    text = (content or "").strip()
    if sec not in _SECTIONS or not text:
        return False
    if len(text) > _MAX_CHARS:
        return False
    if text.count("\n") >= 6:
        return False
    return True


def parse_facts(raw: str) -> list[dict[str, str]]:
    text = (raw or "").strip()
    if not text:
        return []
    obj = None
    try:
        obj = json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                obj = json.loads(m.group(0))
            except Exception:
                return []
    if not isinstance(obj, dict):
        return []
    items = obj.get("facts")
    if not isinstance(items, list):
        return []
    out: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        sec = str(item.get("section") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if not accept_fact(sec, content):
            continue
        out.append({"section": sec, "content": content})
        if len(out) >= _MAX_FACTS:
            break
    return out


def _extract_with_llm(transcript: str, client: Any, model: str, provider: str) -> str:
    if client is None or not transcript.strip():
        return ""
    from identity import localize_narration as _ln
    prompt = f"{_ln(_FLUSH_HINT)}\n\n--- 对话 ---\n\n{transcript}"
    from daemon_runtime import bg_max_tokens
    mt = min(800, bg_max_tokens(default=800))
    if provider == "anthropic":
        resp = client.messages.create(
            model=model, max_tokens=mt,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            getattr(b, "text", "") for b in (resp.content or [])
        )
    resp = client.chat.completions.create(
        model=model, max_tokens=mt,
        messages=[{"role": "user", "content": prompt}],
    )
    choice = (resp.choices or [None])[0]
    return ((choice.message.content if choice else None) or "") if choice else ""


def apply_facts(facts: list[dict[str, str]]) -> list[str]:
    from agent_tools.update_bro_note import append_owner_note
    from workers.notebook_tiers import route_write_section

    written: list[str] = []
    for fact in facts:
        sec = route_write_section(fact["section"], "append", fact["content"])
        result = append_owner_note(sec, fact["content"])
        if getattr(result, "ok", False):
            written.append(sec)
    return written


def flush_before_compact(
    messages: list[dict],
    client: Any,
    model: str,
    provider: str,
) -> dict[str, Any]:
    """尽力写。任何失败都返回 ok=False，调用方仍应 compact。"""
    info: dict[str, Any] = {"ok": False, "wrote": [], "skipped": "off"}
    if not flush_enabled():
        return info
    try:
        transcript = recent_transcript(messages)
        if len(transcript) < 24:
            info["skipped"] = "short"
            return info
        raw = _extract_with_llm(transcript, client, model, provider)
        facts = parse_facts(raw)
        if not facts:
            info["skipped"] = "none"
            info["ok"] = True
            return info
        wrote = apply_facts(facts)
        info["ok"] = True
        info["wrote"] = wrote
        info["skipped"] = ""
        return info
    except Exception as exc:
        info["skipped"] = type(exc).__name__
        return info
