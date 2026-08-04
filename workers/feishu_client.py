"""
workers/feishu_client.py · 飞书开放平台客户端 (0.9.0 · wish-aac348a1)

企业自建应用: app_id + app_secret → tenant_access_token (2h 缓存) → im/v1/messages 发消息。
配置存 data/runtime/feishu_config.json (用户 WebUI 填 · 与微信 iLink 并列)。
对比微信 iLink: 官方 API + WebSocket 长连接 · 无 24h 窗口 · 无公网依赖。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("opus.feishu")

_CONFIG_PATH = Path("data/runtime/feishu_config.json")
_BASE = "https://open.feishu.cn"

_TOKEN_CACHE: dict = {"token": None, "exp": 0.0}  # tenant_access_token + 到期时间


# ── 配置 ──────────────────────────────────────────────────

def load_config() -> dict:
    if not _CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(app_id: str, app_secret: str, enabled: bool = True) -> None:
    cfg = load_config()
    cfg.update({"app_id": app_id.strip(), "app_secret": app_secret.strip(), "enabled": bool(enabled)})
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("feishu config saved · app_id=%s · enabled=%s", cfg["app_id"], cfg["enabled"])


def is_configured() -> bool:
    cfg = load_config()
    return bool(cfg.get("app_id") and cfg.get("app_secret"))


def enabled() -> bool:
    cfg = load_config()
    return is_configured() and bool(cfg.get("enabled", True))


def set_enabled(on: bool) -> None:
    cfg = load_config()
    cfg["enabled"] = bool(on)
    save_config(cfg.get("app_id", ""), cfg.get("app_secret", ""), bool(on))


# ── L1 · 群机器人 webhook (零门槛单向推送 · 0.9.1) ───────────────

def save_webhook(url: str) -> None:
    cfg = load_config()
    cfg["webhook_url"] = url.strip()
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("feishu webhook saved · %s", cfg["webhook_url"][:40] + "***" if cfg["webhook_url"] else "")


def get_webhook() -> Optional[str]:
    url = load_config().get("webhook_url") or ""
    return url.strip() or None


def send_webhook(text: str) -> dict:
    """L1 · 群机器人 webhook 推送 · 无需 App ID/Secret · 单向 (daemon → 群)。"""
    url = get_webhook()
    if not url:
        return {"ok": False, "error": "未配置 webhook URL"}
    try:
        r = requests.post(
            url,
            json={"msg_type": "text", "content": {"text": text}},
            timeout=15,
        )
        d = r.json()
        ok = d.get("code") == 0
        if not ok:
            logger.warning("feishu webhook 失败: %s", d.get("msg"))
        return {"ok": ok, "msg": d.get("msg", "")}
    except Exception as e:
        logger.warning("feishu webhook 异常: %s", e)
        return {"ok": False, "error": str(e)}


# ── 认证 ──────────────────────────────────────────────────

def get_tenant_token() -> Optional[str]:
    """app_id+app_secret → tenant_access_token · 缓存到到期前 5 分钟。"""
    if _TOKEN_CACHE["token"] and time.time() < _TOKEN_CACHE["exp"] - 300:
        return _TOKEN_CACHE["token"]
    cfg = load_config()
    if not is_configured():
        return None
    try:
        r = requests.post(
            f"{_BASE}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": cfg["app_id"], "app_secret": cfg["app_secret"]},
            timeout=15,
        )
        d = r.json()
        if d.get("code") == 0:
            _TOKEN_CACHE["token"] = d["tenant_access_token"]
            _TOKEN_CACHE["exp"] = time.time() + int(d.get("expire", 7200))
            return _TOKEN_CACHE["token"]
        logger.warning("feishu token 失败: %s", d.get("msg"))
    except Exception as e:
        logger.warning("feishu token 异常: %s", e)
    return None


# ── 收发 ──────────────────────────────────────────────────

def send_text(text: str, receive_id: str, receive_id_type: str = "chat_id") -> dict:
    """给飞书会话/用户发一条文本消息。receive_id_type: chat_id / open_id / user_id。"""
    token = get_tenant_token()
    if not token:
        return {"ok": False, "error": "未配置或 token 获取失败"}
    try:
        r = requests.post(
            f"{_BASE}/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": receive_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            timeout=20,
        )
        d = r.json()
        ok = d.get("code") == 0
        if not ok:
            logger.warning("feishu send_text 失败: %s", d.get("msg"))
        return {"ok": ok, "msg": d.get("msg", ""), "message_id": (d.get("data") or {}).get("message_id")}
    except Exception as e:
        logger.warning("feishu send_text 异常: %s", e)
        return {"ok": False, "error": str(e)}


# ── 状态 ──────────────────────────────────────────────────

def status() -> dict:
    cfg = load_config()
    return {
        "configured": is_configured(),
        "enabled": enabled(),
        "app_id": (cfg.get("app_id") or "")[:8] + "***" if is_configured() else "",
        "token_ok": bool(get_tenant_token()),
        "has_secret": bool(cfg.get("app_secret")),
        "webhook": bool(cfg.get("webhook_url")),
    }
