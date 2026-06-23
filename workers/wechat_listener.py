"""
workers/wechat_listener.py · iLink 微信收消息 → OPUS 大脑 → 带 token 回复 (卷六十一 · phase 2)

getupdates 长轮询 daemon thread。用户在微信发消息 → 缓存 context_token → 喂进大脑
(背景 turn·专用会话 api-wechat·复用 proactive 那套 background _chat_impl) → 把回复用刚拿到的
context_token 发回微信。这条让微信变成一条真聊天渠道，也让 24h 窗口持续续期。
kill switch: 用户发『opus stop』静默 / 『opus start』恢复 (逃生口)。
"""
from __future__ import annotations

import base64
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("opus.wechat")

_THREAD: Optional[threading.Thread] = None
_WECHAT_SID = "api-wechat"
_WECHAT_LABEL = "\U0001f4f1 \u5fae\u4fe1"
_KILL_OFF = "opus stop"
_KILL_ON = "opus start"

_STATE = {
    "started_at": None,
    "last_poll_at": None,
    "messages_in": 0,
    "media_in": 0,
    "replies_out": 0,
    "last_error": None,
}

# MessageItemType: TEXT=1 IMAGE=2 VOICE=3 FILE=4 VIDEO=5
_ITEM_TEXT, _ITEM_VOICE = 1, 3
_MEDIA_TYPES = (2, 4, 5)
_EXT_BY_MIME = {
    "image/jpeg": "jpg", "image/png": "png", "image/gif": "gif",
    "image/webp": "webp", "image/bmp": "bmp",
}


def get_state() -> dict:
    from workers import ilink_client

    s = dict(_STATE)
    s["alive"] = is_listener_alive()
    s["silent"] = ilink_client.is_silent()
    return s


def _text_of(m: dict) -> str:
    """拼出消息里所有 TEXT item 的文字 (一条消息可能多段)。"""
    out = []
    for it in m.get("item_list") or []:
        if it.get("type") == _ITEM_TEXT:
            t = (it.get("text_item") or {}).get("text") or ""
            if t:
                out.append(t)
    return " ".join(out).strip()


def _wechat_session() -> str:
    try:
        from daemon_session import get_session_meta, set_session_meta

        if (get_session_meta(_WECHAT_SID).get("label") or "") != _WECHAT_LABEL:
            set_session_meta(_WECHAT_SID, label=_WECHAT_LABEL)
    except Exception:
        pass
    return _WECHAT_SID


def _run_bg_turn(message: str, attachments: Optional[list] = None) -> str:
    from daemon_api import _ACTIVE_TURNS, _TURN_TO_SID, _TURNS_LOCK, _chat_impl

    sid = _wechat_session()
    turn_id = "wechat-" + str(int(time.time() * 1000))
    cancel = threading.Event()
    with _TURNS_LOCK:
        _ACTIVE_TURNS[turn_id] = cancel
        _TURN_TO_SID[turn_id] = sid
    try:
        from daemon_runtime import RUNTIME as _RT
        from provider_presets import safe_max_tokens as _smt
        result = _chat_impl(
            message=message,
            session_id=sid,
            auto_confirm=(os.environ.get("OPUS_WECHAT_AUTO_CONFIRM") or "confirm"),
            max_tokens=_smt(2048, getattr(_RT, "model", "")),
            attachments=attachments or None,
            progress=None,
            cancel_event=cancel,
            turn_id=turn_id,
            user_meta={"src": "wechat"},
        )
        return (result.get("reply") or "").strip()
    finally:
        with _TURNS_LOCK:
            _ACTIVE_TURNS.pop(turn_id, None)
            _TURN_TO_SID.pop(turn_id, None)


def _collect_media(items: list) -> tuple[list, list]:
    """下载+解密消息里的媒体 item。图片 → attachments(data_url·复用 look_at)；
    视频/文件 → 落盘 + 文字注记；语音 → 暂不支持提示。返回 (attachments, notes)。"""
    from workers import ilink_media

    attachments: list = []
    notes: list = []
    for idx, it in enumerate(items):
        t = it.get("type")
        if t == _ITEM_VOICE:
            notes.append("[对方发来一段语音·我暂时还不能听]")
            continue
        if t not in _MEDIA_TYPES:
            continue
        try:
            got = ilink_media.download_media_item(it)
        except Exception as e:
            logger.warning("inbound media 下载失败: %s", e)
            notes.append(f"[一个媒体下载失败: {type(e).__name__}]")
            continue
        if not got:
            continue
        if got["kind"] == "image":
            mime = ilink_media.sniff_image_mime(got["data"])
            ext = _EXT_BY_MIME.get(mime, "jpg")
            b64 = base64.b64encode(got["data"]).decode()
            attachments.append({
                "name": f"wechat_{int(time.time())}_{idx}.{ext}",
                "data_url": f"data:{mime};base64,{b64}",
            })
            _STATE["media_in"] += 1
        else:
            rel = ilink_media.save_inbound(got["kind"], got["data"], got.get("name", ""))
            label = "视频" if got["kind"] == "video" else "文件"
            notes.append(f"[对方发来一个{label}·已存到 {rel}]")
            _STATE["media_in"] += 1
    return attachments, notes


