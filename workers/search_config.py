"""外网搜索 KEY 单例。未配置时 web_search 走免费刮取。"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = DATA_DIR / "search_config.json"

_DEFAULT = {
    "provider": "bocha",
    "api_key": "",
    "enabled": True,
    "configured": False,
}


def load_search_config() -> dict:
    if not CONFIG_PATH.exists():
        return dict(_DEFAULT)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT)
    out = dict(_DEFAULT)
    out.update(data if isinstance(data, dict) else {})
    return out


def save_search_config(cfg: dict) -> dict:
    cur = load_search_config()
    if "provider" in cfg:
        cur["provider"] = (cfg.get("provider") or "bocha").strip() or "bocha"
    if "enabled" in cfg:
        cur["enabled"] = bool(cfg["enabled"])
    key = (cfg.get("api_key") or "").strip()
    if key and "****" not in key:
        cur["api_key"] = key
    cur["configured"] = bool((cur.get("api_key") or "").strip())
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from workers.safe_write import robust_write_json
        robust_write_json(CONFIG_PATH, cur, backup=False)
    except ImportError:
        CONFIG_PATH.write_text(
            json.dumps(cur, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return cur


def mask_key(s: str) -> str:
    s = s or ""
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "****" + s[-4:]


def get_active_search() -> tuple[str, str, str]:
    """(provider, api_key, source)。未启用或没 key 则全空。"""
    cfg = load_search_config()
    if not cfg.get("enabled", True):
        return "", "", ""
    key = (cfg.get("api_key") or "").strip()
    if cfg.get("configured") and key:
        return (cfg.get("provider") or "bocha").strip() or "bocha", key, "user"
    key = (os.getenv("BOCHA_API_KEY") or "").strip()
    if key:
        return "bocha", key, "env"
    return "", "", ""
