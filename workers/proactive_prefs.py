"""
workers/proactive_prefs.py · 主动 CALL 频率档位 · 猫系↔犬系 (卷六十一)

把一堆 OPUS_PROACTIVE_* 旋钮收成一条『多 ↔ 少』的轴·让 BRO 用一个滑块表达『我想要多黏的 OPUS』。
猫系=含蓄少开口·犬系=热情常搭话。写 env 同时写进程 os.environ·即时生效不用重启 (proactive_call
每拍重读 os.environ)。同时也持久化到 .env (write_env_kv)·重启后保留。
"""
from __future__ import annotations

import os

# 少 → 多。每档把四个旋钮一起调：沉默阈值越小 / 随机概率越高 / 每天上限越大 / 间隔越小 = 越黏。
PRESETS = [
    {"id": "off", "label": "关闭", "emoji": "\U0001f6ab", "desc": "不主动开口·只等你来",
     "env": {"OPUS_PROACTIVE_CALL": "0"}},
    {"id": "aloof", "label": "高冷猫", "emoji": "\U0001f63c", "desc": "极少·要憋很久才找你",
     "env": {"OPUS_PROACTIVE_CALL": "1", "OPUS_PROACTIVE_SILENCE_HOURS": "36",
             "OPUS_PROACTIVE_SPONTANEITY": "0.15", "OPUS_PROACTIVE_MAX_PER_DAY": "1",
             "OPUS_PROACTIVE_MIN_GAP_HOURS": "12"}},
    {"id": "cat", "label": "猫系", "emoji": "\U0001f431", "desc": "含蓄·偶尔想起你",
     "env": {"OPUS_PROACTIVE_CALL": "1", "OPUS_PROACTIVE_SILENCE_HOURS": "24",
             "OPUS_PROACTIVE_SPONTANEITY": "0.25", "OPUS_PROACTIVE_MAX_PER_DAY": "1",
             "OPUS_PROACTIVE_MIN_GAP_HOURS": "8"}},
    {"id": "balanced", "label": "均衡", "emoji": "\u2696\ufe0f", "desc": "默认分寸·不冷不黏",
     "env": {"OPUS_PROACTIVE_CALL": "1", "OPUS_PROACTIVE_SILENCE_HOURS": "18",
             "OPUS_PROACTIVE_SPONTANEITY": "0.35", "OPUS_PROACTIVE_MAX_PER_DAY": "1",
             "OPUS_PROACTIVE_MIN_GAP_HOURS": "6"}},
    {"id": "dog", "label": "犬系", "emoji": "\U0001f436", "desc": "热情·常来搭话",
     "env": {"OPUS_PROACTIVE_CALL": "1", "OPUS_PROACTIVE_SILENCE_HOURS": "8",
             "OPUS_PROACTIVE_SPONTANEITY": "0.6", "OPUS_PROACTIVE_MAX_PER_DAY": "3",
             "OPUS_PROACTIVE_MIN_GAP_HOURS": "3"}},
    {"id": "clingy", "label": "黏人犬", "emoji": "\U0001f415", "desc": "很黏·只要你在就想说话",
     "env": {"OPUS_PROACTIVE_CALL": "1", "OPUS_PROACTIVE_SILENCE_HOURS": "4",
             "OPUS_PROACTIVE_SPONTANEITY": "0.85", "OPUS_PROACTIVE_MAX_PER_DAY": "5",
             "OPUS_PROACTIVE_MIN_GAP_HOURS": "2"}},
]

# 用来判断"当前 env 命中哪个档"的字段 (off 单独判)
_MATCH_KEYS = (
    "OPUS_PROACTIVE_SILENCE_HOURS",
    "OPUS_PROACTIVE_SPONTANEITY",
    "OPUS_PROACTIVE_MAX_PER_DAY",
    "OPUS_PROACTIVE_MIN_GAP_HOURS",
)


def _enabled() -> bool:
    return (os.environ.get("OPUS_PROACTIVE_CALL") or "1").strip().lower() not in (
        "0", "false", "off", "no", "",
    )


def current_preset_id() -> str:
    """读当前 env·匹配到某个档·匹配不上返回 'custom' (BRO 手改过 .env)。"""
    if not _enabled():
        return "off"
    cur = {k: (os.environ.get(k) or "").strip() for k in _MATCH_KEYS}
    for p in PRESETS:
        if p["id"] in ("off",):
            continue
        if all(cur.get(k, "") == str(p["env"].get(k, "")) for k in _MATCH_KEYS if k in p["env"]):
            # 只有当 env 里这些值都设了才算命中·全空时算 balanced (默认值等价)
            if any(cur.get(k) for k in _MATCH_KEYS):
                return p["id"]
    # env 全空 = 没显式设过 = 默认值 = balanced
    if not any(cur.get(k) for k in _MATCH_KEYS):
        return "balanced"
    return "custom"


def set_preset(preset_id: str) -> dict:
    """应用一个档位·写 os.environ (即时) + .env (持久)。返回应用后的 env 子集。"""
    preset = next((p for p in PRESETS if p["id"] == preset_id), None)
    if preset is None:
        raise ValueError(f"unknown preset: {preset_id}")
    from daemon_provider import write_public_env

    applied = {}
    for k, v in preset["env"].items():
        try:
            # 写 .env 对外落 DAEMONKEY_ 前缀(去 OPUS 泄漏)·同时同步 os.environ 内核 OPUS_ 名
            write_public_env(k, v)
        except Exception:
            os.environ[k] = v  # 写 .env 失败也至少让本进程即时生效
        applied[k] = v
    return applied


def status() -> dict:
    return {
        "current": current_preset_id(),
        "enabled": _enabled(),
        "presets": [
            {"id": p["id"], "label": p["label"], "emoji": p["emoji"], "desc": p["desc"]}
            for p in PRESETS
        ],
    }
