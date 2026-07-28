"""workers/notification_config.py
通知配置（单例 · wish-fb6b7427 · 2026-07-28）

跟 vision_config 同哲学——单例，不是多配置 CRUD：
  - 数据落 data/notification_config.json（L3 · 不进 git）
  - 三个消费端：
    · desktop_pet/pet.py 直接读文件（桌宠跟 daemon 走文件桥 · 不过 HTTP）
    · daemon toast 挂点（事项 B · 已落地 workers/windows_toast.py · daemon_api.py L687-690 / L1383-1386）
    · 前端 chat.js 走 GET/POST /notification-config

开关语义：
  - pet_sound      桌宠完成音效（ding/manbo.wav · done 通知时播）
  - windows_toast  Windows 系统通知（事项 B 已落地 · workers/windows_toast.py）
  - tab_flash      浏览器标签闪烁（事项 C 已落地 · chat.js _maybeTabFlash）
  - pet_sound_path 音效文件路径（相对工程根 · 第一版 UI 不暴露）
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = DATA_DIR / "notification_config.json"

DEFAULTS: dict = {
    "pet_sound": True,
    "windows_toast": False,
    "tab_flash": False,
    "pet_sound_path": "ding/manbo.wav",
}


def load_notification_config() -> dict:
    """读取通知配置。文件不存在/损坏返回 DEFAULTS 骨架（含未来字段默认值）。"""
    if not CONFIG_PATH.exists():
        return dict(DEFAULTS)
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        merged = dict(DEFAULTS)
        if isinstance(cfg, dict):
            merged.update({k: v for k, v in cfg.items() if k in DEFAULTS})
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)


def save_notification_config(cfg: dict) -> dict:
    """写入通知配置（merge 到 DEFAULTS 上 · 只收已知字段）。返回落盘后的完整配置。"""
    merged = dict(DEFAULTS)
    if isinstance(cfg, dict):
        merged.update({k: v for k, v in cfg.items() if k in DEFAULTS})
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return merged
