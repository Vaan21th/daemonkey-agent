"""会话能力档位 · 解析（wish-16fa5930）· 表在 data/cognition/tool_profiles.json"""
from __future__ import annotations

import json
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "data" / "cognition" / "tool_profiles.json"
DEFAULT_ID = "standard"


def _load() -> dict:
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def profile_list() -> list:
    """给 UI 的档位清单（不带工具名全文）。"""
    from agent_tools._tool_catalog import CORE
    out = []
    for pid, v in ((_load().get("profiles") or {})).items():
        if not isinstance(v, dict):
            continue
        t = v.get("tools")
        n = len(CORE) if t == "CORE" else (len(t) if isinstance(t, list) else 0)
        out.append({"id": pid, "name": v.get("name") or pid,
                    "desc": v.get("desc") or "", "size": v.get("size") or "",
                    "count": n, "default": bool(v.get("default"))})
    return out


def resolve_profile(pid):
    """返 (档位 id, 工具集合 | None)。None = 不设限（standard = CORE 全量）。"""
    from agent_tools._tool_catalog import CORE
    d = (_load().get("profiles") or {})
    p = d.get(pid) if isinstance(pid, str) and pid else None
    if not isinstance(p, dict):
        p, pid = d.get(DEFAULT_ID), DEFAULT_ID
    if not isinstance(p, dict):
        return DEFAULT_ID, None
    t = p.get("tools")
    if t == "CORE" or not t:
        return pid, None
    names = [x for x in t if isinstance(x, str) and x in CORE]
    return pid, set(names)


def suggest_profile() -> dict:
    """按当前模型给一个建议档（原型缺口③ · 本地小模型 → 闲聊档）。

    只在**本机端点**（LM Studio / Ollama 等自跑模型）时建议 chat：这类模型
    窗口小、在 138 件工具前容易选错轨（实测 8B 只给 8 件仍挑错）。
    云端模型不猜（返 {}）—— 弱云端模型要不要也算，等 BRO 拍。

    返回 {} = 不建议；否则 {"id", "why", "model", "local"}。前端只拿它做
    选档卡的**预选**，用户点一下就覆盖，不写 meta、不改行为。
    """
    try:
        from workers.provider_configs import get_active_config
        cfg = get_active_config(include_key=False) or {}
    except Exception:
        return {}
    base = str(cfg.get("base_url") or "").strip().lower()
    if not base:
        return {}
    host = base.split("//", 1)[-1].split("/", 1)[0].rsplit("@", 1)[-1]
    host = host.rsplit(":", 1)[0].strip("[]")
    if host not in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
        return {}
    return {"id": "chat", "why": "检测到本机模型 · 建议闲聊档",
            "model": str(cfg.get("model") or ""), "local": True}
