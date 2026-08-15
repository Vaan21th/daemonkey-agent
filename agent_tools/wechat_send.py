"""
agent_tools/wechat_send.py
==========================

Daemonkey 主动给 BRO（或别人）发微信。

为什么独立工具：
  - 桥接（wechat_bridge.py）做的是"BRO 发来 → daemon 处理 → 自动回 BRO"
  - 但 Daemonkey 想**主动**发消息给 BRO（"任务完成了"/"该睡觉了"/某个长跑结果）
    时不走 BRO 提问流程——这个工具就是这种场景的入口

实现：
  - 文本：优先走官方 iLink → 退回 outbox.txt（如果 bridge 在跑就立即发到 BRO）
  - 媒体（media_path）：走 iLink CDN 上传链路（图片/视频/文件），受 24h 窗口约束
  - bridge 没在跑也不报错——只是把文本留在 outbox.txt 等 bridge 启动后消费

CONFIRM 档：
  - 主动发微信是有形动作（不能让 Daemonkey 半夜 3 点突然给 BRO 发"在吗"）
  - 即使 yolo on 也建议你看一眼摘要

媒体（卷六十二）：
  - media_path = 本地文件路径·按 MIME 自动分流：图片 / 视频 / 其它→文件附件
  - 只能走 iLink（outbox/wcferry 不支持媒体）·且必须 24h 窗口开着
  - text 此时是可选 caption（媒体前导文字）

不支持：
  - 给非 BRO 的人发（Phase 1 单目标）
"""

from __future__ import annotations

from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTBOX_FILE = PROJECT_ROOT / "desktop_pet" / "outbox.txt"


def _summarize(args: dict) -> str:
    text = (args.get("text") or "").strip()
    media = (args.get("media_path") or "").strip()
    if media:
        cap = f" · caption {len(text)} chars" if text else ""
        return f"wechat_send  媒体 {Path(media).name}  → BRO{cap}"
    preview = text[:50].replace("\n", " ")
    if len(text) > 50:
        preview += "..."
    return f"wechat_send  {len(text)} chars  → BRO  · {preview!r}"


def _run_media(media_path: str, caption: str) -> ToolResult:
    try:
        from workers import ilink_client, ilink_media
    except Exception as e:
        return ToolResult(
            ok=False, output="",
            error=(
                f"微信发媒体的依赖没装好: {type(e).__name__}: {e}\n"
                "发文件/图片/视频需要 cryptography (AES 加密走微信 CDN)。装上就能发:\n"
                "  .venv\\Scripts\\pip install cryptography\n"
                "(或重跑 run.ps1 / 启动器·会按 requirements.txt 补装)\n"
                "【重要】装好前别退而给本地 http://127.0.0.1 链接——他在手机上打不开"
                "(127.0.0.1 在手机上指的是手机自己)。如实说『发文件还差个依赖·装上就能发』。"
            ),
        )
    if not ilink_client.enabled():
        return ToolResult(
            ok=False, output="",
            error="微信 iLink 未配置/未启用·发不了媒体。先在设置 → 微信 & 主动 里扫码连微信。",
        )
    r = ilink_media.send_media(media_path, caption=caption)
    if r.get("ok"):
        cap = f" · caption {len(caption)} chars" if caption else ""
        return ToolResult(
            ok=True,
            output=f"wechat_send · 已通过 iLink 发{r['kind']}给 BRO ({r['bytes']} bytes){cap}",
        )
    err = r.get("error", "")
    if err == "window_closed":
        return ToolResult(
            ok=True,
            output=(
                "wechat_send · iLink 24h 窗口已关 (BRO 超过 24h 没在微信开口)·"
                "这个媒体发不出去。等 BRO 下次在微信说话开窗后再发·或走 WebUI 发给他。"
            ),
        )
    if err == "silent_mode":
        return ToolResult(ok=True, output="wechat_send · 微信处于静默 (Daemonkey stop)·没发。等 BRO 发 Daemonkey start 再说。")
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

    # 优先走官方 iLink 渠道 (卷六十一)：24h 窗口开着就直接发·安全、无封号风险
    try:
        from workers import ilink_client
        if ilink_client.enabled():
            if ilink_client.window_open():
                r = ilink_client.send_text(text)
                if r.get("ok"):
                    return ToolResult(
                        ok=True,
                        output=f"wechat_send · 已通过官方 iLink 发给 BRO ({len(text)} chars)",
                    )
            else:
                return ToolResult(
                    ok=True,
                    output=(
                        "wechat_send · iLink 24h 窗口已关 (BRO 超过 24h 没在微信开口)·"
                        "这条发不出去。等 BRO 下次在微信说话开窗后再发·或走 WebUI 告诉他。"
                    ),
                )
    except Exception:
        pass  # iLink 不可用 → 退回 outbox (wcferry) 兜底

    try:
        OUTBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing = OUTBOX_FILE.read_text(encoding="utf-8") if OUTBOX_FILE.exists() else ""
        # 累加而不是覆盖——同一轮可能多次写
        new_content = (existing.rstrip() + "\n\n" + text).strip() if existing.strip() else text
        OUTBOX_FILE.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"failed to write outbox: {type(e).__name__}: {e}")

    return ToolResult(
        ok=True,
        output=(
            f"wechat_send · queued to outbox\n"
            f"  text: {len(text)} chars\n"
            f"  outbox: {OUTBOX_FILE.relative_to(PROJECT_ROOT)}\n"
            f"  → wechat_bridge.py 会在下一次 poll（≤ 0.5s）转发给 BRO\n"
            f"  如果 bridge 没在跑，消息会留在 outbox 等 bridge 启动后消费"
        ),
    )


SPEC = ToolSpec(
    name="wechat_send",
    description=(
        "Send a message — text and/or media (image/video/file) — to BRO via WeChat. "
        "Text goes through the official iLink channel (falls back to the bridge outbox). "
        "To send media, set `media_path` to a local file path: images→图片, videos→视频, "
        "anything else→文件附件; `text` then becomes an optional caption. "
        "Media REQUIRES the iLink 24h window to be open (BRO must have messaged you on WeChat "
        "within ~24h) — if it's closed the tool will say so instead of sending. "
        "Use for: actively notifying BRO when a long task completes, sending him a screenshot / "
        "generated chart / report file, gentle reminders, or following up on something later. "
        "DO NOT use for: every reply (the bridge handles that automatically), 'just to chat' "
        "messages, or anything BRO didn't opt into. Tier CONFIRM."
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": (
                    "Message text to send to BRO (1-8000 chars). "
                    "When media_path is set, this is an optional caption sent before the media."
                ),
            },
            "media_path": {
                "type": "string",
                "description": (
                    "Optional local file path to send as media. Routed by file type: "
                    "image/* → 图片, video/* → 视频, otherwise → 文件附件 (≤25 MB). "
                    "Requires iLink configured and the 24h window open."
                ),
            },
        },
        "required": [],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
