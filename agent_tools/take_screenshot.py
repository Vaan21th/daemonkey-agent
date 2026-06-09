"""
agent_tools/take_screenshot.py
==============================

OPUS 看到 BRO 屏幕的入口。

实现：用 Pillow 自带的 ImageGrab（Windows / macOS 原生，零依赖增量）。
保存到 sessions/screenshots/<timestamp>.png 或返回路径。

档位：AUTO
  - 截屏只是读取屏幕状态，BRO 在终端能看到调用
  - 如果 BRO 在做敏感操作（密码窗），他自己会 yolo off

省钱角度：
  - 截屏 PNG 文件可能很大（4K 屏 ~5MB）
  - **不把图回灌进 messages**——只返回文件路径
  - BRO 想让 OPUS 真"看"图时，配合 read_file（v0.2 加 vision-capable model 路由）
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHOT_DIR = PROJECT_ROOT / "sessions" / "screenshots"


def _summarize(args: dict) -> str:
    region = args.get("region")
    return f"take_screenshot  region={region or 'fullscreen'}"


def _run(args: dict) -> ToolResult:
    try:
        from PIL import ImageGrab
    except ImportError:
        return ToolResult(
            ok=False, output="",
            error="Pillow not installed; run: pip install Pillow",
        )

    SHOT_DIR.mkdir(parents=True, exist_ok=True)

    region = args.get("region")
    bbox = None
    if region and isinstance(region, dict):
        try:
            bbox = (
                int(region["left"]),
                int(region["top"]),
                int(region["right"]),
                int(region["bottom"]),
            )
        except (KeyError, ValueError, TypeError) as e:
            return ToolResult(ok=False, output="", error=f"bad region {region!r}: {e}")

    try:
        img = ImageGrab.grab(bbox=bbox, all_screens=True)
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"screen grab failed: {e!r}")

    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    name = args.get("filename") or f"shot_{ts}.png"
    if not name.endswith(".png"):
        name += ".png"
    out_path = SHOT_DIR / name

    try:
        img.save(out_path, optimize=True)
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"save failed: {e!r}")

    rel = out_path.relative_to(PROJECT_ROOT)
    from identity import localize_narration as _ln
    return ToolResult(
        ok=True,
        output=_ln(
            f"screenshot saved\n"
            f"  path: {rel}\n"
            f"  size: {img.size[0]}x{img.size[1]} px\n"
            f"  bytes: {out_path.stat().st_size}\n"
            f"  region: {bbox or 'all screens'}\n"
            f"  next: BRO can view it / OPUS can read_file the path if vision model is active"
        ),
    )


SPEC = ToolSpec(
    name="take_screenshot",
    description=(
        "Capture a screenshot of BRO's screen. Saved to sessions/screenshots/. "
        "Returns the file path (NOT the image data—saves tokens). "
        "Use when BRO says 'look at my screen', 'see this', or you need visual context "
        "of his current work. Optional region={left,top,right,bottom} for a specific area; "
        "default captures all screens."
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "region": {
                "type": "object",
                "description": "Optional bounding box {left, top, right, bottom} in screen pixels",
                "properties": {
                    "left":   {"type": "integer"},
                    "top":    {"type": "integer"},
                    "right":  {"type": "integer"},
                    "bottom": {"type": "integer"},
                },
            },
            "filename": {
                "type": "string",
                "description": "Optional filename (auto-generated timestamp if omitted)",
            },
        },
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
