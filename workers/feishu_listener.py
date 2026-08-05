"""
workers/feishu_listener.py · 飞书长连接收消息 → OPUS 大脑 → 回复 (0.9.0 · wish-aac348a1)

lark-oapi 官方 ws.Client 长连接 (无公网依赖 · 无 24h 窗口)。
im.message.receive_v1 事件 → _run_bg_turn (专用会话 api-feishu · 复用 proactive 那套 background _chat_impl)
→ 回复用 im/v1/messages 发回飞书。单聊 (p2p) 全回复 · 群聊暂不自动回 (避免机器人到处说话)。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger("opus.feishu")

_THREAD: Optional[threading.Thread] = None
_FEISHU_SID = "api-feishu"
_FEISHU_LABEL = "\u2708\ufe0f \u98de\u4e66 \u00b7 \u7528\u6237"

_STATE = {
    "started_at": None,
    "last_event_at": None,
    "messages_in": 0,
    "replies_out": 0,
    "last_error": None,
    "ws_connected": False,
}


def get_state() -> dict:
    s = dict(_STATE)
    s["alive"] = is_listener_alive()
    s["configured"] = _client_enabled()
    return s


def _client_enabled() -> bool:
    from workers import feishu_client
    return feishu_client.enabled()


def _feishu_session() -> str:
    try:
        from daemon_session import get_session_meta, set_session_meta
        if (get_session_meta(_FEISHU_SID).get("label") or "") != _FEISHU_LABEL:
            set_session_meta(_FEISHU_SID, label=_FEISHU_LABEL)
    except Exception:
        pass
    return _FEISHU_SID


def _run_bg_turn(message: str) -> str:
    from daemon_api import _ACTIVE_TURNS, _TURN_TO_SID, _TURNS_LOCK, _chat_impl

    sid = _feishu_session()
    turn_id = "feishu-" + str(int(time.time() * 1000))
    cancel = threading.Event()
    with _TURNS_LOCK:
        _ACTIVE_TURNS[turn_id] = cancel
        _TURN_TO_SID[turn_id] = sid
    try:
        from daemon_runtime import bg_max_tokens
        result = _chat_impl(
            message=message,
            session_id=sid,
            auto_confirm=(os.environ.get("OPUS_FEISHU_AUTO_CONFIRM") or "confirm"),
            max_tokens=bg_max_tokens(),
            attachments=None,
            progress=None,
            cancel_event=cancel,
            turn_id=turn_id,
            user_meta={"src": "feishu"},
        )
        return (result.get("reply") or "").strip()
    finally:
        with _TURNS_LOCK:
            _ACTIVE_TURNS.pop(turn_id, None)
            _TURN_TO_SID.pop(turn_id, None)


def _text_of_message(content: str) -> str:
    """im.message.receive_v1 的 content 是 JSON 字符串: {"text": "..."} / {"post": {...}} 等。"""
    try:
        d = json.loads(content or "{}")
    except Exception:
        return (content or "").strip()
    if "text" in d:
        return str(d["text"]).strip()
    # post (富文本) · 取所有 text 段拼起来
    if "post" in d:
        out = []
        for para in (d["post"].get("zh_cn") or {}).get("content") or []:
            for seg in para:
                if isinstance(seg, dict) and seg.get("tag") == "text":
                    out.append(str(seg.get("text", "")))
        return " ".join(out).strip()
    return (content or "").strip()


def _reply_with(text: str, chat_id: str, msg_type: str = "text", is_group: bool = False,
                message_id: str = "", file_key: str = "", file_name: str = "") -> None:
    """统一回复链路 (0.9.0 BETA): 文件读取 + 飞书链接自动拉取 + 群总结指令 + LLM + 发送。"""
    _STATE["last_event_at"] = time.strftime("%H:%M:%S")
    logger.info("feishu 收到%s: %s (type=%s)", "群消息" if is_group else "p2p", text[:60], msg_type)

    extra = ""

    # ⓪ 文件消息 → 下载解析 (群里发文件被 @ 场景)
    if msg_type == "file" and file_key and message_id:
        try:
            from workers.feishu_docs import fetch_file
            fr = fetch_file(message_id, file_key, file_name)
            if fr.get("ok") and fr.get("found") and fr.get("text"):
                text = f"看看这个文件「{file_name}」并总结要点" if not text else text
                extra = f"\n\n[文件 {file_name} · 内容]\n{fr['text']}"
            elif fr.get("ok") and (fr.get("unsupported") or fr.get("empty")):
                text = f"[收到文件「{file_name}」 · {fr.get('error', '暂不支持解析')}]"
            elif not fr.get("ok"):
                text = f"[文件读取失败: {fr.get('error', '')}]"
        except Exception as e:
            logger.warning("feishu 文件处理异常: %s", e)
            text = f"[文件处理异常: {type(e).__name__}]"

    # ① 飞书链接自动拉取 (文档/表格/多维表格)
    try:
        from workers.feishu_docs import fetch_by_link
        link_res = fetch_by_link(text)
        if link_res.get("found") and link_res.get("ok"):
            extra = (f"\n\n[自动拉取的飞书{link_res['url_type']} · {link_res.get('title', '')}]\n"
                     f"{link_res.get('text', '')}")
        elif link_res.get("found") and not link_res.get("ok"):
            extra = f"\n\n[拉取失败: {link_res.get('error', '')}]"
    except Exception as e:
        logger.warning("feishu 链接拉取异常: %s", e)

    # ② 群总结指令 → 拉群最近消息
    if is_group and _is_summary_request(text):
        group_msgs = _fetch_group_messages(chat_id, 30)
        if group_msgs:
            extra += f"\n\n[群聊最近消息·供总结]\n{group_msgs}"
            text = f"请总结这个飞书群的近期消息，要点式列出：\n{text}"

    reply = _run_bg_turn(text + extra)
    from workers import feishu_client
    r = feishu_client.send_text(reply or "(抱歉·我这边没生成出回复)", chat_id, "chat_id")
    if r.get("ok"):
        _STATE["replies_out"] += 1


def _is_summary_request(text: str) -> bool:
    return any(k in text for k in ("总结", "汇总", "回顾", "摘要"))


def _handle_message(data) -> None:
    """im.message.receive_v1 事件处理 (lark-oapi 的 data 对象)。

    lark-oapi 新版: ws 分发传的是【事件信封】P2ImMessageReceiveV1 (字段 event/header/token/type) ·
    业务数据在 data.event (P2ImMessageReceiveV1Data · 含 .message/.sender) ·
    data.message 直取会炸 (AttributeError · 2026-08-05 线上事故)。
    兼容老结构: 老版 data 直接是业务对象 (有 .message) → event 兜底回退 data 自身。

    0.9.0 BETA · 群聊支持: chat_type=group 时检查 @ 机器人 (mentions 含机器人 open_id) → 被 @ 才回
    (对标 OpenClaw requireMention) · 没 @ 直接忽略不打扰。
    """
    try:
        inner = getattr(data, "event", data)  # 新信封取 event · 老结构 data 即业务
        msg = getattr(inner, "message", None)
        if msg is None:
            logger.warning("feishu 事件无 message 字段: %s", type(data).__name__)
            return
        # 0.9.0 BETA · 消息去重 (飞书断线重连/超时重试会重放事件 · 同一 message_id 只回一次)
        message_id = getattr(msg, "message_id", "") or ""
        if message_id:
            now = time.time()
            _STATE.setdefault("seen_msg_ids", {})
            if message_id in _STATE["seen_msg_ids"]:
                logger.info("feishu 重复消息跳过: %s", message_id)
                return
            _STATE["seen_msg_ids"][message_id] = now
            # 环形清理: 只留最近 5 分钟的去重窗口 (防内存涨)
            cutoff = now - 300
            stale = [k for k, v in _STATE["seen_msg_ids"].items() if v < cutoff]
            for k in stale:
                del _STATE["seen_msg_ids"][k]
            if len(_STATE["seen_msg_ids"]) > 2000:
                # 兜底: 超 2000 条清一半 (最老的)
                ordered = sorted(_STATE["seen_msg_ids"].items(), key=lambda kv: kv[1])
                for k, _ in ordered[: len(ordered) // 2]:
                    del _STATE["seen_msg_ids"][k]
        chat_type = getattr(msg, "chat_type", "") or ""
        content = getattr(msg, "content", "") or ""
        chat_id = getattr(msg, "chat_id", "") or ""
        msg_type = getattr(msg, "message_type", "") or "text"
        text = _text_of_message(content)
        # file 消息: 解析 file_key/file_name (下载读取用)
        file_key, file_name = "", ""
        if msg_type == "file":
            try:
                fcnt = json.loads(content)
                file_key = fcnt.get("file_key", "") or fcnt.get("file_token", "")
                file_name = fcnt.get("file_name", "")
            except Exception:
                pass
        if not text and msg_type != "file":
            # 非文字消息 (图片/富文本等) 解析不出 → 不沉默 · 回一句提示
            text = f"[收到一条 {msg_type} 消息 · 我暂时只处理文字和文档/表格链接]"
        if not text and msg_type == "file":
            text = f"[收到文件 {file_name}]"
        if not chat_id:
            return

        if chat_type == "p2p":
            _STATE["messages_in"] += 1
            _reply_with(text, chat_id, msg_type, is_group=False,
                        message_id=message_id, file_key=file_key, file_name=file_name)
        elif chat_type == "group":
            # 群消息: 只有 @ 了机器人 (或 mention 机器人名字) 才回
            mentions = getattr(msg, "mentions", None) or []
            bot_id = _bot_open_id()
            mentioned = False
            for m in mentions:
                if _mention_open_id(m) and bot_id and _mention_open_id(m) == bot_id:
                    mentioned = True
                    break
            if not mentioned:
                return  # 群消息没 @ 机器人 → 不打扰
            text = _strip_mentions(text, mentions)
            _STATE["messages_in"] += 1
            _reply_with(text, chat_id, msg_type, is_group=True,
                        message_id=message_id, file_key=file_key, file_name=file_name)
    except Exception as e:
        _STATE["last_error"] = f"{type(e).__name__}: {e}"
        logger.warning("feishu handle 异常: %s", e)


# ── 0.9.0 BETA · 群消息辅助 ──────────────────────────────

_BOT_OPEN_ID_CACHE = {"open_id": None}


def _bot_open_id() -> Optional[str]:
    """机器人自己的 open_id (bot/v3/info · 缓存)。群消息 @ 检测用。"""
    if _BOT_OPEN_ID_CACHE["open_id"]:
        return _BOT_OPEN_ID_CACHE["open_id"]
    try:
        import requests
        from workers import feishu_client
        tok = feishu_client.get_tenant_token()
        if not tok:
            return None
        r = requests.get(
            "https://open.feishu.cn/open-apis/bot/v3/info",
            headers={"Authorization": f"Bearer {tok}"}, timeout=10,
        )
        d = r.json()
        if d.get("code") == 0:
            _BOT_OPEN_ID_CACHE["open_id"] = d["bot"]["open_id"]
            return _BOT_OPEN_ID_CACHE["open_id"]
    except Exception as e:
        logger.warning("feishu bot info 获取失败: %s", e)
    return None


def _mention_open_id(m) -> Optional[str]:
    """从 mention 条目取 open_id · 兼容 dict 和 lark MentionEvent 对象两种形态。"""
    if isinstance(m, dict):
        mid = m.get("id") or {}
        return mid.get("open_id") if isinstance(mid, dict) else mid
    mid = getattr(m, "id", None)
    if mid is None:
        return None
    return mid.get("open_id") if isinstance(mid, dict) else getattr(mid, "open_id", None)


def _strip_mentions(text: str, mentions) -> str:
    """把 @_user_1 这类占位符替换成 @名字 (或删除) · 兼容 dict / MentionEvent 对象。"""
    for m in mentions or []:
        key = m.get("key") if isinstance(m, dict) else getattr(m, "key", None)
        name = m.get("name") if isinstance(m, dict) else getattr(m, "name", None)
        if key:
            text = text.replace(key, f"@{name}" if name else "")
    return text.strip()


def _fetch_group_messages(chat_id: str, count: int = 30) -> Optional[str]:
    """拉群最近消息 (im/v1/messages · 按创建时间倒序) · 供总结用。"""
    try:
        import requests
        from workers import feishu_client
        tok = feishu_client.get_tenant_token()
        if not tok:
            return None
        r = requests.get(
            "https://open.feishu.cn/open-apis/im/v1/messages",
            headers={"Authorization": f"Bearer {tok}"},
            params={
                "container_id_type": "chat", "container_id": chat_id,
                "page_size": count, "sort_type": "ByCreateTimeDesc",
            },
            timeout=15,
        )
        d = r.json()
        if d.get("code") != 0:
            logger.warning("feishu 群消息拉取失败: %s", d.get("msg"))
            return None
        items = d.get("data", {}).get("items") or []
        lines = []
        for it in reversed(items):  # 倒序翻转回正序 (最新在最后)
            sender = (it.get("sender") or {}).get("id") or "?"
            body = it.get("body") or {}
            try:
                content = json.loads(body.get("content") or "{}").get("text", "")
            except Exception:
                content = body.get("content") or ""
            lines.append(f"[{sender}] {content}")
        return "\n".join(lines)[-8000:]
    except Exception as e:
        logger.warning("feishu 群消息异常: %s", e)
        return None


def _event_handler_builder():
    """构建 lark-oapi 事件分发器 · 注册 im.message.receive_v1。"""
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import P2ImMessageReceiveV1Data

        def do_p2_im_message_receive_v1(data: P2ImMessageReceiveV1Data) -> None:
            _STATE["ws_connected"] = True
            _handle_message(data)

        return (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1)
            .build()
        )
    except Exception as e:
        logger.error("feishu event handler 构建失败: %s", e)
        return None


def _run_ws_loop() -> None:
    """阻塞跑 lark ws.Client (长连接) · 断线异常退出由外层重试。"""
    try:
        import lark_oapi as lark
        from workers import feishu_client
        if not feishu_client.enabled():
            logger.info("feishu 未启用 · ws 不启动")
            return
        handler = _event_handler_builder()
        if handler is None:
            return
        cfg = feishu_client.load_config()
        client = lark.ws.Client(
            cfg["app_id"], cfg["app_secret"],
            event_handler=handler,
            log_level=lark.LogLevel.INFO,
        )
        _STATE["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        logger.info("feishu ws 长连接启动")
        client.start()  # 阻塞 · 内部自动重连 (lark 处理)
    except Exception as e:
        _STATE["last_error"] = f"{type(e).__name__}: {e}"
        logger.warning("feishu ws 异常退出: %s", e)


def start_listener_in_background() -> Optional[threading.Thread]:
    """daemon 启动时调用 · 飞书已配置且启用则拉起长连接线程。"""
    global _THREAD
    if _THREAD and _THREAD.is_alive():
        return _THREAD
    from workers import feishu_client
    if not feishu_client.enabled():
        return None
    _THREAD = threading.Thread(target=_run_ws_loop, name="feishu-listener", daemon=True)
    _THREAD.start()
    logger.info("feishu listener 已拉起 (thread=%s)", _THREAD.name)
    return _THREAD


def is_listener_alive() -> bool:
    return bool(_THREAD and _THREAD.is_alive())
