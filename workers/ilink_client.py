"""
workers/ilink_client.py · iLink/ClawBot 微信渠道 · HTTP 客户端 + 上下文缓存 + 24h 窗口 (卷六十一)

官方个人号 bot 接口 (Tencent/openclaw-weixin · ilinkai.weixin.qq.com)。纯 HTTP/JSON·零 openclaw/Node。
官方 UI 钉死的规则: 用户先发消息 → 开 24h 窗口·窗口内带 context_token 能随时发·窗口外 /
零上下文 → ret:-2。所以这层维护『最近一枚 context_token + 时间戳』·并暴露 window_open() 让主动
CALL 判断能不能走微信。bot_token 是密钥·落 gitignored 的 data/runtime/ilink_token.json。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("opus.ilink")

_ROOT = Path(__file__).resolve().parent.parent
_TOKEN_FILE = _ROOT / "data" / "runtime" / "ilink_token.json"
_CTX_FILE = _ROOT / "data" / "runtime" / "ilink_last_context.json"
_SILENT_FLAG = _ROOT / "data" / "runtime" / "wechat_silent.flag"

# 官方插件常量 (Tencent/openclaw-weixin package.json): ilink_appid="bot" · version=2.4.3
_APP_ID = "bot"
_CHANNEL_VERSION = "2.4.3"
_CLIENT_VERSION = (2 << 16) | (4 << 8) | 3
_BASE_INFO = {"channel_version": _CHANNEL_VERSION, "bot_agent": "OpenClaw"}
_WINDOW_SEC = 23 * 3600  # 官方 24h · 留 1h 安全边界


def is_configured() -> bool:
    return _TOKEN_FILE.exists()


def enabled() -> bool:
    if (os.environ.get("OPUS_WECHAT_ILINK") or "1").strip().lower() in (
        "0", "false", "off", "no", "",
    ):
        return False
    return is_configured()


def load_token() -> tuple[str, str, str]:
    d = json.loads(_TOKEN_FILE.read_text(encoding="utf-8"))
    raw = d.get("raw", {})
    user = raw.get("ilink_user_id") or d.get("ilink_user_id") or ""
    return d["bot_token"], d.get("baseurl", "https://ilinkai.weixin.qq.com"), user


def _uin() -> str:
    return base64.b64encode(str(random.randint(0, 2**32 - 1)).encode()).decode()


def _headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {token}",
        "X-WECHAT-UIN": _uin(),
        "iLink-App-Id": _APP_ID,
        "iLink-App-ClientVersion": str(_CLIENT_VERSION),
    }


def _post(endpoint: str, body: dict, token: str, base: str, timeout: float) -> dict:
    payload = {**body, "base_info": _BASE_INFO}
    r = requests.post(
        f"{base}/ilink/bot/{endpoint}", headers=_headers(token), json=payload, timeout=timeout
    )
    try:
        return r.json()
    except ValueError:
        return {"_status": r.status_code, "_raw": r.text[:200]}


# ---------------------------------------------------------------- kill switch
def is_silent() -> bool:
    return _SILENT_FLAG.exists()


def set_silent(on: bool) -> None:
    try:
        if on:
            _SILENT_FLAG.parent.mkdir(parents=True, exist_ok=True)
            _SILENT_FLAG.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
        elif _SILENT_FLAG.exists():
            _SILENT_FLAG.unlink()
    except OSError as e:
        logger.warning("set_silent failed: %s", e)


# ---------------------------------------------------------------- context 缓存
def save_context(context_token: str, from_user_id: str, text: str = "") -> None:
    try:
        _CTX_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CTX_FILE.write_text(
            json.dumps(
                {
                    "context_token": context_token,
                    "from_user_id": from_user_id,
                    "text": text,
                    "obtained_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("save context failed: %s", e)


def load_context() -> dict:
    if not _CTX_FILE.exists():
        return {}
    try:
        return json.loads(_CTX_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def context_age_sec() -> Optional[float]:
    ts = load_context().get("obtained_at")
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds()
    except ValueError:
        return None


def window_open() -> bool:
    """用户最近一条消息是否还在 23h 窗口内 (官方 24h · 留安全边界)。"""
    age = context_age_sec()
    return age is not None and age < _WINDOW_SEC


def latest_context_token() -> Optional[str]:
    return load_context().get("context_token") or None


# ---------------------------------------------------------------- API
def get_updates(buf: str = "", timeout: float = 40) -> dict:
    token, base, _ = load_token()
    return _post("getupdates", {"get_updates_buf": buf or ""}, token, base, timeout)


def notify_start() -> dict:
    token, base, _ = load_token()
    return _post("msg/notifystart", {}, token, base, 10)


def send_text(
    text: str,
    *,
    to_user_id: Optional[str] = None,
    context_token: Optional[str] = None,
) -> dict:
    """给用户发文本。默认 to=token 里的 ilink_user_id·context 用缓存最新一枚。
    返回 {ok, ret, ...}。ret:-2 = 没 context / 窗口外。空 {} = 成功。"""
    token, base, user = load_token()
    to = to_user_id or user
    ctx = context_token or latest_context_token()
    if not to:
        return {"ok": False, "error": "no_to_user_id"}
    chunk = 3000
    chunks = [text[i : i + chunk] for i in range(0, len(text), chunk)] or [""]
    for c in chunks:
        msg = {
            "to_user_id": to,
            "message_type": 2,
            "message_state": 2,
            "client_id": str(uuid.uuid4()),
            "item_list": [{"type": 1, "text_item": {"text": c}}],
        }
        if ctx:
            msg["context_token"] = ctx
        resp = _post("sendmessage", {"msg": msg}, token, base, 20)
        if resp.get("ret") not in (0, None):  # -2 等 = 失败
            return {"ok": False, "ret": resp.get("ret"), "resp": resp}
    return {"ok": True, "chunks": len(chunks)}


def get_upload_url(params: dict, *, timeout: float = 30) -> dict:
    """拿 CDN 预签名上传地址 (getuploadurl)。params 见 GetUploadUrlReq。媒体上传第一步。"""
    token, base, _ = load_token()
    return _post("getuploadurl", params, token, base, timeout)


def send_media_item(
    item: dict,
    *,
    caption: str = "",
    to_user_id: Optional[str] = None,
    context_token: Optional[str] = None,
) -> dict:
    """发一个媒体 MessageItem (图片/视频/文件)。caption 非空时先作为独立 TEXT 消息发出·
    跟官方客户端一致 (每条 item 单独一个 sendmessage)。返回 {ok, ...}·ret:-2 = 没 context / 窗口外。"""
    token, base, user = load_token()
    to = to_user_id or user
    ctx = context_token or latest_context_token()
    if not to:
        return {"ok": False, "error": "no_to_user_id"}
    items = []
    cap = (caption or "").strip()
    if cap:
        items.append({"type": 1, "text_item": {"text": cap}})
    items.append(item)
    for it in items:
        msg = {
            "from_user_id": "",
            "to_user_id": to,
            "message_type": 2,
            "message_state": 2,
            "client_id": str(uuid.uuid4()),
            "item_list": [it],
        }
        if ctx:
            msg["context_token"] = ctx
        resp = _post("sendmessage", {"msg": msg}, token, base, 30)
        if resp.get("ret") not in (0, None):
            return {"ok": False, "ret": resp.get("ret"), "resp": resp}
    return {"ok": True}


def proactive_deliver(text: str) -> bool:
    """主动 CALL 用：窗口开 + 没静默 才把这条问候推到微信。返回是否真发出去。"""
    if not enabled() or is_silent() or not window_open():
        return False
    return bool(send_text(text).get("ok"))


def status() -> dict:
    age = context_age_sec()
    return {
        "configured": is_configured(),
        "enabled": enabled(),
        "silent": is_silent(),
        "window_open": window_open(),
        "context_age_hours": round(age / 3600, 2) if age is not None else None,
        "window_hours": _WINDOW_SEC / 3600,
    }
