"""workers/radar_config.py
掘金雷达 · 自动刷新配置（单例 · wish-7f38376e · 2026-09-23）

跟 notification_config 同哲学——单例，不是多配置 CRUD：
  - 数据落 data/radar_config.json（L3 · 不进 git）
  - 消费端：
    · workers/scheduler.py `_radar_loop` 每 10s 热读一次 ·
      设置页改完最多 10 秒生效 · **不用重启 daemon**
    · 前端设置页「掘金雷达」tab 走 GET/POST /radar-config

字段：
  - enabled      自动刷新总开关
                 False = 后台不再跑雷达（BRO 手动「抓一下雷达」/ auto_pipeline 仍然可用）
  - interval_min 两轮之间的间隔（分钟 · 1..1440）

优先级：data/radar_config.json（设置页写的） > .env OPUS_RADAR_INTERVAL_MIN > 默认 30。
文件不存在时用 .env 兜底 → 老用户升级后行为一个字都不变；
文件一旦被设置页写过，就以文件为准（UI 说了算）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = DATA_DIR / "radar_config.json"

DEFAULTS: dict = {
    "enabled": True,
    "interval_min": 30,
}

MIN_INTERVAL_MIN = 1
MAX_INTERVAL_MIN = 1440


def _clamp_interval(v: int) -> int:
    return max(MIN_INTERVAL_MIN, min(MAX_INTERVAL_MIN, int(v)))


def _env_defaults() -> dict:
    """文件不存在时的兜底：沿用 .env OPUS_RADAR_INTERVAL_MIN 的老语义。

    - 没设 / 非法  → 默认 30 分钟 · 开
    - 0 或负数     → 视为「默认关」（老用户的 OPUS_RADAR_INTERVAL_MIN=0）
    - >0           → 用它当间隔
    """
    d = dict(DEFAULTS)
    raw = (os.environ.get("OPUS_RADAR_INTERVAL_MIN") or "").strip()
    if not raw:
        return d
    try:
        v = int(float(raw))
    except ValueError:
        return d
    if v <= 0:
        d["enabled"] = False
    else:
        d["interval_min"] = _clamp_interval(v)
    return d


def load_radar_config() -> dict:
    """读当前配置。文件不存在/损坏 → 用 .env 兜底骨架。"""
    merged = _env_defaults()
    if not CONFIG_PATH.exists():
        return merged
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return merged
    if not isinstance(cfg, dict):
        return merged
    if isinstance(cfg.get("enabled"), bool):
        merged["enabled"] = cfg["enabled"]
    iv = cfg.get("interval_min")
    if isinstance(iv, (int, float)) and not isinstance(iv, bool):
        merged["interval_min"] = _clamp_interval(int(iv))
    return merged


def save_radar_config(cfg: dict) -> dict:
    """写入配置（merge 到当前值上 · 只收已知字段）。返回落盘后的完整配置。

    只传 enabled 或只传 interval_min 都行——另一个保持原样。
    """
    cur = load_radar_config()
    if isinstance(cfg, dict):
        if isinstance(cfg.get("enabled"), bool):
            cur["enabled"] = cfg["enabled"]
        iv = cfg.get("interval_min")
        if isinstance(iv, (int, float)) and not isinstance(iv, bool):
            cur["interval_min"] = _clamp_interval(int(iv))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(cur, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return cur
