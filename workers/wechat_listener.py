"""
workers/wechat_listener.py · iLink 微信收消息 → OPUS 大脑 → 带 token 回复 (卷六十一 · phase 2)

getupdates 长轮询 daemon thread。BRO 在微信发消息 → 缓存 context_token → 喂进 OPUS 大脑
(背景 turn·专用会话 api-wechat·复用 proactive 那套 background _chat_impl) → 把回复用刚拿到的
context_token 发回微信。这条让微信变成 OPUS 的真聊天渠道，也让 24h 窗口持续续期。
kill switch: BRO 发『opus stop』静默 / 『opus start』恢复 (沿用 wcferry bridge 的逃生口)。
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
_WORKER: Optional[threading.Thread] = None          # P0 · 单 worker 串行消费入站 (改自同步 _handle)
_INBOUND_QUEUE: list[dict] = []                      # P0 · _loop 收消息暂存 · worker 取
_WECHAT_SID = "api-wechat"
_WECHAT_LABEL = "\U0001f4f1 \u5fae\u4fe1 · BRO"
_KILL_OFF = "opus stop"
_KILL_ON = "opus start"

# ── 卷八十一续 · P0 单会话排他 + FIFO 队列 (Hermes queue 语义 · A 跑完 B 自动接上) ──
# 根因 (BRO 社区反馈): 原来每条消息直接 _run_bg_turn 无锁无队列 → A 处理中 B 又开一个线程
# 抢同一 api-wechat 会话 → 并发写冲突 / 回复串线 / "把自己玩死了"。
# 设计: _BUSY_LOCK 排他 (同一时刻只有一个 turn 在跑) · B 到达进 _PENDING_QUEUE (FIFO)
# A 完成 → 取队头自动跑下一轮 · 每条都落地按序不丢。加 _QUEUE_MAX 上限防无限堆积。
_BUSY_LOCK = threading.Lock()
_PENDING_QUEUE: list[dict] = []  # [{msg, frm, ctx, attachments, notes, brain_msg}]
_QUEUE_MAX = 20
_STATE_EXTRA = {"queued": 0, "busy": False, "last_queue_overflow": None}

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
    s.update(dict(_STATE_EXTRA))  # P0 · 队列/忙态 (卷八十一续)
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


def _run_bg_turn(message: str, attachments: Optional[list] = None, progress_cb=None) -> str:
    from daemon_api import _ACTIVE_TURNS, _TURN_TO_SID, _TURNS_LOCK, _chat_impl

    sid = _wechat_session()
    turn_id = "wechat-" + str(int(time.time() * 1000))
    cancel = threading.Event()
    with _TURNS_LOCK:
        _ACTIVE_TURNS[turn_id] = cancel
        _TURN_TO_SID[turn_id] = sid
    try:
        from daemon_runtime import bg_max_tokens
        result = _chat_impl(
            message=message,
            session_id=sid,
            auto_confirm=(os.environ.get("OPUS_WECHAT_AUTO_CONFIRM") or "confirm"),
            max_tokens=bg_max_tokens(),
            attachments=attachments or None,
            progress=progress_cb,   # P2 · tool_progress 事件 → 工具行节流
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
            # wish-241e0014 · 语音三态 (BRO 拍板: 可选更新 · 对话路径零下载):
            #   ① 依赖+模型就绪 → silk → wav → whisper 转写 → [转写: xxx]
            #   ② 未就绪 → 落盘存证 + 引导文案 (不阻塞 · 不下载 · 用户去设置页开)
            try:
                from workers import stt_transcribe, ilink_media as _im
                got = _im.download_media_item(it)
                if not got or not got.get("data"):
                    notes.append("[BRO 发来一段语音·我暂时还不能听]")
                    continue
                rel = _im.save_inbound("voice", got["data"], got.get("name") or "voice.silk")
                if stt_transcribe.stt_status().get("ready"):
                    text = stt_transcribe.transcribe_silk(str(rel))
                    if text:
                        notes.append(f"[BRO 发来一段语音·转写: {text}]")
                    else:
                        notes.append(f"[BRO 发来一段语音·转写失败·音频已存 {rel}]")
                else:
                    # 未装/未下载 → 引导去设置页 (对话路径零下载)
                    notes.append(f"[BRO 发来一段语音·已存 {rel}·语音识别增强未开启·去 设置→视觉→语音识别增强 开启即可转文字]")
            except Exception as e:
                logger.debug("voice save failed: %s", e)
                notes.append("[BRO 发来一段语音·我暂时还不能听]")
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
            notes.append(f"[BRO 发来一个{label}·已存到 {rel}]")
            _STATE["media_in"] += 1
    return attachments, notes


class _TypingTicker:
    """『对方正在输入』续发器 (P0 · 移植墨言 wish-2dc6cf44 · 对标 cc-connect StartTyping)。
    start 起 daemon 线程每 5s 续发 start · stop 停线程 + 发 stop。失败静默不打断主流程。"""

    def __init__(self, frm: str, ctx: str):
        self.frm = frm
        self.ctx = ctx
        self._ticket: Optional[str] = None
        self._stop_ev = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        from workers import ilink_client

        try:
            self._ticket = ilink_client.get_typing_ticket(self.frm, self.ctx)
            if not self._ticket:
                return
            ilink_client.send_typing(1, to_user_id=self.frm, context_token=self.ctx, typing_ticket=self._ticket)
            self._stop_ev.clear()
            self._thread = threading.Thread(target=self._beat, name="WechatTyping", daemon=True)
            self._thread.start()
        except Exception:
            pass

    def _beat(self) -> None:
        from workers import ilink_client

        while not self._stop_ev.wait(5):
            try:
                ilink_client.send_typing(1, to_user_id=self.frm, context_token=self.ctx, typing_ticket=self._ticket)
            except Exception:
                pass

    def stop(self) -> None:
        from workers import ilink_client

        self._stop_ev.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._ticket:
            try:
                ilink_client.send_typing(2, to_user_id=self.frm, context_token=self.ctx, typing_ticket=self._ticket)
            except Exception:
                pass


class _HumanTurnNarrator:
    """拟人化进度叙事 (v3 · BRO 拍板 2026-08-14): 取代 ⚙ 工具行。

    BRO 原话: "有没有办法让他更拟人一下，比如我现在要开始做XX，大概X分钟后回你，
    那就不需要把一堆工具显示出来了，没意义啊。"

    设计: 工具名对用户没意义 · 人不会跟朋友说"我在调用 web_search"。
    改为像人一样报进度:
      - 第一条 tool_call 事件 → 发拟人开场: "收到！我开始处理 XX 了，大概一两分钟，
        弄完马上回你。" (XX = 用户消息前 20 字 · 不是工具名)
      - 中途 >25s 后 → 最多补一句: "还在弄，快好了，稍等。"
      - 之后静默 → 正式回复是唯一"结果"。
    配合 typing 心跳 · 用户全程知道"在做事"且不被打扰。
    """

    def __init__(self, frm: str, ctx: str, user_text: str):
        self.frm = frm
        self.ctx = ctx
        self._user_text = (user_text or "").strip()
        self._opened = False
        self._mid_note_sent = False
        self._start_ts = 0.0
        self._lock = threading.Lock()

    def on_progress(self, ev_type: str, ev_data: dict) -> None:
        """tool_call / tool_progress 事件 → 拟人进度 (不显示工具名)。"""
        if ev_type != "tool_call" and ev_type != "tool_progress":
            return
        now = time.time()
        with self._lock:
            if not self._opened:
                self._opened = True
                self._start_ts = now
                text = self._build_opener()
            elif not self._mid_note_sent and (now - self._start_ts) > 25.0:
                self._mid_note_sent = True
                text = self._build_comfort()
            else:
                return
        try:
            from workers import ilink_client
            ilink_client.send_text(
                text,
                to_user_id=self.frm, context_token=self.ctx)
        except Exception:
            pass

    def _build_opener(self) -> str:
        """开场白: 从风格包轮换取 (wish-9585aa62) · 自由风格已蒸馏成完整句子。

        老方案 (localize_styled_narration 换词) 只有 5 组关键词·自由文本匹配不到
        就静默落回中性——BRO 实测"每次都是一样的"。现在由蒸馏的变体池轮换:
        设定过风格 → 风格句; 没设定 (母体) → OPUS 默认风格句。零 LLM 零延迟。
        """
        from identity import narration_opener
        return narration_opener(snippet=self._user_text[:20])

    def _build_comfort(self) -> str:
        """中途安抚 (>25s): 风格包轮换取。"""
        from identity import narration_comfort
        return narration_comfort()


def _queue_pending(msg: dict, frm: str, ctx: str, attachments: list, notes: list, brain_msg: str) -> bool:
    """A 处理中 B 到达 → 进 FIFO 队列 (P0 · Hermes queue 语义)。超上限丢弃+告警。"""
    global _STATE_EXTRA
    if len(_PENDING_QUEUE) >= _QUEUE_MAX:
        _STATE_EXTRA["last_queue_overflow"] = datetime.now(timezone.utc).isoformat()
        logger.warning("wechat pending queue full (%d) · dropping follow-up", _QUEUE_MAX)
        return False
    _PENDING_QUEUE.append({
        "msg": msg, "frm": frm, "ctx": ctx,
        "attachments": attachments, "notes": notes, "brain_msg": brain_msg,
    })
    _STATE_EXTRA["queued"] = len(_PENDING_QUEUE)
    return True


def _drain_queue() -> None:
    """A 完成 → 取队头自动跑下一轮 (P0 · Hermes _promote_queued_event)。"""
    while True:
        with _BUSY_LOCK:
            if not _PENDING_QUEUE:
                _STATE_EXTRA["busy"] = False
                _STATE_EXTRA["queued"] = 0
                return
            item = _PENDING_QUEUE.pop(0)
            _STATE_EXTRA["queued"] = len(_PENDING_QUEUE)
        try:
            _process_one(item)
        except Exception as e:
            logger.exception("wechat queued turn failed: %s", e)
            # 单条失败不阻塞队列 · 继续下一条


def _notify_confirm_request(frm: str, ctx: str, ev_data: dict) -> None:
    """confirm_request SSE 事件 → 给 BRO 发一条确认消息 (wish-2f0c731a)。

    微信通道没有确认卡片 UI · 用文字消息带回复指令当按钮:
      工具 + 风险 + 「回复『确认』放行 / 『取消』拒绝」
    BRO 的回复会被 _maybe_resolve_confirm 拦截 resolve · 不喂 LLM。
    发送失败静默 (SSE 卡片仍会推给 WebUI · 不阻塞流程)。
    """
    try:
        from workers import ilink_client
        tool = (ev_data or {}).get("tool_name") or "工具"
        risk = (ev_data or {}).get("risk_explanation") or "（OPUS 没说明风险）"
        mit = (ev_data or {}).get("mitigation") or ""
        text = (
            f"⚠️ 我需要你拍板：\n"
            f"操作：{tool}\n"
            f"风险：{risk}"
        )
        if mit:
            text += f"\n规避：{mit}"
        text += "\n回复【确认】放行 · 回复【取消】拒绝"
        ilink_client.send_text(text, to_user_id=frm, context_token=ctx)
        logger.info("wechat confirm_request sent · tool=%s", tool)
    except Exception as e:
        logger.debug("wechat confirm notify failed: %s", e)


def _maybe_resolve_confirm(text: str, frm: str) -> Optional[dict]:
    """BRO 微信回复确认/取消 → 找到该会话最近的 pending confirm → resolve。

    匹配规则:
      - 确认词: 确认/同意/可以/放行/批准/ok/行/好/干
      - 取消词: 取消/拒绝/不行/不要/别/不干/否
    只看简短回复 (≤6 字) · 避免把正常对话误判成确认。
    找到 → 调 /turns/{turn_id}/confirm 等价逻辑 (进程内直接 resolve)。
    返回 None = 不是确认回复 (正常走 LLM) · dict = 已处理。
    """
    import re as _re

    t = (text or "").strip()
    if not t or len(t) > 6:
        return None
    confirm_re = _re.compile(r"^(确认|同意|可以|放行|批准|ok|okay|行|好|干|是|对)[!！。.]*$", _re.I)
    cancel_re = _re.compile(r"^(取消|拒绝|不行|不要|别|不干|否|不)[!！。.]*$", _re.I)

    decision = None
    if confirm_re.match(t):
        decision = "approve_once"
    elif cancel_re.match(t):
        decision = "deny"
    else:
        return None

    # 找该 frm 最近的 pending confirm
    try:
        from daemon_api import _PENDING_CONFIRMS, _PENDING_CONFIRMS_LOCK
        with _PENDING_CONFIRMS_LOCK:
            candidates = [p for p in _PENDING_CONFIRMS.values()
                          if p.get("turn_id", "").startswith("wechat-")]
            if not candidates:
                return {"ok": False, "detail": "当前没有待确认的操作"}
            # 取最近创建的
            latest = max(candidates, key=lambda p: p.get("created_at") or 0)
            tool_call_id = next((k for k, v in _PENDING_CONFIRMS.items() if v is latest), None)
            turn_id = latest.get("turn_id") or ""
            if not tool_call_id:
                return {"ok": False, "detail": "找不到待确认的操作"}
    except Exception as e:
        logger.debug("wechat resolve find failed: %s", e)
        return {"ok": False, "detail": "确认解析失败"}

    # 进程内直接 resolve (等价 POST /turns/{turn_id}/confirm · 不走 HTTP 免 auth 开销)
    try:
        from api_routes.chat import _resolve_confirm_inline
        result = _resolve_confirm_inline(tool_call_id, turn_id, decision, reason=f"wechat 文字回复: {t}")
        ok = bool(result and result.get("ok"))
        logger.info(
            "wechat confirm resolved · tool_call=%s · decision=%s · ok=%s · reply=%r",
            tool_call_id, decision, ok, t,
        )
        return {
            "ok": ok,
            "action_label": "放行" if (decision == "approve_once" and ok) else "拒绝" if ok else "处理",
            "detail": result.get("detail") if result else "处理失败",
        }
    except Exception as e:
        logger.debug("wechat resolve failed: %s", e)
        return {"ok": False, "detail": f"确认处理失败: {type(e).__name__}"}


def _process_one(item: dict) -> None:
    """真正跑一次背景 turn + typing 心跳 + 工具行节流 (P0/P2 核心)。"""
    from workers import ilink_client

    frm, ctx = item["frm"], item["ctx"]
    brain_msg, attachments = item["brain_msg"], item.get("attachments") or []
    ticker = _TypingTicker(frm, ctx)
    narrator = _HumanTurnNarrator(frm, ctx, brain_msg)

    # progress 回调: tool_call 事件 → 拟人开场/中途安抚 (v3 · 不再显示工具名)
    # confirm_request 事件 → 发确认消息给 BRO (wish-2f0c731a · 微信无确认卡片 UI · 文字回复当按钮)
    def _progress_sink(ev_type: str, ev_data: dict) -> None:
        try:
            if ev_type == "confirm_request":
                _notify_confirm_request(frm, ctx, ev_data)
                return
            narrator.on_progress(ev_type, ev_data)
        except Exception:
            pass

    _STATE["messages_in"] += 1
    ticker.start()
    try:
        reply = _run_bg_turn(brain_msg, attachments=attachments, progress_cb=_progress_sink)
    except Exception as e:
        # 墨言094-2 真增量 · turn 异常兜底: 用户不再无回应干等。
        # 发一条"处理出错"安抚 · 兜底失败静默 (不叠异常)。
        logger.warning("wechat turn 异常终止 · 发兜底消息 · err=%s", e)
        try:
            from identity import localize_narration as _ln
            ilink_client.send_text(
                _ln("（刚才处理出错了，稍等重试一下）"),
                to_user_id=frm, context_token=ctx,
            )
        except Exception as e2:
            logger.warning("wechat 兜底消息发送失败: %s", e2)
        return
    finally:
        ticker.stop()
    if not reply:
        return
    # P2 · 长回复分块带 (N/M) 标记 (send_text 已分块 · 这里加标记)
    r = ilink_client.send_text(reply, to_user_id=frm, context_token=ctx)
    if r.get("ok") is False and r.get("ret") not in (None,):
        logger.warning("wechat reply send failed: %s", r)
    _STATE["replies_out"] += 1


def _enqueue_inbound(msg: dict) -> None:
    """_loop 收消息入队 + 保证单 worker 在跑 (P0 修复 · BRO 实测排队告知没触发)。

    根因: 原来 _loop 同步 _handle → A 跑时 _loop 阻塞读不到 B。
    改: 消息进 _INBOUND_QUEUE · _worker 单线程串行消费 · worker 里再走
    _handle 的排他锁 + FIFO 语义 (A 跑时 B 到达 → busy 分支排队告知)。
    """
    global _WORKER
    _INBOUND_QUEUE.append(msg)
    if _WORKER is None or not _WORKER.is_alive():
        _WORKER = threading.Thread(target=_worker_loop, name="OpusWechatWorker", daemon=True)
        _WORKER.start()


def _worker_loop() -> None:
    """消息分发器 (P0 修复 · BRO 实测排队告知没触发)。

    每条消息【独立线程】进 _handle · 并发进入才能触发 busy 分支排队告知。
    (原实现: 单 worker 串行消费 → A 跑时 B 排队在 INBOUND · 等 A 完锁已释放
     → B 走正常路径 · busy 分支永不触发 = 跟原来同步 _loop 一样失效)
    _handle 内部 _BUSY_LOCK 保证同一时刻只有一个真跑 turn · 其余排队告知。
    """
    while True:
        try:
            msg = _INBOUND_QUEUE.pop(0)
        except IndexError:
            return  # 队空 → 分发器退出 (下条消息 _enqueue_inbound 重启)
        try:
            t = threading.Thread(target=_handle, args=(msg,), daemon=True,
                                 name="OpusWechatTurn")
            t.start()  # 不 join · 立刻取下一条继续分发
        except Exception as e:
            logger.exception("wechat dispatch failed: %s", e)


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
        logger.info("wechat kill switch ENGAGED by BRO")
        return
    if low == _KILL_ON:
        from identity import localize_narration as _ln
        ilink_client.set_silent(False)
        ilink_client.send_text(_ln("OPUS 在。继续。"), to_user_id=frm, context_token=ctx)
        logger.info("wechat kill switch RELEASED by BRO")
        return

    # wish-2f0c731a · 确认回复拦截: BRO 回"确认/同意/可以/放行"或"取消/拒绝/不行"
    # 且当前微信会话存在 pending confirm → 直接 resolve · 不喂 LLM。
    # 微信通道没有确认卡片 UI (BRO 实测) · 用文字回复当按钮。
    try:
        resolved = _maybe_resolve_confirm(text, frm)
        if resolved is not None:
            if resolved.get("ok"):
                ilink_client.send_text(
                    f"收到，已{resolved.get('action_label', '处理')}。继续干活。",
                    to_user_id=frm, context_token=ctx,
                )
            else:
                ilink_client.send_text(
                    f"收到。{resolved.get('detail', '')}",
                    to_user_id=frm, context_token=ctx,
                )
            return
    except Exception as _e:
        logger.debug("confirm resolve check failed: %s", _e)

    if ilink_client.is_silent():
        logger.debug("wechat silent · dropping %r", text[:40])
        return

    # BRO 在微信开口了 → 窗口续上了 → 把之前窗口关时攒下的主动问候补发出来(卷七十四续十六)
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
        brain_msg = "（这是 BRO 在微信发来的图片，看看图里是什么，然后自然地回应他。）"

    # P0 · 单会话排他 + FIFO 队列 (Hermes queue 语义 · 卷八十一续)
    # 忙(A 在跑) → B 进队列 · 不并发抢会话 · A 完 B 自动接上 · 每条都落地按序不丢。
    # 忙时给 B 一条轻量告知 (P1) · 让用户知道"收到了·排队中" 而不是石沉大海。
    if not _BUSY_LOCK.acquire(blocking=False):
        queued = _queue_pending(msg, frm, ctx, attachments, notes, brain_msg)
        if queued:
            try:
                from identity import localize_narration as _ln
                ilink_client.send_text(
                    _ln("收到。正在处理上一条，这条排队中，处理完马上回你。"),
                    to_user_id=frm, context_token=ctx,
                )
            except Exception:
                pass
        return

    try:
        _STATE_EXTRA["busy"] = True
        _process_one({"msg": msg, "frm": frm, "ctx": ctx,
                      "attachments": attachments, "notes": notes, "brain_msg": brain_msg})
    finally:
        _BUSY_LOCK.release()
    # A 完成 → drain 队列 (取队头自动跑下一轮 · 直到队空)
    _drain_queue()


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
                    # P0 修复 (BRO 实测: 排队告知没触发) — 根因: 原来同步 _handle(m)
                    # A 在跑时 _loop 阻塞在 _handle · B 根本读不出来 → 等 A 完 B 才进
                    # (锁已释放走正常路径) → busy 分支永远不触发。
                    # 改: _loop 只收消息入队立即返回继续轮询 · 后台 worker 串行消费。
                    _enqueue_inbound(m)
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
