"""agent_tools/render_png.py

把本地 HTML（中栏画布页）渲成整页长图 —— 微信 / 飞书通道发图用。

为什么需要它：**`.html` 发过去等于没发** —— 手机上只提示"用其他应用打开"，
微信下载目录浏览器还读不到。发一张图，点开就能看，两个通道一视同仁。

为什么不自动分发：通道判别（api-wechat-* / api-feishu-*）和发送工具都在，
但**微信/飞书通道这条线还没在真机上实测过**。先给能力、我在通道下自己发，
等通道真跑顺了再谈"daemon 层按通道自动分发"——不然就是又一次假就绪。

实现落在 workers/html_shot.py（Playwright 整页截图 · 按页高自适应缩放）。
"""
from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _fmt_size(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def _run(args: dict) -> ToolResult:
    import os
    import struct

    from workers.html_shot import shot_html
    from workers.stage_open import is_stage_html

    path = (args.get("path") or "").strip().replace("\\", "/")
    if not path:
        return ToolResult(
            ok=False, output="",
            error="path 必填 · 传 data/ 下 HTML 的相对路径（如 data/design/xxx.html）",
        )
    if not is_stage_html(path):
        return ToolResult(
            ok=False, output="",
            error=(
                "只渲工坊成品树里的 HTML（data/design · data/workshop/outputs · "
                "data/docs · data/dev · data/content · data/presentations）。"
                f" 收到 {path!r}。"
            ),
        )

    width = int(args.get("width") or 900)
    _scale = args.get("scale")
    try:
        scale = float(_scale) if _scale else None
    except (TypeError, ValueError):
        scale = None

    try:
        rel = shot_html(path, width=width, scale=scale)
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"渲染失败: {type(e).__name__}: {str(e)[:200]}")

    try:
        with open(rel, "rb") as f:
            w, h = struct.unpack(">II", f.read(24)[16:24])
        size = os.path.getsize(rel)
        shape = f"{w} × {h} · 长宽比 {h / w:.1f}:1"
    except Exception:
        shape, size = "", 0

    return ToolResult(
        ok=True,
        output="\n".join([
            f"已渲图 · {rel}",
            f"  {shape} · {_fmt_size(size)}",
            "",
            "微信/飞书通道：wechat_send(media_path=...) / feishu_send(media_path=...) 直接发这张图。",
        ]),
    )


def _summarize(args: dict) -> str:
    return f"🖼 渲图 · {args.get('path') or '(未指定)'}"


SPEC = ToolSpec(
    name="render_png",
    description=(
        "把中栏画布页（HTML）渲成整页长图 PNG · 给微信/飞书通道发图用（那边 .html 打不开）。"
        " 只认工坊成品树里的 HTML；渲染 6 秒左右 · 出图后配 wechat_send / feishu_send 发出去。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "data/ 下 HTML 的相对路径 · 如 data/design/xxx.html",
            },
            "width": {
                "type": "integer",
                "description": "视口宽度，默认 900（手机看长图这个宽度够）",
            },
            "scale": {
                "type": "number",
                "description": "缩放倍率 · 不传按页高自适应（越高越小，免得手机上糊）",
            },
        },
        "required": ["path"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
