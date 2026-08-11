"""
agent_tools/feishu_send.py
==========================

主动给用户发飞书消息（文本 / 文件）· 对称 wechat_send。

为什么独立成工具：
  - 飞书 listener 做的是『用户发来 → 处理 → 自动回』
  - 但主动发文件/通知（"打包完成" / 代码包 / 报告）一直 python_exec 手搓调
    feishu_client——08-09 两次打包发飞书都这么干（飞书链路代码包 + 记忆系统代码包）。
    做成工具后其他流程/定时任务可直接调·不再每次从零写调用代码。
  - receive_id 默认从当前 session_id 解析（api-feishu-user_ou_xxx-sN → ou_xxx）·
    也可显式传 receive_id + receive_id_type（发到群聊等）。

CONFIRM 档：主动发飞书是有形动作。
"""

from __future__ import annotations

from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _resolve_open_id(session_id: str) -> str:
    """从 session_id 解析飞书 open_id: api-feishu-user_ou_xxx-sN → ou_xxx"""
    if not session_id:
        return ""
    seg = [p for p in session_id.split("-") if p.startswith("user_ou_")]
    if seg:
        return seg[0].replace("user_", "", 1)
    seg = [p for p in session_id.split("-") if p.startswith("ou_")]
    if seg:
        return seg[0]
    return ""


def _current_session_id() -> str:
    try:
        from daemon_runtime import RUNTIME
        return getattr(RUNTIME, "session_id", "") or ""
    except Exception:
        return ""


def _summarize(args: dict) -> str:
    text = (args.get("text") or "").strip()
    media = (args.get("media_path") or "").strip()
    rid = (args.get("receive_id") or "").strip() or "(auto)"
    if media:
        cap = f" · caption {len(text)} chars" if text else ""
        size = ""
        try:
            _sz = Path(media).stat().st_size
            size = f" · {_sz//1024}KB" if _sz < 1024 * 1024 else f" · {_sz//1024//1024}MB"
        except Exception:
            pass
        return f"feishu_send  文件 {Path(media).name}{size} → 飞书 {rid}{cap}"
    preview = text[:50].replace("\n", " ")
    if len(text) > 50:
        preview += "..."
    return f"feishu_send  {len(text)} chars → 飞书 {rid}  · {preview!r}"


def _run(args: dict) -> ToolResult:
    from workers import feishu_client

    text = (args.get("text") or "").strip()
    media_path = (args.get("media_path") or "").strip()
    receive_id = (args.get("receive_id") or "").strip()
    rid_type = (args.get("receive_id_type") or "").strip() or "open_id"

    # Important 1 · 8000 上限全程生效 (纯文本 + 前导文字统一)
    if len(text) > 8000:
        return ToolResult(
            ok=False, output="",
            error=f"message too long: {len(text)} chars (limit 8000)",
        )

    if not receive_id:
        receive_id = _resolve_open_id(_current_session_id())
    if not receive_id:
        return ToolResult(
            ok=False, output="",
            error=(
                "feishu_send · 拿不到 receive_id：当前会话不是飞书会话，且你没显式传 receive_id。"
                "传 receive_id（open_id / chat_id）+ receive_id_type 重试。"
            ),
        )

    if not media_path and not text:
        return ToolResult(ok=False, output="", error="text cannot be empty (媒体请走 media_path)")

    if media_path:
        p = Path(media_path)
        if not p.exists() or not p.is_file():
            return ToolResult(ok=False, output="", error=f"文件不存在: {media_path}")
        # Important 3 · 20MB 预检在发前导前 (防"先发说明后报错"的顺序倒置)
        if p.stat().st_size > 20 * 1024 * 1024:
            return ToolResult(
                ok=False, output="",
                error=f"文件 {p.stat().st_size // 1024 // 1024}MB 超 20MB 上限",
            )
        # 前导文字先发（用户先看说明再收文件）· 飞书 file 消息无 caption 字段
        lead = ""
        if text:
            r0 = feishu_client.send_text(text, receive_id, rid_type)
            if not r0.get("ok"):
                # Important 2 · 前导失败即中止 (防 receive_id 无效时文件也白跑)
                return ToolResult(
                    ok=False, output="",
                    error=f"前导文字发送失败: {r0.get('msg') or r0.get('error', '')}",
                )
            lead = " · 前导文字已发"
        r = feishu_client.send_file(str(p), receive_id, rid_type)
        if not r.get("ok"):
            return ToolResult(
                ok=False, output="",
                error=f"飞书发文件失败: {r.get('msg') or r.get('error', '')}",
            )
        return ToolResult(
            ok=True,
            output=(
                f"feishu_send · 已发文件到飞书 {rid_type}={receive_id} · "
                f"{p.name} ({p.stat().st_size} bytes){lead}"
            ),
        )

    r = feishu_client.send_text(text, receive_id, rid_type)
    if r.get("ok"):
        return ToolResult(ok=True, output=f"feishu_send · 已发到飞书 {rid_type}={receive_id} ({len(text)} chars)")
    return ToolResult(ok=False, output="", error=f"飞书发送失败: {r.get('msg') or r.get('error', '')}")


SPEC = ToolSpec(
    name="feishu_send",
    description=(
        "Proactively send a message to the user on Feishu (Lark) — text and/or a file. "
        "`media_path` → sends the local file as a Feishu file message (≤20 MB); `text` then becomes "
        "an optional leading text message. Without media_path, `text` is sent as a plain text message. "
        "`receive_id` defaults to the current session's Feishu open_id (auto-resolved when the session "
        "is an api-feishu-* session); pass it explicitly (with receive_id_type) when auto-resolution "
        "fails or you target a chat. Use for: delivering packaged code / reports / files, "
        "notifying the user of long-task completion on Feishu. DO NOT use for: every reply "
        "(incoming Feishu chats are auto-answered). Tier CONFIRM."
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": (
                    "Message text to send (1-8000 chars). When media_path is set, sent as a "
                    "leading text message before the file."
                ),
            },
            "media_path": {
                "type": "string",
                "description": (
                    "Optional local file path to send as a Feishu file message (≤20 MB). "
                    "Must be an existing local file."
                ),
            },
            "receive_id": {
                "type": "string",
                "description": (
                    "Optional target: open_id / chat_id / user_id. Defaults to the current "
                    "session's Feishu open_id when the session is api-feishu-*."
                ),
            },
            "receive_id_type": {
                "type": "string",
                "enum": ["open_id", "chat_id", "user_id"],
                "description": "Type of receive_id (default open_id).",
            },
        },
        "required": [],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
