"""
agent_tools/wechat_send.py
==========================

主动给用户发微信（文本 / 媒体）。

为什么独立成工具：
  - 微信监听器做的是『用户发来 → 处理 → 自动回』
  - 但有时你想**主动**开口（"长任务跑完了" / "X 小时后提醒我" / 某个结果）——
    这种不走用户提问流程·这个工具就是入口

实现：
  - 走官方 iLink 渠道（设置 → 微信 & 主动 里扫码连上自己的微信后即可用）
  - 文本：24h 窗口开着就直接发
  - 媒体（media_path）：iLink CDN 上传·图片 / 视频 / 文件·同样受 24h 窗口约束
  - 没连微信 / 窗口关了 → 工具会明说·绝不假装发出去

CONFIRM 档：主动发微信是有形动作（别半夜 3 点突然发"在吗"）·即使 yolo 也建议看一眼摘要。
"""

from __future__ import annotations

from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


_NOT_CONFIGURED = "微信还没连上·发不了。先到 设置 → 微信 & 主动 里扫码连上你自己的微信再试。"
_WINDOW_CLOSED = (
    "wechat_send · 微信 24h 窗口已关（用户超过 24h 没在微信开口）·这条发不出去。"
    "等用户下次在微信说话开窗后再发·或直接在 WebUI 告诉他。"
)


def _summarize(args: dict) -> str:
    text = (args.get("text") or "").strip()
    media = (args.get("media_path") or "").strip()
    if media:
        cap = f" · caption {len(text)} chars" if text else ""
        return f"wechat_send  媒体 {Path(media).name}  → 微信{cap}"
    preview = text[:50].replace("\n", " ")
    if len(text) > 50:
        preview += "..."
    return f"wechat_send  {len(text)} chars  → 微信  · {preview!r}"


def _run_media(media_path: str, caption: str) -> ToolResult:
    try:
        from workers import ilink_client, ilink_media
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"微信媒体模块不可用: {type(e).__name__}: {e}")
    if not ilink_client.enabled():
        return ToolResult(ok=False, output="", error=_NOT_CONFIGURED)
    r = ilink_media.send_media(media_path, caption=caption)
    if r.get("ok"):
        cap = f" · caption {len(caption)} chars" if caption else ""
        return ToolResult(ok=True, output=f"wechat_send · 已发{r['kind']}到微信 ({r['bytes']} bytes){cap}")
    err = r.get("error", "")
    if err == "window_closed":
        return ToolResult(ok=True, output=_WINDOW_CLOSED)
    if err == "silent_mode":
        return ToolResult(ok=True, output="wechat_send · 微信处于静默 (opus stop)·没发。等用户发 opus start 再说。")
    return ToolResult(ok=False, output="", error=f"发媒体失败: {err} {r.get('resp', '')}".strip())


def _run(args: dict) -> ToolResult:
    text = (args.get("text") or "").strip()
    media_path = (args.get("media_path") or "").strip()
    if media_path:
        return _run_media(media_path, text)
    if not text:
        return ToolResult(ok=False, output="", error="text cannot be empty (媒体请走 media_path)")
    if len(text) > 8000:
        return ToolResult(
            ok=False, output="",
            error=f"message too long: {len(text)} chars (limit 8000). 拆开发或先 summarize",
        )

    try:
        from workers import ilink_client
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"微信模块不可用: {type(e).__name__}: {e}")
    if not ilink_client.enabled():
        return ToolResult(ok=False, output="", error=_NOT_CONFIGURED)
    if not ilink_client.window_open():
        return ToolResult(ok=True, output=_WINDOW_CLOSED)
    r = ilink_client.send_text(text)
    if r.get("ok"):
        return ToolResult(ok=True, output=f"wechat_send · 已发到微信 ({len(text)} chars)")
    return ToolResult(ok=False, output="", error=f"微信发送失败: {r}")


SPEC = ToolSpec(
    name="wechat_send",
    description=(
        "Proactively send a message — text and/or media (image/video/file) — to the user on WeChat "
        "through the official iLink channel. To send media, set `media_path` to a local file path: "
        "images→图片, videos→视频, anything else→文件附件; `text` then becomes an optional caption. "
        "REQUIRES the user to have connected WeChat (Settings → 微信 & 主动, scan the QR) AND the iLink "
        "24h window to be open (the user must have messaged you on WeChat within ~24h) — otherwise the "
        "tool says so instead of sending. Use for: notifying the user when a long task completes, "
        "sending a screenshot / generated chart / report file, gentle reminders, or following up later. "
        "DO NOT use for: every reply (incoming WeChat chats are auto-answered), 'just to chat' messages, "
        "or anything the user didn't opt into. Tier CONFIRM."
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": (
                    "Message text to send to the user (1-8000 chars). "
                    "When media_path is set, this is an optional caption sent before the media."
                ),
            },
            "media_path": {
                "type": "string",
                "description": (
                    "Optional local file path to send as media. Routed by file type: "
                    "image/* → 图片, video/* → 视频, otherwise → 文件附件 (≤25 MB). "
                    "Requires WeChat connected and the 24h window open."
                ),
            },
        },
        "required": [],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
