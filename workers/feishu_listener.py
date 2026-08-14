"""
workers/feishu_listener.py · 飞书长连接收消息 → OPUS 大脑 → 回复 (0.9.0 · wish-aac348a1)

lark-oapi 官方 ws.Client 长连接 (无公网依赖 · 无 24h 窗口)。
im.message.receive_v1 事件 → _run_bg_turn (按 userKey 多会话 · wish-a0e7301c · 复用 proactive 那套 background _chat_impl)
→ 回复用 im/v1/messages 发回飞书。单聊 (p2p) 全回复 · 群聊暂不自动回 (避免机器人到处说话)。
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from identity import localize_narration as _ln

logger = logging.getLogger("opus.feishu")

_THREAD: Optional[threading.Thread] = None
# 消息处理丢线程池 · 不阻塞 Lark SDK 事件循环 (否则心跳 ping 超时断线 · 2026-08-06 线上事故)
_MSG_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="feishu-msg")

# 飞书打断机制 (2026-08-08 · wish 对标 cc-connect /stop)
# user_key → 正在跑的 turn_id · 让 /stop 命令和新消息能定位"这个用户的 turn"并 set cancel。
# 生命周期跟 _begin_turn / _unregister_turn 的 _ACTIVE_TURNS 注册/注销对齐。
_FEISHU_USER_TURNS: dict[str, str] = {}
_FEISHU_TURNS_LOCK = threading.Lock()

_STATE = {
    "started_at": None,
    "last_event_at": None,
    "last_event_ts": 0.0,      # 数值时间戳 · 看门狗判定"卡死"用
    "messages_in": 0,
    "replies_out": 0,
    "last_error": None,
    "ws_connected": False,
    "ws_status": "stopped",    # stopped / connected / disconnected / reviving
    "revive_count": 0,         # 自动复活 (删旧拉新) 次数
}


def get_state() -> dict:
    s = dict(_STATE)
    s["alive"] = is_listener_alive()
    s["configured"] = _client_enabled()
    return s


def _client_enabled() -> bool:
    from workers import feishu_client
    return feishu_client.enabled()


def _begin_turn(user_key: str, sid: str):
    """原子: 打断该 user 旧 turn (若有) + 注册自己的占位。返回 (turn_id, cancel, interrupted)。

    必须原子——否则三消息并发时"打断"和"注册"之间可插队 (A4 · 2026-08-08 三审发现):
    M2 打断 turn1 → M3 插队注册 turn3 → M2 注册 turn2 覆盖 turn3 映射 → turn3 失去映射打不死。
    """
    from daemon_api import _ACTIVE_TURNS, _TURN_TO_SID, _TURNS_LOCK
    turn_id = f"feishu-{uuid.uuid4().hex[:12]}"
    cancel = threading.Event()
    interrupted = False
    with _TURNS_LOCK, _FEISHU_TURNS_LOCK:
        old_tid = _FEISHU_USER_TURNS.get(user_key)
        if old_tid:
            old_cancel = _ACTIVE_TURNS.get(old_tid)
            if old_cancel is not None:
                old_cancel.set()
                interrupted = True
        _ACTIVE_TURNS[turn_id] = cancel
        _TURN_TO_SID[turn_id] = sid
        _FEISHU_USER_TURNS[user_key] = turn_id
    return turn_id, cancel, interrupted


def _unregister_turn(user_key: str, turn_id: str) -> None:
    """清理 turn 占位 (只删自己的映射 · 防误删新 turn)。幂等。"""
    from daemon_api import _ACTIVE_TURNS, _TURN_TO_SID, _TURNS_LOCK
    with _TURNS_LOCK:
        _ACTIVE_TURNS.pop(turn_id, None)
        _TURN_TO_SID.pop(turn_id, None)
    with _FEISHU_TURNS_LOCK:
        if _FEISHU_USER_TURNS.get(user_key) == turn_id:
            _FEISHU_USER_TURNS.pop(user_key, None)


def _run_bg_turn(message: str, user_key: str, chat_id: str = "",
                 turn_id: str = "", cancel: Optional[threading.Event] = None) -> str:
    """跑一次后台 LLM turn。turn_id/cancel 由调用方 _begin_turn 注册后传入。

    cancel 被 set (用户 /stop 或新消息打断) → 立即返回 CANCELED 标记 · 不跑 LLM。
    """
    from daemon_api import _chat_impl
    from workers.feishu_sessions import get_manager

    sid = get_manager().get_or_create(user_key)["sid"]
    try:
        if cancel is not None and cancel.is_set():
            return "\x00__CANCELED__\x00"
        from daemon_runtime import bg_max_tokens
        result = _chat_impl(
            message=message,
            session_id=sid,
            auto_confirm=(os.environ.get("OPUS_FEISHU_AUTO_CONFIRM") or "confirm"),
            max_tokens=bg_max_tokens(),
            attachments=None,
            progress=_make_feishu_progress(chat_id) if chat_id else None,
            cancel_event=cancel,
            turn_id=turn_id,
            user_meta={"src": "feishu"},
        )
        if cancel is not None and cancel.is_set():
            return "\x00__CANCELED__\x00"
        return (result.get("reply") or "").strip()
    finally:
        if turn_id:
            _unregister_turn(user_key, turn_id)


def _make_feishu_progress(chat_id: str):
    """tool_loop 进度事件 → 飞书进度卡片 (块 D · 对标 cc-connect progress card)。

    一张卡片实时更新 · 不刷文本: 每次工具调用追加一行 · 完成时 _finish_progress_card 标 ✅。
    提权事件 (confirm_request / confirm_resolved) → 提权确认卡片 (卷四十六 inline confirm UI 的飞书版)。
    只转 tool_call + 失败的 tool_result · 不转 assistant_text (最终回复会到)。
    任何失败静默 · 进度转发不能影响主链路。
    """
    def _on_progress(kind: str, data: dict) -> None:
        try:
            if kind == "tool_call":
                # cc 风格: 调用行 (蓝色) · 参数格式化
                _update_progress_card(chat_id, {
                    "kind": "call", "name": data.get("name", "?"),
                    "summary": (data.get("summary") or "")[:60],
                    "args": (data.get("args_preview") or "")[:200],
                })
            elif kind == "tool_result":
                # cc 风格: 结果行 (青色) · 🟢/🔴
                _update_progress_card(chat_id, {
                    "kind": "result", "name": data.get("name", "?"),
                    "ok": bool(data.get("ok")), "error": (data.get("error") or "")[:100],
                })
            elif kind == "assistant_text":
                # LLM 中间产出 (思考/回复片段) → 也上卡 · 让飞书用户看到过程 (wish-bcdf5315)
                txt = (data.get("text") or "").strip()
                if txt:
                    _update_progress_card(chat_id, {
                        "kind": "assistant", "text": txt[:220],
                    })
            elif kind == "thinking":
                # 2026-08-14 · 思考过程上卡 (墨言 094 飞书对齐 cc): tool_loop 推 thinking 事件 → 灰字思考面板
                txt = (data.get("text") or "").strip()
                if txt:
                    _update_progress_card(chat_id, {
                        "kind": "thinking", "text": txt[:220],
                    })
            elif kind == "confirm_request":
                _show_confirm_card(chat_id, data)
            elif kind == "confirm_resolved":
                _update_confirm_resolved(chat_id, data)
        except Exception:
            logger.warning("listener 消息解析失败 (L158)", exc_info=True)
    return _on_progress


_PROGRESS_CARDS: dict = {}  # chat_id -> {"message_id", "lines", "lock", "confirming_tool_call_id", "chat_id"}


def _render_tool_line(rec) -> str:
    """工具行渲染 (单行状态流): 每个工具只显示一次 · 进行中 ⏳ · 完成 ✅ · 失败 🔴。"""
    if isinstance(rec, str):  # 兼容旧字符串行
        return rec
    if rec.get("kind") == "assistant":
        return f"<text_tag color='purple'>{_ln('OPUS')}</text_tag> {(rec.get('text') or '')[:200]}"
    if rec.get("kind") == "thinking":
        # 对标 cc-connect renderProgressEntryElement thinking: 💭 + 灰字小字
        return f"<text_tag color='grey'>💭 {(rec.get('text') or '')[:200]}</text_tag>"
    name = rec.get("name", "?")
    status = rec.get("status", "running")
    if status == "done":
        prefix = "✅"
    elif status == "error":
        prefix = "🔴"
    else:
        prefix = "⏳"
    content = f"{prefix} **{name}**"
    args = (rec.get("args") or "").strip()
    if args:
        content += "\n" + (f"```text\n{args[:150]}\n```" if "\n" in args or len(args) > 100 else f"`{args[:150]}`")
    if status == "error" and rec.get("error"):
        content += f"\n🔴 {rec['error'][:100]}"
    return content


def _progress_card_elements(st: dict, title: str, running: bool) -> list:
    """进度卡 elements: 标题 + 思考面板 + 工具面板 (两个独立 collapsible_panel · cc 风格)。

    收缩 = 原生折叠: 处理中 expanded=true (用户实时看) · 完成 expanded=false (默认收起)。
    思考 (assistant_text) 与工具调用 (tool_call/result) 分开显示 · 互不混。
    """
    elems = [{"tag": "div", "text": {"tag": "lark_md", "content": title}}]

    # ① 思考过程面板 (紫色 · AI 的文字产出)
    thoughts = st.get("thoughts", [])[-6:]
    if thoughts:
        elems.append({
            "tag": "collapsible_panel",
            "expanded": running,
            "background_color": "grey",
            "header": {"title": {"tag": "plain_text", "content": f"💭 思考 ({len(thoughts)})"}},
            "border": {"color": "grey"},
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": _render_tool_line(rec)}}
                for rec in thoughts
            ],
        })

    # ② 工具调用面板 (单行状态流 · ever 要求默认收缩)
    tools = st.get("lines", [])[-8:]
    if tools:
        elems.append({
            "tag": "collapsible_panel",
            "expanded": False,  # 默认收缩 · 想看展开点标题 (ever 要求)
            "background_color": "grey",
            "header": {"title": {"tag": "plain_text", "content": f"🛠 工具 ({len(tools)})"}},
            "border": {"color": "grey"},
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": _render_tool_line(rec)}}
                for rec in tools
            ],
        })
    return elems


def _update_progress_card(chat_id: str, line) -> None:
    """进度卡片: 首事件发卡 · 后续事件 update_card 追加行 (工具面板 collapsible_panel)。

    与确认卡共用同一张卡 (wish-a0e7301c 卡片交互): confirming 期间不覆盖确认 UI ·
    新行先缓存进 lines · 确认完成后 _restore_progress_from_confirm 一次性带上。
    行是结构化 dict (kind=call/result · name/args/ok/error) · cc 风格渲染。
    """
    from workers import feishu_client
    st = _PROGRESS_CARDS.setdefault(
        chat_id, {"message_id": "", "lines": [], "thoughts": [], "lock": threading.Lock(),
                  "confirming_tool_call_id": "", "chat_id": chat_id})
    with st["lock"]:
        if line.get("kind") in ("assistant", "thinking"):
            # 思考过程独立存 thoughts · 与工具调用分开 (assistant=正文片段 · thinking=推理内容)
            st.setdefault("thoughts", []).append(line)
            if len(st["thoughts"]) > 6:
                st["thoughts"] = st["thoughts"][-6:]
        elif line.get("kind") == "result":
            # 工具只显示一次 (ever 要求): 把最后一条同名 running 行标记完成 · 不新增行
            updated = False
            for rec in reversed(st["lines"]):
                if rec.get("kind") == "tool" and rec.get("name") == line.get("name") \
                        and rec.get("status") == "running":
                    rec["status"] = "done" if line.get("ok") else "error"
                    if not line.get("ok"):
                        rec["error"] = line.get("error", "")
                    updated = True
                    break
            if not updated:
                # 对应 running 行被挤出上限 → 兜底补一条已完成行
                rec = dict(line)
                rec["kind"] = "tool"
                rec["status"] = "done" if line.get("ok") else "error"
                st["lines"].append(rec)
                if len(st["lines"]) > 8:
                    st["lines"] = st["lines"][-8:]
        else:
            # 工具调用行 (kind=call/tool) · 初始状态 running
            rec = dict(line)
            rec["kind"] = "tool"
            rec.setdefault("status", "running")
            st["lines"].append(rec)
            if len(st["lines"]) > 8:  # 卡片行数上限 · 丢最老的
                st["lines"] = st["lines"][-8:]
        # 正等确认 → 不动卡片 · 行先攒着 (确认完成后统一刷上)
        if st.get("confirming_tool_call_id"):
            return
        card = {
            "config": {"wide_screen_mode": True},
            "elements": _progress_card_elements(st, "**⏳ 处理中**", running=True),
        }
        if not st["message_id"]:
            r = feishu_client.send_card(card, chat_id, "chat_id")
            if r.get("ok") and r.get("message_id"):
                st["message_id"] = r["message_id"]
            logger.info("feishu progress_card: 发卡 line=%s send_ok=%s mid=%s",
                        str(line)[:40], r.get("ok"), r.get("message_id"))
        else:
            r = feishu_client.update_card(st["message_id"], card)
            logger.info("feishu progress_card: 更新 mid=%s line=%s ok=%s",
                        st["message_id"], str(line)[:40], r.get("ok"))


def _finish_progress_card(chat_id: str) -> None:
    """最终回复前调用: 进度卡标题 ⏳ → ✅ · 清理状态。"""
    st = _PROGRESS_CARDS.pop(chat_id, None)
    if not st or not st.get("message_id"):
        return
    # 若还挂着未决确认 (超时 auto-deny 等) · 一并清掉回调索引 · 避免脏残留
    tid = st.get("confirming_tool_call_id") or ""
    if tid:
        _CONFIRM_CARDS.pop(tid, None)
    try:
        from workers import feishu_client
        card = {
            "config": {"wide_screen_mode": True},
            "elements": _progress_card_elements(st, "**✅ 完成**", running=False),
        }
        feishu_client.update_card(st["message_id"], card)
    except Exception:
        logger.warning("listener 事件处理失败 (L308)", exc_info=True)


# ── 提权卡片 (卷四十六 inline confirm UI 的飞书版 · wish-a0e7301c) ──────────

_CONFIRM_CARDS: dict = {}  # tool_call_id -> 卡片 message_id
_CONFIRM_COUNT: dict = {}  # chat_id -> {"count", "last_ts"} · 连续确认护栏
_CONFIRM_COUNT_LOCK = threading.Lock()  # 护栏计数并发保护 (多 turn 并发 confirm 会同时写)
_MAX_CONSECUTIVE_CONFIRMS = 3  # 5 分钟窗口内连续确认上限 · 超了自动拒绝剩余操作


def _auto_deny_confirm(tool_call_id: str, chat_id: str) -> None:
    """护栏触发: 直接拒绝该 tool_call 的确认请求 · 不弹卡 · 提示用户。"""
    try:
        from daemon_api import _PENDING_CONFIRMS, _PENDING_CONFIRMS_LOCK
        with _PENDING_CONFIRMS_LOCK:
            pending = _PENDING_CONFIRMS.get(tool_call_id)
            if pending is None or pending["event"].is_set():
                return
            pending["decision"] = "deny"
            pending["reason"] = "连续确认护栏自动拒绝"
            ev = pending["event"]
        ev.set()
    except Exception:
        return
    try:
        from workers import feishu_client
        feishu_client.send_text(
            f"🛡 连续确认超过 {_MAX_CONSECUTIVE_CONFIRMS} 次 · 剩余操作已自动拒绝。"
            "如果确实要继续，请重新发一条消息。", chat_id, "chat_id")
    except Exception:
        logger.warning("listener 事件分发失败 (L339)", exc_info=True)


def _show_confirm_card(chat_id: str, data: dict) -> None:
    """confirm_request 事件 → 提权确认卡片 (✅ 批准 / ❌ 拒绝)。

    与进度卡共用同一张卡: 优先 update 进度卡 message_id 变成确认形态 ·
    没有进度卡 (首个工具就是 GUARD) 才 send_card 新建。 _CONFIRM_CARDS 仍按
    tool_call_id 索引 · 但 message_id 与进度卡是同一个。

    护栏 (2026-08-06 · 修"连环弹卡"): 同一 chat 5 分钟窗口内连续确认超
    _MAX_CONSECUTIVE_CONFIRMS 次 → 自动拒绝剩余操作 + 提示 · 不再弹卡。
    """
    from workers import feishu_client
    tool_call_id = data.get("tool_call_id") or ""
    if not tool_call_id:
        return
    # 护栏: 连续确认次数 (锁保护 · 多 turn 并发 confirm 时计数不丢)
    now = time.time()
    with _CONFIRM_COUNT_LOCK:
        cnt = _CONFIRM_COUNT.setdefault(chat_id, {"count": 0, "last_ts": 0})
        if now - cnt["last_ts"] > 300:  # 5 分钟窗口
            cnt["count"] = 0
        cnt["count"] += 1
        cnt["last_ts"] = now
        over = cnt["count"] > _MAX_CONSECUTIVE_CONFIRMS
    if over:
        logger.info("feishu confirm 护栏: 连续确认超 %d 次 · 自动拒绝 id=%s",
                    _MAX_CONSECUTIVE_CONFIRMS, tool_call_id)
        _auto_deny_confirm(tool_call_id, chat_id)
        return
    tool_name = data.get("tool_name") or "?"
    tier_reason = data.get("tier_reason") or ""
    risk = (data.get("risk_explanation") or "").strip() or "(OPUS 没说明风险)"
    mitigation = (data.get("mitigation") or "").strip() or "(OPUS 没说明规避)"
    args_preview = (data.get("args_preview") or "")[:200]
    card = {
        "config": {"wide_screen_mode": True},
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md",
             "content": f"**🔐 等你拍板** · `{tool_name}`"}},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**{tier_reason}**"}},
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md",
             "content": f"**调用**\n```\n{args_preview}\n```"}},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"⚠️ 风险：{risk}"}},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"🛡 规避：{mitigation}"}},
            {"tag": "action", "actions": [
                {"tag": "button", "text": {"tag": "plain_text", "content": "✅ 批准"},
                 "type": "primary",
                 "value": {"action": f"act:/confirm {tool_call_id} approve",
                           "chat_id": chat_id, "is_group": "0"}},
                {"tag": "button", "text": {"tag": "plain_text", "content": "❌ 拒绝"},
                 "type": "danger",
                 "value": {"action": f"act:/confirm {tool_call_id} deny",
                           "chat_id": chat_id, "is_group": "0"}},
            ]},
        ],
    }
    # 复用进度卡: 同一张卡原地变成确认形态 (修"两张卡片"观感)
    st = _PROGRESS_CARDS.setdefault(
        chat_id, {"message_id": "", "lines": [], "lock": threading.Lock(), "confirming_tool_call_id": ""})
    with st["lock"]:
        st["confirming_tool_call_id"] = tool_call_id
        if st["message_id"]:
            r = feishu_client.update_card(st["message_id"], card)
            mid = st["message_id"]
            logger.info("feishu confirm_card: tool=%s id=%s reuse_mid=%s ok=%s",
                        tool_name, tool_call_id, mid, r.get("ok"))
        else:
            r = feishu_client.send_card(card, chat_id, "chat_id")
            mid = r.get("message_id") or ""
            if r.get("ok") and mid:
                st["message_id"] = mid
            logger.info("feishu confirm_card: tool=%s id=%s send_ok=%s mid=%s",
                        tool_name, tool_call_id, r.get("ok"), mid)
    if mid:
        _CONFIRM_CARDS[tool_call_id] = mid


def _resolve_confirm(args: str, chat_id: str) -> None:
    """提权卡片按钮 → 写回 daemon _PENDING_CONFIRMS (对标 WebUI POST /turns/{tid}/confirm 的 approve/deny)。"""
    parts = (args or "").split()
    if len(parts) < 2:
        logger.info("feishu confirm resolve: args 解析失败: %r", args)
        return
    tool_call_id, decision = parts[0], parts[1]
    if decision not in ("approve", "deny"):
        logger.info("feishu confirm resolve: decision 非法: %s", decision)
        return
    try:
        from daemon_api import _PENDING_CONFIRMS, _PENDING_CONFIRMS_LOCK
        with _PENDING_CONFIRMS_LOCK:
            pending = _PENDING_CONFIRMS.get(tool_call_id)
            if pending is None or pending["event"].is_set():
                logger.info("feishu confirm resolve: pending 不存在/已处理: %s", tool_call_id)
                # 重复点击已处理的确认 → 明确反馈 (避免"点了没反应"的困惑)
                try:
                    from workers import feishu_client
                    feishu_client.send_text("这个操作你已经处理过了 ✅ 不用再点", chat_id, "chat_id")
                except Exception:
                    logger.warning("listener 回调处理失败 (L440)", exc_info=True)
                return
            pending["decision"] = "approve_once" if decision == "approve" else "deny"
            pending["reason"] = "飞书卡片批准" if decision == "approve" else "飞书卡片拒绝"
            ev = pending["event"]
        ev.set()
    except Exception as e:
        logger.warning("feishu confirm resolve 异常: %s", e)
        return
    # 决议后更新卡片状态 (同一张卡: 确认形态 → 恢复进度形态)
    mid = _CONFIRM_CARDS.pop(tool_call_id, "")
    logger.info("feishu confirm resolve: id=%s decision=%s mid=%s", tool_call_id, decision, mid)
    if mid:
        # 清 confirming 标记 · 把确认期间攒的工具行一起刷回进度卡
        st = _PROGRESS_CARDS.get(chat_id)
        if st and st.get("message_id") == mid:
            with st["lock"]:
                st["confirming_tool_call_id"] = ""
        try:
            from workers import feishu_client
            status = "✅ 已批准，继续处理" if decision == "approve" else "❌ 已拒绝"
            r = feishu_client.update_card(mid, {
                "config": {"wide_screen_mode": True},
                "elements": _progress_card_elements(st if st else {}, f"**{status}**", running=True),
            })
            logger.info("feishu confirm resolve: update_card ok=%s msg=%s", r.get("ok"), r.get("msg"))
        except Exception as e:
            logger.warning("feishu confirm resolve update_card 异常: %s", e)


def _update_confirm_resolved(chat_id: str, data: dict) -> None:
    """confirm_resolved 事件 (超时 auto-deny) → 更新卡片状态。"""
    tool_call_id = data.get("tool_call_id") or ""
    mid = _CONFIRM_CARDS.pop(tool_call_id, "")
    if not mid:
        return
    title = "⏰ 超时未响应 · 已自动拒绝" if data.get("auto_timeout") else "✅ 已处理"
    # 清 confirming 标记 · 把攒的行一起刷回 (超时也保留进度)
    st = _PROGRESS_CARDS.get(chat_id)
    if st and st.get("message_id") == mid:
        with st["lock"]:
            st["confirming_tool_call_id"] = ""
    try:
        from workers import feishu_client
        feishu_client.update_card(mid, {
            "config": {"wide_screen_mode": True},
            "elements": _progress_card_elements(st if st else {}, f"**{title}**", running=True),
        })
    except Exception:
        logger.warning("listener 消息发送失败 (L489)", exc_info=True)


# ── 块 A · 飞书命令系统 (wish-a0e7301c · 对标 cc-connect 命令表精简) ──────

_CMD_ALIASES = {
    "新建": "/new",
    "新会话": "/new",
    "列表": "/list",
    "会话列表": "/list",
    "切换": "/switch",
    "当前": "/current",
    "当前会话": "/current",
    "帮助": "/help",
    "命令": "/help",
    "停止": "/stop",
    "停": "/stop",
    "打断": "/stop",
    "取消": "/stop",
    "别做了": "/stop",
}


def _handle_command(text: str, user_key: str) -> Optional[str]:
    """命中飞书命令返回回复文本 · 否则返回 None (走正常 LLM 链路)。"""
    t = text.strip()
    if t.startswith("/"):
        parts = t.split(maxsplit=1)
        raw = parts[0]
        args = (parts[1] if len(parts) > 1 else "").strip()
        cmd = raw.lower()
    elif t in _CMD_ALIASES:
        cmd = _CMD_ALIASES[t]
        args = ""
        raw = cmd  # 别名分支也定义 raw · 防未来别名指向未知命令时 NameError (C2)
    else:
        return None

    from workers.feishu_sessions import get_manager, real_stats
    mgr = get_manager()

    if cmd == "/help":
        return ("可用命令：\n"
                "/new · 开新会话\n"
                "/list · 列出所有会话\n"
                "/switch <序号|名称> · 切换会话\n"
                "/current · 查看当前会话\n"
                "/stop · 打断当前正在跑的任务\n"
                "/help · 本帮助\n\n"
                "中文别名：新建 / 列表 / 切换 / 当前 / 停止")
    if cmd == "/stop":
        return _stop_turn(user_key)
    if cmd == "/new":
        s = mgr.new_session(user_key)
        return f"✅ 已开新会话 `{s['sid']}`\n直接发消息就是新对话。\n/list 看全部 · /switch 切换。"
    if cmd == "/list":
        sessions = mgr.list_sessions(user_key)
        if not sessions:
            return "还没有会话 · 直接发消息会自动建一个。"
        cur = (mgr.active(user_key) or {}).get("sid")
        lines = []
        for i, s in enumerate(sessions, 1):
            mark = " ← 当前" if s["sid"] == cur else ""
            st = real_stats(s["sid"])
            name = st["label"] or s.get("name") or "默认会话"
            lines.append(f"{i}. `{s['sid']}` · {st['turns']} 轮{mark}{(' · ' + name) if name != '默认会话' else ''}")
        return "📋 会话列表：\n" + "\n".join(lines) + "\n\n/switch <序号> 切换"
    if cmd == "/switch":
        if not args:
            return "/switch 用法：/switch <序号|名称>\n/list 查看全部会话"
        s, err = mgr.switch(user_key, args)
        if err:
            return f"❌ {err}"
        return f"✅ 已切换到 `{s['sid']}`\n后面发的消息都会进这个会话。"
    if cmd == "/current":
        s = mgr.active(user_key) or mgr.get_or_create(user_key)
        st = real_stats(s["sid"])
        name = st["label"] or s.get("name") or "默认会话"
        label = f" · {name}" if name != "默认会话" else ""
        return f"当前会话：`{s['sid']}` · {st['turns']} 轮{label}\n/new 开新的 · /list 看全部"
    return f"未知命令 `{raw}` · 发 /help 看可用命令。"


def _interrupt_user_turn(user_key: str) -> bool:
    """打断该 user 正在跑的 turn (set cancel_event)。返回是否真找到了活跃 turn。"""
    from daemon_api import _ACTIVE_TURNS, _TURNS_LOCK
    with _TURNS_LOCK, _FEISHU_TURNS_LOCK:
        turn_id = _FEISHU_USER_TURNS.get(user_key)
        if not turn_id:
            return False
        cancel = _ACTIVE_TURNS.get(turn_id)
        if cancel is None:
            return False
        cancel.set()
        return True


def _stop_turn(user_key: str) -> str:
    """/stop · 打断当前任务 (对标 cc-connect /stop · 保留会话 · 下条消息继续)。"""
    if _interrupt_user_turn(user_key):
        return "⏹ 已打断当前任务。\n下一条消息我会正常继续（会话没动）。"
    return "当前没有正在跑的任务。\n直接发消息就行。"


# ── 块 C · 飞书卡片交互 (wish-a0e7301c · 对标 cc-connect card nav:/act:) ──────

def _card_button(text: str, value_action: str, chat_id: str, is_group: bool,
                 style: str = "default") -> dict:
    """卡片按钮 · value 里带 chat_id + is_group · 回调时还原会话维度。"""
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": style,
        "value": {"action": value_action, "chat_id": chat_id, "is_group": "1" if is_group else "0"},
    }


def _command_card(cmd: str, args: str, user_key: str, chat_id: str, is_group: bool) -> Optional[dict]:
    """命令 → 卡片 JSON (nav 渲染)。返回 None = 该命令不渲染卡片。"""
    from workers.feishu_sessions import get_manager, real_stats
    mgr = get_manager()

    if cmd == "/list":
        sessions = mgr.list_sessions(user_key)
        cur = (mgr.active(user_key) or {}).get("sid")
        elements = [{"tag": "div", "text": {"tag": "lark_md", "content": "**📋 会话列表**"}}]
        if not sessions:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "还没有会话 · 直接发消息会自动建。"}})
        actions = []
        for i, s in enumerate(sessions, 1):
            mark = " · **← 当前**" if s["sid"] == cur else ""
            st = real_stats(s["sid"])
            name = st["label"] or s.get("name") or "默认会话"
            label = f" · {name}" if name != "默认会话" else ""
            elements.append({"tag": "div", "text": {"tag": "lark_md",
                            "content": f"**{i}.** `{s['sid']}` · {st['turns']} 轮{label}{mark}"}})
            if s["sid"] != cur:
                actions.append(_card_button(f"切到 {i}", f"act:/switch {i}", chat_id, is_group))
        if sessions:
            actions.append(_card_button("➕ 新建", "act:/new", chat_id, is_group, "primary"))
            actions.append(_card_button("🔄", "nav:/list", chat_id, is_group))
        # 飞书 action 按钮每行上限 6 · 超出分多行
        for i in range(0, len(actions), 5):
            elements.append({"tag": "action", "actions": actions[i:i + 5]})
        return {"config": {"wide_screen_mode": True}, "elements": elements}

    if cmd == "/new":
        return {"config": {"wide_screen_mode": True}, "elements": [
            {"tag": "div", "text": {"tag": "lark_md",
             "content": "**➕ 新建会话**\n开新会话后 · 当前对话上下文清零 · 旧会话可 /list 切回。"}},
            {"tag": "action", "actions": [
                _card_button("✅ 确认新建", "act:/new", chat_id, is_group, "primary"),
                _card_button("取消", "nav:/current", chat_id, is_group),
            ]},
        ]}

    if cmd == "/current":
        s = mgr.active(user_key) or mgr.get_or_create(user_key)
        st = real_stats(s["sid"])
        name = st["label"] or s.get("name") or "默认会话"
        label = f" · {name}" if name != "默认会话" else ""
        return {"config": {"wide_screen_mode": True}, "elements": [
            {"tag": "div", "text": {"tag": "lark_md",
             "content": f"**当前会话**\n`{s['sid']}` · {st['turns']} 轮{label}"}},
            {"tag": "action", "actions": [
                _card_button("➕ 新建", "act:/new", chat_id, is_group, "primary"),
                _card_button("📋 列表", "nav:/list", chat_id, is_group),
            ]},
        ]}

    return None


def _command_card_from_text(text: str, user_key: str, chat_id: str, is_group: bool) -> Optional[dict]:
    """文本命令 → 卡片 (纯展示命令才渲染 · /new 走文本直接执行 · 不弹确认)。"""
    t = text.strip()
    if not t.startswith("/"):
        return None
    cmd = t.split(maxsplit=1)[0].lower()
    if cmd in ("/list", "/current"):
        return _command_card(cmd, "", user_key, chat_id, is_group)
    return None


def _execute_card_cmd(cmd: str, args: str, user_key: str) -> None:
    """卡片 act: 前缀按钮的副作用 (对标 cc-connect executeCardAction)。"""
    from workers.feishu_sessions import get_manager
    mgr = get_manager()
    if cmd == "/new":
        mgr.new_session(user_key)
    elif cmd == "/switch":
        mgr.switch(user_key, args)


def _handle_card_action(data) -> Optional[dict]:
    """卡片按钮回调 (card.action.trigger)。value: {"action": "act:/new", "chat_id": ..., "is_group": ...}。

    对齐 cc onCardAction: act:/nav: 返回渲染卡 · 由调用方塞进 CardActionTriggerResponse
    原位更新原卡 (不再 send_card 发新卡刷屏) · /confirm 自己 update_card 返回 None。
    """
    try:
        ev = getattr(data, "event", data)
        action = getattr(ev, "action", None)
        if action is None or getattr(action, "value", None) is None:
            return None
        value = action.value
        raw = str(value.get("action") or "")
        if not raw:
            return None
        logger.info("feishu card action: value=%s", raw)
        chat_id = str(value.get("chat_id") or "") or str(getattr(getattr(ev, "context", None), "open_chat_id", "") or "")
        is_group = str(value.get("is_group") or "") == "1"
        open_id = str(getattr(getattr(ev, "operator", None), "open_id", "") or "")
        if not chat_id:
            return None
        from workers.feishu_sessions import get_manager
        user_key = get_manager().make_key(open_id, chat_id, is_group)

        parts = raw.split(maxsplit=1)
        verb, args = parts[0], (parts[1] if len(parts) > 1 else "").strip()
        if verb.startswith("act:"):
            cmd = verb[4:]
            if cmd.startswith("/confirm"):
                # 提权决议 · 直接写回 _PENDING_CONFIRMS (决议后自己 update_card 恢复进度形态)
                _resolve_confirm(args, chat_id)
                return None
            _execute_card_cmd(cmd, args, user_key)
            # act 执行后渲染结果卡: /new → 当前会话信息 · /switch → 列表 (当前标记变化可见)
            if cmd == "/new":
                nav = "/current"
            elif cmd == "/switch":
                nav = "/list"
            else:
                nav = cmd
        elif verb.startswith("nav:"):
            nav = verb[4:]
        else:
            return None
        return _command_card(nav, args, user_key, chat_id, is_group)
    except Exception as e:
        _STATE["last_error"] = f"{type(e).__name__}: {e}"
        logger.warning("feishu card action 异常: %s", e)
        return None


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
                message_id: str = "", file_key: str = "", file_name: str = "",
                user_id: str = "", image_key: str = "", parent_id: str = "",
                image_pairs: Optional[list] = None) -> None:
    """统一回复链路 (wish-a0e7301c): 命令分流 + 空闲轮换 + 文件/链接/总结 + LLM + 发送。

    image_pairs: 多图合批时传 [(message_id, image_key), ...] · 优先于单值 image_key。
    """
    _STATE["last_event_at"] = time.strftime("%H:%M:%S")
    logger.info("feishu 收到%s: %s (type=%s)", "群消息" if is_group else "p2p", text[:60], msg_type)

    from workers.feishu_sessions import get_manager
    user_key = get_manager().make_key(user_id, chat_id, is_group)
    turn_id, cancel = "", None  # 提前初始化 · 防注册前异常时 finally NameError

    # 命令分流 (块 C + A): 卡片命令优先 · 失败 fallback 文本
    from workers import feishu_client
    card = _command_card_from_text(text, user_key, chat_id, is_group)
    if card is not None:
        r = feishu_client.send_card(card, chat_id, "chat_id")
        if r.get("ok"):
            _STATE["replies_out"] += 1
            return
        logger.info("feishu send_card 失败 · fallback 文本命令: %s", r.get("msg"))
    cmd_reply = _handle_command(text, user_key)
    if cmd_reply is not None:
        feishu_client.send_text(cmd_reply, chat_id, "chat_id")
        _STATE["replies_out"] += 1
        return

    # 发消息强行打断 (2026-08-08): 原子完成"打断旧 turn + 注册自己的占位"。
    # 必须在任何耗时步骤之前 · 让后续消息能打断"准备中"的 turn (问题 9)。
    # _begin_turn 原子性保证三消息并发不互相覆盖映射 (A4)。
    sid = get_manager().get_or_create(user_key)["sid"]
    turn_id, cancel, interrupted = _begin_turn(user_key, sid)
    if interrupted:
        try:
            feishu_client.send_text("⏸ 收到新消息 · 已打断上一个任务，开始处理这条。", chat_id, "chat_id")
        except Exception as e:
            logger.warning("feishu 打断提示发送异常: %s", e)

    # 空闲自动轮换 + touch (辅助逻辑 · 失败不中断主流程 · 否则 turn 泄漏 C8)
    try:
        rotated = get_manager().maybe_rotate_idle(user_key)
        if rotated:
            feishu_client.send_text(
                f"⏳ 上个会话空闲超时 · 已自动开新会话 `{rotated['sid']}`", chat_id, "chat_id")
        get_manager().touch(user_key)
    except Exception as e:
        logger.warning("feishu 轮换/touch 异常: %s", e)

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

    # ⓪.5 图片消息 → 下载 → look_at 识图 (发图给 AI 看场景 · 支持多图合批)
    if image_pairs:
        pairs = image_pairs
    elif isinstance(image_key, list):
        # 防御: list 元素是 (mid, key) tuple 或裸 key 字符串
        pairs = [(m, k) for m, k in image_key if isinstance(k, tuple)]
        if not pairs:
            pairs = [(message_id, k) for k in image_key if isinstance(k, str)]
    elif image_key:
        pairs = [(message_id, image_key)]
    else:
        pairs = []
    if msg_type == "image" and pairs:
        try:
            from workers.feishu_docs import fetch_image
            from agent_tools.look_at import _run as _look_at_run
            parts = []
            for mid, ikey in pairs:
                ir = fetch_image(mid, ikey)
                if ir.get("ok"):
                    vr = _look_at_run({"path": ir["path"], "question": "这张图里有什么？请详细描述"})
                    if vr.ok:
                        parts.append(str(vr.output))
                    else:
                        parts.append(f"[图片识别失败: {vr.error}]")
                else:
                    parts.append(f"[图片下载失败: {ir.get('error', '')}]")
            if not parts:
                text = "[图片处理无结果]"
            elif len(parts) == 1:
                extra = f"\n\n[飞书图片 · {_ln('OPUS')}看到的]\n{parts[0]}"
            else:
                extra = "\n\n[飞书图片 · " + _ln("OPUS") + "看到的]\n" + "\n\n".join(
                    f"--- 图{i + 1} ---\n{p}" for i, p in enumerate(parts))
        except Exception as e:
            logger.warning("feishu 图片处理异常: %s", e)
            text = f"[图片处理异常: {type(e).__name__}]"

    # ⓪.7 引用回复链 (块2 · 对标 cc fetchQuotedMessage): 用户引用回复 → 取回被引用的消息链上下文
    if parent_id:
        if _is_message_recalled(parent_id):
            text = f"（你引用的消息已被撤回）{text}"
        else:
            try:
                chain = _fetch_reply_chain(parent_id, _MAX_REPLY_CHAIN_DEPTH)
                if chain:
                    extra += "\n\n[引用消息链]\n" + _format_reply_chain(chain)
            except Exception as e:
                logger.warning("feishu 引用链取回异常: %s", e)

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
        try:
            group_msgs = _fetch_group_messages(chat_id, 30)
            if group_msgs:
                extra += f"\n\n[群聊最近消息·供总结]\n{group_msgs}"
                text = f"请总结这个飞书群的近期消息，要点式列出：\n{text}"
        except Exception as e:
            logger.warning("feishu 群总结拉取异常: %s", e)

    # 块 D · 处理中指示 + LLM + ✅ reaction (对标 cc-connect: 飞书无 typing API · 用 emoji reaction 代替)
    try:
        # 处理中指示: 给用户消息加 👀 (cc 默认 OnIt) · 完成时移除 + 加 ✅
        _typing_reaction_id = ""
        if message_id:
            _typing_r = feishu_client.send_reaction(message_id, "OnIt")
            _typing_reaction_id = _typing_r.get("reaction_id") or ""
        reply = _run_bg_turn(text + extra, user_key, chat_id, turn_id=turn_id, cancel=cancel)
        # 被打断的 turn: 不补发旧回复 (用户已经收到"已打断"提示·新消息在跑了)
        if reply == "\x00__CANCELED__\x00":
            _finish_progress_card(chat_id)
            # 清理"处理中"reaction (B7 · 否则 👀 永远挂消息上)
            if message_id and _typing_reaction_id:
                try:
                    feishu_client.remove_reaction(message_id, _typing_reaction_id)
                except Exception as e:
                    logger.warning("feishu CANCELED 清理 reaction 异常: %s", e)
            return
        # 进度卡片 ⏳ → ✅ (若有)
        _finish_progress_card(chat_id)
        r = _send_reply(reply or "(抱歉·我这边没生成出回复)", chat_id)
        if r.get("ok"):
            _STATE["replies_out"] += 1
            if message_id:
                # 移除处理中 reaction · 加完成 ✅
                if _typing_reaction_id:
                    feishu_client.remove_reaction(message_id, _typing_reaction_id)
                feishu_client.send_reaction(message_id, "OK")
    finally:
        # turn 完成/异常 · 重置连续确认护栏 + 兜底清进度卡 (防残留) + 清 turn 占位
        _CONFIRM_COUNT.pop(chat_id, None)
        _PROGRESS_CARDS.pop(chat_id, None)
        _unregister_turn(user_key, turn_id)


def _is_summary_request(text: str) -> bool:
    return any(k in text for k in ("总结", "汇总", "回顾", "摘要"))


# ── 块2 · 消息撤回检测 (对标 cc-connect onMessageRecalled / markMessageRecalled / isMessageRecalled) ──

_RECALL_TTL = 600  # 撤回登记保留 10 分钟 (对标 cc recalledMessageTTL)
_RECALLED_MSG_IDS: dict = {}  # message_id -> 撤回时间戳


def _mark_message_recalled(message_id: str) -> None:
    """登记一条被撤回的消息 (撤回事件回调 · 环形清理超 TTL 的旧记录)。"""
    message_id = (message_id or "").strip()
    if not message_id:
        return
    now = time.time()
    stale = [k for k, v in _RECALLED_MSG_IDS.items() if now - v > _RECALL_TTL]
    for k in stale:
        _RECALLED_MSG_IDS.pop(k, None)
    _RECALLED_MSG_IDS[message_id] = now


def _is_message_recalled(message_id: str) -> bool:
    """这条消息是否已被撤回 (TTL 过期自动清除并返回 False)。"""
    message_id = (message_id or "").strip()
    if not message_id:
        return False
    marked_at = _RECALLED_MSG_IDS.get(message_id)
    if marked_at is None:
        return False
    if time.time() - marked_at > _RECALL_TTL:
        _RECALLED_MSG_IDS.pop(message_id, None)
        return False
    return True


# ── 块2 · 引用回复链 (对标 cc-connect fetchReplyChain / fetchQuotedMessage / formatReplyChain) ──

_MAX_REPLY_CHAIN_DEPTH = 5  # 引用链最多取 5 层 (对标 cc maxReplyChainDepth)


def _fetch_single_message(message_id: str) -> Optional[dict]:
    """按 id 拉单条消息 (GET /im/v1/messages/{id}?card_msg_content_type=raw_card_content)。

    返回 dict: {sender_name, sender_type, text, parent_id} · 任何失败返回 None (优雅降级)。
    对标 cc fetchSingleMessage: text/post/image/interactive 各类型提取 + sender 名解析。
    """
    try:
        from workers import feishu_client
        gr = feishu_client.get_message(message_id)  # 走重试层 (块1: token 刷新 + 瞬时重试)
        if not gr.get("ok") or not gr.get("item"):
            return None
        item = gr["item"]
        body = item.get("body") or {}
        content = body.get("content") or ""
        if not content:
            return None
        msg_type = item.get("msg_type", "text")
        # 各类型提取文本 (对标 cc fetchSingleMessage switch)
        if msg_type == "text":
            try:
                text = (json.loads(content).get("text") or "").strip()
            except Exception:
                text = content.strip()
        elif msg_type == "post":
            text = _text_of_message(content)  # content 就是 {"post": {...}} JSON 字符串
            if not text:
                text = "[富文本消息]"
        elif msg_type == "image":
            text = "[图片]"
        elif msg_type == "interactive":
            text = _extract_card_plain_text(content)
            if not text:
                text = "[卡片消息]"
        else:
            text = f"[{msg_type}]"
        if not text:
            return None
        # sender 名 (对标 cc resolveUserName / resolveBotSenderName 的简化版)
        sender = item.get("sender") or {}
        sender_type = sender.get("sender_type", "user")
        sender_id = sender.get("id", "") or ""
        if sender_type == "app":
            sender_name = f"{_ln('OPUS')}(机器人)" if "cli_" in sender_id else f"机器人[{sender_id[:20]}]"
        elif sender_id:
            # 2026-08-14 · 名字解析 (墨言 094 飞书对齐 cc): open_id → 真名 (Contact API + 缓存) ·
            # 失败降级 open_id 截断 (cc 同构) · 需 contact:user.base:readonly 权限 (未开通自动降级)
            try:
                from workers.feishu_client import resolve_user_name as _run
                sender_name = _run(sender_id)
                if not sender_name or sender_name == sender_id:
                    sender_name = sender_id if len(sender_id) <= 12 else f"{sender_id[:6]}…{sender_id[-4:]}"
            except Exception:
                sender_name = sender_id if len(sender_id) <= 12 else f"{sender_id[:6]}…{sender_id[-4:]}"
        else:
            sender_name = "用户"
        return {
            "sender_name": sender_name, "sender_type": sender_type,
            "text": text, "parent_id": item.get("parent_id") or "",
        }
    except Exception as e:
        logger.debug("feishu fetch_single_message 异常: %s", e)
        return None


def _fetch_reply_chain(parent_id: str, max_depth: int = _MAX_REPLY_CHAIN_DEPTH) -> list:
    """沿 parent_id 迭代取回复链 · 防循环 · 最多 max_depth 层 · 返回时间正序 (对标 cc fetchReplyChain)。"""
    chain = []
    visited = set()
    current_id = (parent_id or "").strip()
    while current_id and len(chain) < max_depth:
        if current_id in visited:
            break  # 循环引用
        visited.add(current_id)
        msg = _fetch_single_message(current_id)
        if msg is None:
            break
        chain.append(msg)
        current_id = msg.get("parent_id") or ""
    chain.reverse()  # 时间正序 (最旧在前 · 对标 cc)
    return chain


def _format_reply_chain(chain: list) -> str:
    """格式化回复链 (对标 cc formatReplyChain: 单条兼容格式 / 多条编号格式)。"""
    if not chain:
        return ""
    if len(chain) == 1:
        return f"[引用消息 from {chain[0]['sender_name']}]:\n{chain[0]['text']}\n\n"
    lines = [f"--- 引用消息链 ({len(chain)} 条) ---"]
    for i, msg in enumerate(chain, 1):
        role = "assistant" if msg.get("sender_type") == "app" else "user"
        lines.append(f"[{i}] {msg['sender_name']} ({role}):\n{msg['text']}")
    lines.append("---")
    return "\n\n".join(lines) + "\n\n"


def _extract_card_plain_text(content: str) -> str:
    """interactive 卡片 JSON → 纯文本 (收集 lark_md / plain_text 内容 · 简化版对标 cc extractInteractiveCardText)。"""
    try:
        d = json.loads(content)
    except Exception:
        return ""
    out = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("tag") in ("lark_md", "plain_text", "text"):
                t = node.get("text") or node.get("content") or ""
                if isinstance(t, dict):
                    t = t.get("content") or ""
                if isinstance(t, str) and t.strip():
                    out.append(t.strip())
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(d)
    return " ".join(out)[:500]


# ── 块3 · 富文本智能发送 (对标 cc-connect buildReplyContent / containsMarkdown / countMarkdownTables / buildPostMdJSON / preprocessFeishuMarkdown / sanitizeMarkdownURLs) ──

_MD_INDICATORS = ("```", "**", "~~", "`", "\n- ", "\n* ", "\n1. ", "\n# ", "---")
_MAX_CARD_TABLES = 5  # 卡片最多 5 张表格 · 超了飞书 API 报 11310 (对标 cc maxCardTables)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def _contains_markdown(s: str) -> bool:
    """有没有 markdown 指示符 (对标 cc containsMarkdown + hasComplexMarkdown 的表格检测)。"""
    if any(ind in s for ind in _MD_INDICATORS):
        return True
    # 表格行 (以 | 开头结尾) 也算 markdown · 否则纯表格会被发成 text 一坨
    for line in s.split("\n"):
        t = line.strip()
        if len(t) > 1 and t[0] == "|" and t[-1] == "|":
            return True
    return False


def _count_markdown_tables(s: str) -> int:
    """统计 markdown 表格数量: 连续以 | 开头结尾的行算一个表格 (对标 cc countMarkdownTables)。"""
    count = 0
    in_table = False
    for line in s.split("\n"):
        t = line.strip()
        is_table = len(t) > 1 and t[0] == "|" and t[-1] == "|"
        if is_table and not in_table:
            count += 1
            in_table = True
        elif not is_table:
            in_table = False
    return count


def _sanitize_markdown_urls(md: str) -> str:
    """非 http(s) 链接 → 纯文本 (飞书对非法 href 报 230001 · 对标 cc sanitizeMarkdownURLs)。"""
    def _repl(m):
        url = m.group(2)
        if url.startswith("http://") or url.startswith("https://"):
            return m.group(0)
        return m.group(1) or url
    return _MD_LINK_RE.sub(_repl, md)


def _preprocess_feishu_markdown(md: str) -> str:
    """代码围栏 (```) 前补换行 · 防卡片渲染错位 (对标 cc preprocessFeishuMarkdown)。"""
    if "```" not in md:
        return md
    return re.sub(r"(?<!\n)```", "\n```", md)


def _build_card_json(content: str) -> dict:
    """markdown 文本 → 飞书 v2 卡片 JSON (对标 cc buildCardJSON 简化版: 单 markdown div)。"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": _ln("OPUS")}, "template": "blue"},
        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": content}}],
    }


def _build_reply_content(text: str):
    """智能选择回复消息类型 (对标 cc buildReplyContent)。

    - 含 mention (card/post 不触发 mention 通知) → 强制 text
    - 无 markdown → text
    - markdown 表格 >5 (飞书卡片上限) → post (md tag)
    - 否则 → interactive 卡片 (markdown 渲染效果最好)
    返回 (msg_type, payload): text→字符串 / post→字符串 / interactive→卡片 dict。
    """
    text = (text or "").strip()
    if not text:
        return "text", ""
    has_mention = "<at user_id=" in text or "<at id=" in text
    if not _contains_markdown(text) or has_mention:
        return "text", text
    if _count_markdown_tables(text) > _MAX_CARD_TABLES:
        return "post", text
    cleaned = _sanitize_markdown_urls(_preprocess_feishu_markdown(text))
    return "interactive", _build_card_json(cleaned)


def _send_reply(text: str, chat_id: str) -> dict:
    """最终回复智能发送 (对标 cc Reply): 卡片 → post → text 逐级降级 · 失败不丢回复。"""
    from workers import feishu_client as _fc
    msg_type, payload = _build_reply_content(text)
    try:
        if msg_type == "interactive":
            r = _fc.send_card(payload, chat_id, "chat_id")
            if r.get("ok"):
                return r
            logger.info("feishu 卡片发送失败 · 降级 text: %s", r.get("msg"))
            return _fc.send_text(text, chat_id, "chat_id")
        if msg_type == "post":
            r = _fc.send_post(payload, chat_id, "chat_id")
            if r.get("ok"):
                return r
            return _fc.send_text(text, chat_id, "chat_id")
        return _fc.send_text(payload, chat_id, "chat_id")
    except Exception as e:
        logger.warning("feishu _send_reply 异常: %s", e)
        return _fc.send_text(text, chat_id, "chat_id")


# ── 块3 · 图片合批 (对标 cc-connect bufferImage / flushImageBatchByRef / dispatchImageBatchEntry) ──

_IMAGE_BATCH_WINDOW = 0.5  # 秒 · 连续多图合批窗口 (对标 cc defaultImageBatchWindow 500ms)
_IMAGE_BATCHES: dict = {}  # key(chat:user) -> entry
_IMAGE_LOCK = threading.Lock()  # buffer/flush 跨线程竞态防护 (对标 cc imageBatchMu)


def _buffer_image(chat_id: str, is_group: bool, user_id: str, parent_id: str,
                  message_id: str, image_key: str) -> None:
    """图片进合批缓冲: 同会话 (chat+user+parent) 500ms 窗口内多图合并 · 上下文不匹配先 flush 旧的。

    对标 cc bufferImage: 窗口内新图重置定时器 · parent/user 变化 → 立即 dispatch 旧批。
    """
    key = f"{chat_id}:{user_id}"
    to_dispatch = None
    with _IMAGE_LOCK:
        existing = _IMAGE_BATCHES.get(key)
        if existing and (existing.get("parent_id") != parent_id or existing.get("user_id") != user_id):
            to_dispatch = _flush_image_batch_locked(key)  # 上下文不匹配 → 旧批先走
            existing = None
        if existing:
            existing["timer"].cancel()
            existing["images"].append((message_id, image_key))
        else:
            entry = {
                "chat_id": chat_id, "is_group": is_group, "user_id": user_id,
                "parent_id": parent_id, "images": [(message_id, image_key)],
            }
            _IMAGE_BATCHES[key] = entry
            timer = threading.Timer(_IMAGE_BATCH_WINDOW, _flush_image_batch, args=[key])
            timer.daemon = True
            entry["timer"] = timer
            timer.start()
    if to_dispatch:
        _dispatch_image_batch(to_dispatch)


def _flush_image_batch_locked(key: str):
    """锁内: 取走缓冲 entry + 停定时器 · 返回 entry (锁外 dispatch)。"""
    entry = _IMAGE_BATCHES.pop(key, None)
    if entry and entry.get("timer"):
        try:
            entry["timer"].cancel()
        except Exception:
            logger.warning("listener 提权卡处理失败 (L1231)", exc_info=True)
    return entry


def _flush_image_batch(key: str) -> None:
    """窗口到 (Timer 回调) → 把缓冲里的图片合并成一次 _reply_with (多图一次识图 + 一次 LLM)。"""
    with _IMAGE_LOCK:
        entry = _flush_image_batch_locked(key)
    if entry:
        _dispatch_image_batch(entry)


def _dispatch_image_batch(entry: dict) -> None:
    """真正 dispatch 一批图片 (锁外调用 · 对标 cc dispatchImageBatchEntry)。"""
    # 过滤被撤回的图片消息 (块2 撤回登记 · 对标 cc)
    images = [(mid, k) for mid, k in entry["images"] if not _is_message_recalled(mid)]
    if not images:
        return
    last_mid = images[-1][0]
    if len(images) == 1:
        text = "[收到一张图片 · 请看看这张图]"
    else:
        text = f"[收到 {len(images)} 张图片 · 请一起看看]"
    # image_pairs = [(mid, key), ...] · 每张图自己的 message_id 用于下载 (对标 cc dispatchImageBatchEntry)
    _MSG_EXECUTOR.submit(_reply_with, text, entry["chat_id"], "image", entry["is_group"],
                         last_mid, "", "", entry["user_id"], "", entry["parent_id"], images)


# ── 块3 · 合并转发展开 (对标 cc-connect parseMergeForward / formatMergeForwardTree) ──

_MAX_MERGE_FORWARD_DEPTH = 10  # 嵌套转发最多 10 层 (对标 cc)


def _expand_merge_forward(root_message_id: str) -> str:
    """拉合并转发全部子消息 → 按 upper_message_id 建树 → 递归格式化。

    返回 `<forwarded_messages>` 文本 · 任何失败返回空串 (调用方降级为提示)。
    图片/文件只标注不下载 (与引用链同策略 · 保持轻量)。
    """
    try:
        from workers import feishu_client
        gr = feishu_client.get_message_items(root_message_id)
        if not gr.get("ok"):
            logger.debug("feishu merge_forward 拉取失败: %s", gr.get("msg", gr.get("error", "")))
            return ""
        items = gr.get("items") or []
        if not items:
            return ""
        children_map: dict = {}
        for it in items:
            mid = it.get("message_id") or ""
            if not mid or mid == root_message_id:
                continue  # 跳过 root 容器 (对标 cc)
            parent = it.get("upper_message_id") or root_message_id
            children_map.setdefault(parent, []).append(it)
        if not children_map:
            return ""
        sb: list = []
        _format_merge_forward_tree(root_message_id, children_map, sb, 0)
        if not sb:
            return ""
        return "<forwarded_messages>\n" + "\n".join(sb) + "\n</forwarded_messages>"
    except Exception as e:
        logger.warning("feishu merge_forward 展开异常: %s", e)
        return ""


def _format_merge_forward_tree(parent_id: str, children_map: dict, sb: list, depth: int) -> None:
    """递归格式化合并转发树 (对标 cc formatMergeForwardTree)。"""
    if depth > _MAX_MERGE_FORWARD_DEPTH:
        sb.append("    " * depth + "[嵌套转发已截断]")
        return
    for it in children_map.get(parent_id, []):
        mid = it.get("message_id") or ""
        msg_type = it.get("msg_type") or "text"
        indent = "    " * depth
        # 发送者 (简化: id 截断 · 对标 cc resolveUserName 降级)
        sender = it.get("sender") or {}
        sender_id = sender.get("id") or ""
        if sender.get("sender_type") == "app":
            sender_name = "机器人"
        elif sender_id:
            # 2026-08-14 · 名字解析 (墨言 094 飞书对齐 cc): open_id → 真名 (Contact API + 缓存) ·
            # 失败降级 open_id 截断 (cc 同构) · 需 contact:user.base:readonly 权限 (未开通自动降级)
            try:
                from workers.feishu_client import resolve_user_name as _run
                sender_name = _run(sender_id)
                if not sender_name or sender_name == sender_id:
                    sender_name = sender_id if len(sender_id) <= 12 else f"{sender_id[:6]}…{sender_id[-4:]}"
            except Exception:
                sender_name = sender_id if len(sender_id) <= 12 else f"{sender_id[:6]}…{sender_id[-4:]}"
        else:
            sender_name = "用户"
        # 时间戳 HH:MM
        ts = ""
        ct = it.get("create_time") or ""
        try:
            if ct:
                ts = time.strftime("%H:%M", time.localtime(int(ct) / 1000))
                ts = f"[{ts}] "
        except Exception:
            logger.warning("listener 合并转发失败 (L1324)", exc_info=True)
        body = it.get("body") or {}
        content = body.get("content") or ""
        prefix = f"{indent}{ts}{sender_name}: "
        if msg_type == "text":
            try:
                txt = (json.loads(content).get("text") or "").strip()
            except Exception:
                txt = content.strip()
            if txt:
                sb.append(prefix + txt.replace("\n", "\n" + indent + "    "))
        elif msg_type == "post":
            txt = _text_of_message(content)
            if txt:
                sb.append(prefix + txt.replace("\n", "\n" + indent + "    "))
        elif msg_type == "image":
            sb.append(prefix + "[图片]")
        elif msg_type == "file":
            try:
                fname = (json.loads(content).get("file_name") or "文件")
            except Exception:
                fname = "文件"
            sb.append(prefix + f"[文件: {fname}]")
        elif msg_type == "merge_forward":
            sb.append(prefix + "[转发消息]")
            _format_merge_forward_tree(mid, children_map, sb, depth + 1)
        else:
            sb.append(prefix + f"[{msg_type} 消息]")


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
        # 引用回复 (块2 · 对标 cc fetchReplyChain): 用户回复的那条消息 id
        parent_id = getattr(msg, "parent_id", "") or ""
        # sender open_id → userKey 用 (p2p 会话维度)
        user_id = ""
        try:
            sender = getattr(inner, "sender", None)
            sid_obj = getattr(sender, "sender_id", None) if sender is not None else None
            if sid_obj is not None:
                user_id = getattr(sid_obj, "open_id", "") or ""
        except Exception:
            logger.warning("listener 文件处理失败 (L1404)", exc_info=True)
        text = _text_of_message(content)
        # file/image 消息: 解析 key (下载读取用)
        file_key, file_name = "", ""
        image_key = ""
        try:
            fcnt = json.loads(content)
            if msg_type == "file":
                file_key = fcnt.get("file_key", "") or fcnt.get("file_token", "")
                file_name = fcnt.get("file_name", "")
            elif msg_type == "image":
                image_key = fcnt.get("image_key", "") or fcnt.get("file_key", "")
                file_name = "飞书图片"
        except Exception:
            logger.warning("listener 文件指针复位失败 (L1418)", exc_info=True)
        if msg_type == "merge_forward":
            # 合并转发 (块3 · 对标 cc parseMergeForward): 拉子消息展开成文本给 LLM
            root_id = ""
            try:
                root_id = (json.loads(content) or {}).get("root_message_id", "")
            except Exception:
                logger.warning("listener 文件读取失败 (L1425)", exc_info=True)
            if root_id:
                text = "[收到合并转发 · 正在展开内容…]"
                expanded = _expand_merge_forward(root_id)
                if expanded:
                    text += "\n\n" + expanded
                else:
                    text = "[收到合并转发 · 展开失败，请手动转发关键内容]"
            else:
                text = "[收到合并转发 · 无法解析 root_message_id]"
        if not text and msg_type != "file":
            # 非文字消息: 图片 → 走识图链路 · 其他 → 不沉默回提示
            if msg_type == "image":
                text = "[收到一张图片 · 请看看这张图]"
            else:
                text = f"[收到一条 {msg_type} 消息 · 我暂时只处理文字/图片/文档和表格链接]"
        if not text and msg_type == "file":
            text = f"[收到文件 {file_name}]"
        if not chat_id:
            return

        if chat_type == "p2p":
            _STATE["messages_in"] += 1
            if msg_type == "image" and image_key:
                _buffer_image(chat_id, False, user_id, parent_id, message_id, image_key)
                return
            _MSG_EXECUTOR.submit(_reply_with, text, chat_id, msg_type, False,
                                 message_id, file_key, file_name, user_id, image_key, parent_id)
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
            if msg_type == "image" and image_key:
                _buffer_image(chat_id, True, user_id, parent_id, message_id, image_key)
                return
            _MSG_EXECUTOR.submit(_reply_with, text, chat_id, msg_type, True,
                                 message_id, file_key, file_name, user_id, image_key, parent_id)
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
    """构建 lark-oapi 事件分发器 · 注册 im.message.receive_v1 + card.action.trigger。"""
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import (
            P2ImMessageReceiveV1Data, P2ImMessageReactionCreatedV1Data, P2ImMessageReactionDeletedV1Data,
        )
        from lark_oapi.api.im.v1.model import P2ImMessageRecalledV1Data
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTrigger, P2CardActionTriggerResponse,
        )

        def do_p2_im_message_receive_v1(data: P2ImMessageReceiveV1Data) -> None:
            _STATE["ws_connected"] = True
            _STATE["last_event_ts"] = time.time()  # 看门狗: 有事件 = 连接活着
            _handle_message(data)

        def do_p2_im_message_reaction_created_v1(data: P2ImMessageReactionCreatedV1Data) -> None:
            _STATE["last_event_ts"] = time.time()  # reaction 也刷 · 证明 ws 活着
            return None  # 忽略 reaction 事件 (我们自己的 ✅ 触发 · 消日志噪音)

        def do_p2_im_message_reaction_deleted_v1(data: P2ImMessageReactionDeletedV1Data) -> None:
            _STATE["last_event_ts"] = time.time()  # reaction.deleted 同样刷看门狗 · 证明 ws 活着
            return None  # 忽略 · 无 processor 时 SDK 会刷 ERROR (fix-log 20260814-1 ④)

        def do_p2_im_message_recalled_v1(data: P2ImMessageRecalledV1Data) -> None:
            _STATE["last_event_ts"] = time.time()
            _mark_message_recalled(getattr(data, "message_id", "") or "")
            return None  # 撤回只登记 · 等引用检测用

        def do_p2_card_action_trigger(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
            _STATE["last_event_ts"] = time.time()  # 看门狗: 卡片点击也算活
            # 对齐 cc onCardAction: 返回 Card 原位更新原卡 (点按钮不刷屏 · 同步返回比 send_card 快)
            card = _handle_card_action(data)
            if card:
                return P2CardActionTriggerResponse({"card": {"type": "raw", "data": card}})
            return P2CardActionTriggerResponse({})

        return (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1)
            .register_p2_im_message_reaction_created_v1(do_p2_im_message_reaction_created_v1)
            .register_p2_im_message_reaction_deleted_v1(do_p2_im_message_reaction_deleted_v1)
            .register_p2_im_message_recalled_v1(do_p2_im_message_recalled_v1)
            .register_p2_card_action_trigger(do_p2_card_action_trigger)
            .build()
        )
    except Exception as e:
        logger.error("feishu event handler 构建失败: %s", e)
        return None


def _run_ws_loop() -> None:
    """飞书 WS 长连接 · 自动复活机制 (删旧拉新)。

    循环语义:
      1. 每次循环 = 拉一个**全新** ws.Client (旧 client 已在上一轮 teardown)
      2. client.start() 阻塞 · SDK 内部自动重连
      3. start() 返回 (= 连接生命周期结束: SDK 放弃 / 异常 / 看门狗强制断开)
         → 删旧 (teardown 旧 client) → 回到 1 拉新 (revive_count + 1)
      4. 启动即异常 → 指数退避后删旧拉新
      5. 看门狗线程: 30min 无任何业务事件 → 判定卡死 → 强制断开 → 触发删旧拉新
         (阈值远大于"用户静默"时长 · 防误杀 · SDK 自身 ping_timeout 已处理断线)

    退出条件: 只有 feishu 未启用 (用户停用) 才 return · 否则永不退出。
    """
    attempt = 0
    while True:
        client = None  # 循环级 · 异常路径也要能 teardown
        try:
            import lark_oapi as lark
            from workers import feishu_client
            if not feishu_client.enabled():
                logger.info("feishu 未启用 · ws 不启动")
                _STATE["ws_status"] = "stopped"
                return
            handler = _event_handler_builder()
            if handler is None:
                logger.error("feishu event handler 构建失败 (lark 库缺失/版本问题?) · 10s 后重试")
                time.sleep(10)
                attempt += 1
                continue
            cfg = feishu_client.load_config()
            # ── 拉新: 每次循环重建 client ──
            client = lark.ws.Client(
                cfg["app_id"], cfg["app_secret"],
                event_handler=handler,
                log_level=lark.LogLevel.INFO,
            )
            _STATE["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _STATE["last_event_ts"] = time.time()
            _STATE["ws_status"] = "connected"
            _STATE["last_error"] = ""
            logger.info("feishu ws 长连接启动 (attempt=%d)", attempt + 1)
            attempt = 0  # 成功启动后重置退避
            # 看门狗: 卡死检测 (30min 无事件 → 强制断旧 → 外层删旧拉新)
            wd_stop = threading.Event()
            threading.Thread(
                target=_ws_watchdog, args=(client, wd_stop),
                name="feishu-watchdog", daemon=True,
            ).start()
            try:
                client.start()  # 阻塞 · SDK 内部自动重连
            finally:
                wd_stop.set()
            # start() 返回 = 连接生命周期结束 → 删旧拉新
            _STATE["revive_count"] += 1
            _STATE["ws_connected"] = False
            _STATE["ws_status"] = "reviving"
            logger.warning("feishu ws 连接结束 · 删旧拉新 (第 %d 次复活)", _STATE["revive_count"])
            _teardown_client(client)
            time.sleep(2)  # 防秒退循环 (启动即失败时不空转 CPU)
        except Exception as e:
            _STATE["last_error"] = f"{type(e).__name__}: {e}"
            _STATE["ws_connected"] = False
            _STATE["ws_status"] = "disconnected"
            if client is not None:
                _teardown_client(client)  # start() 抛异常也要删旧 · 防 SDK 资源累积
            attempt += 1
            delay = min(60, 5 * attempt)  # 5s,10s,... 上限 60s
            logger.warning("feishu ws 异常: %s · %ds 后删旧拉新", e, delay)
            time.sleep(delay)


def _teardown_client(client) -> None:
    """删旧: 关闭旧 ws.Client · 释放连接 (尽力而为 · 不抛)。"""
    try:
        if client is not None:
            client.close()
    except Exception:
        logger.warning("listener 群消息处理失败 (L1685)", exc_info=True)


def _ws_watchdog(client, stop_ev: threading.Event) -> None:
    """看门狗: 每 30s 检查 · ①停用即断 ②卡死检测 (30min 无业务事件才判 · 防静默误杀)。"""
    while not stop_ev.is_set():
        if stop_ev.wait(30):
            return
        from workers import feishu_client
        # ① 停用即断: set_enabled(False) → 断开旧连接 → 外层循环开头发现未启用 → 退出
        if not feishu_client.enabled():
            logger.info("feishu 已停用 · 看门狗断开旧连接")
            _STATE["ws_status"] = "stopped"
            try:
                client.close()
            except Exception:
                logger.warning("listener 会话清理失败 (L1701)", exc_info=True)
            return
        # ② 卡死检测: 30min 无任何业务事件才怀疑卡死 (SDK 自身 ping_timeout 已处理断线 ·
        #    阈值必须远大于"用户静默"时长 · 防深夜/思考间隙误杀)
        last = _STATE.get("last_event_ts", 0.0)
        idle = time.time() - last
        if idle > 1800:
            logger.warning("feishu ws 看门狗: %ds 无事件 · 判定卡死 · 强制删旧拉新", int(idle))
            _STATE["ws_status"] = "reviving"
            try:
                client.close()  # 断开 → start() 返回 → _run_ws_loop 删旧拉新
            except Exception:
                logger.warning("listener 消息撤回失败 (L1713)", exc_info=True)
            return


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