def _handle(msg: dict) -> None:
    from workers import ilink_client

    items = msg.get("item_list") or []
    text = _text_of(msg)
    ctx = msg.get("context_token")
    frm = msg.get("from_user_id", "")
    if ctx:
        ilink_client.save_context(ctx, frm, text)

    low = text.lower()
    if low == _KILL_OFF:
        from identity import localize_narration as _ln
        ilink_client.set_silent(True)
        ilink_client.send_text(_ln(f"OPUS 进入静默。发『{_KILL_ON}』唤醒。"), to_user_id=frm, context_token=ctx)
        logger.info("wechat kill switch ENGAGED by user")
        return
    if low == _KILL_ON:
        from identity import localize_narration as _ln
        ilink_client.set_silent(False)
        ilink_client.send_text(_ln("OPUS 在。继续。"), to_user_id=frm, context_token=ctx)
        logger.info("wechat kill switch RELEASED by user")
        return
    if ilink_client.is_silent():
        logger.debug("wechat silent · dropping %r", text[:40])
        return

    # 用户在微信开口了 → 窗口续上了 → 把之前窗口关时攒下的主动问候补发出来(卷七十四续十六)
    try:
        flushed = ilink_client.flush_pending()
        if flushed:
            logger.info("wechat flushed %d pending proactive greeting(s)", flushed)
    except Exception as e:
        logger.debug("flush pending failed: %s", e)

    attachments, notes = ([], [])
    if any(it.get("type") in _MEDIA_TYPES or it.get("type") == _ITEM_VOICE for it in items):
        attachments, notes = _collect_media(items)

    if not text and not attachments and not notes:
        return  # 没文字也没拿到任何媒体 → 没什么可回的

    brain_msg = text
    if notes:
        brain_msg = (brain_msg + "\n" + "\n".join(notes)).strip()
    if not brain_msg and attachments:
        brain_msg = "（这是对方在微信发来的图片，看看图里是什么，然后自然地回应他。）"

    _STATE["messages_in"] += 1
    reply = _run_bg_turn(brain_msg, attachments=attachments)
    if not reply:
        return
    r = ilink_client.send_text(reply, to_user_id=frm, context_token=ctx)
    if r.get("ok"):
        _STATE["replies_out"] += 1
    else:
        logger.warning("wechat reply send failed: %s", r)


def _loop(first_delay_sec: int) -> None:
    from workers import ilink_client
    from workers.resume_runner import _wait_runtime_ready

    _STATE["started_at"] = datetime.now(timezone.utc).isoformat()
    logger.info("wechat listener started · first poll in %ds", first_delay_sec)
    time.sleep(first_delay_sec)
    _wait_runtime_ready()
    try:
        ilink_client.notify_start()
    except Exception as e:
        logger.debug("notify_start failed: %s", e)

    buf = ""
    while True:
        _STATE["last_poll_at"] = datetime.now(timezone.utc).isoformat()
        try:
            resp = ilink_client.get_updates(buf)
            buf = resp.get("get_updates_buf", buf) or buf
            for m in resp.get("msgs") or []:
                if m.get("message_type") != 1:  # 只处理用户消息·跳过 bot 自己的
                    continue
                try:
                    _handle(m)
                except Exception as e:
                    logger.exception("wechat handle failed: %s", e)
            _STATE["last_error"] = None
        except Exception as e:
            _STATE["last_error"] = str(e)[:200]
            logger.debug("wechat poll err: %s", e)
            time.sleep(3)
        time.sleep(0.5)


def start_listener_in_background(
    first_delay_sec: Optional[int] = None,
) -> Optional[threading.Thread]:
    global _THREAD
    if _THREAD is not None and _THREAD.is_alive():
        return _THREAD

    from workers import ilink_client

    if not ilink_client.enabled():
        logger.info("wechat listener disabled (未扫码 / OPUS_WECHAT_ILINK=0)")
        return None

    if first_delay_sec is None:
        raw = (os.environ.get("OPUS_WECHAT_FIRST_DELAY_SEC") or "20").strip()
        first_delay_sec = int(raw) if raw.lstrip("-").isdigit() else 20

    t = threading.Thread(
        target=_loop,
        kwargs={"first_delay_sec": first_delay_sec},
        name="OpusWechatListener",
        daemon=True,
    )
    t.start()
    _THREAD = t
    return t


def is_listener_alive() -> bool:
    return _THREAD is not None and _THREAD.is_alive()
