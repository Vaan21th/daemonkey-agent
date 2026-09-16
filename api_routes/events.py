"""
api_routes/events.py · 会话常驻事件流（SSE 广播）· wish-8a9a3482
=================================================================

给「后台 turn 产出即时上屏」提供通道：

  GET /api/events?session_id=<sid>   · 常驻 SSE · 页面开着就连 · 断线重连
  GET /api/events                    · 不带 sid = 通配订阅（收所有会话后台事件）

背景（2026-09-16 实测）：
  前台对话走 /chat/stream 的 SSE，queue 是「每个连接一个」—— 你发消息才有连接。
  后台 turn（延迟唤醒 / 定时任务 / 分身通报）由 daemon 自己拉起、不写 SSE，
  产出只能落 jsonl 等前台轮询补。实测 21:30:53 触发 → 21:32:06 结束，中间 64 秒
  前端完全静默，BRO 以为出问题、手动刷新才看到。

本端点把「订阅」跟「turn 生命周期」解耦：页面开着就一直连着，
后台 turn 产出时经 daemon_api.broadcast_to_session() 推过来 —— 即时上屏。

事件名（复用前台已接住的既有语义，不造新通道）：
  event: hello       {"session_id": "...", "sink_id": "..."}
  event: bg_status   {"phase": "start"|"done", "label": "..."}
  event: bg_done     {"session_id": "...", "ts": "..."}

纪律：
  · 订阅者注销放 finally（防御模式④ Dispose 到静默）
  · 单个订阅者推送失败不影响其余（防御模式⑤ · 收在 broadcast_to_session 里）
  · keepalive 25s —— 跟 /chat/stream 同一口径，别让中间层掐连接
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from api_routes._deps import check_auth

router = APIRouter()

KEEPALIVE_INTERVAL = 25


@router.get("/api/events")
async def session_events(
    session_id: str = "",
    authorization: Optional[str] = Header(None),
    request: Request = None,
):
    """常驻会话事件流 · 页面开着就连 · 断线由前端重连。"""
    check_auth(authorization)
    # 不带 session_id = 通配订阅（收所有会话的后台事件）·
    # 前端只连一条、跨会话不用重连；收到后自己判 data.session_id === sessionId。
    sid = (session_id or "").strip() or "*"

    from daemon_api import register_session_sink, unregister_session_sink

    sink_id = "sink-" + uuid.uuid4().hex[:8]
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def push_event(event_type: str, data: dict):
        # 线程安全 · 调用方可能在后台线程里（_run_bg_turn）
        asyncio.run_coroutine_threadsafe(queue.put((event_type, data)), loop)

    register_session_sink(sid, sink_id, push_event)

    async def event_stream():
        hello = json.dumps({"session_id": sid, "sink_id": sink_id}, ensure_ascii=False)
        yield f"event: hello\ndata: {hello}\n\n"
        try:
            while True:
                if request is not None:
                    try:
                        if await request.is_disconnected():
                            break
                    except Exception:
                        pass
                try:
                    event_type, data = await asyncio.wait_for(
                        queue.get(), timeout=KEEPALIVE_INTERVAL
                    )
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                try:
                    data_str = json.dumps(data, ensure_ascii=False)
                except Exception:
                    data_str = json.dumps({"error": "non-serializable event payload"})
                yield f"event: {event_type}\ndata: {data_str}\n\n"
        finally:
            unregister_session_sink(sid, sink_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
