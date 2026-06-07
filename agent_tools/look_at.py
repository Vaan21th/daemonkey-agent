"""
agent_tools/look_at.py
======================

OPUS 的"眼睛"——看图然后回文字描述。

双路径视觉分发（wish-4a6331b2）：
  路径 A · 当前模型 supports_vision() == True (Claude/GPT/Gemini/Qwen)
    → 图片 base64 直接进当前模型的 user message → OPUS 自己"看"原图
    → 不经过中间视觉模型——就是 OPUS 的当前眼睛在看
  
  路径 B · 当前模型不支持 vision (DeepSeek/Kimi/GLM)
    → 调 Gemini 3.1 Flash Lite（通过同一 AiHubMix API）看图
    → 返回文字描述 → OPUS "看到"文字版描述
    → 一张图 < $0.001，够用且便宜

用途：
  - 用户 在 WebUI 发图 → daemon_api 调 look_at → 描述拼进 user message
  - OPUS 截屏后 → look_at 看屏幕 → 理解 用户 当前工作上下文
  - 用户 丢一张 PDF 扫描页 → look_at → 文字描述
  - 任何"OPUS 需要看到图片内容"的场景

限制：
  - 支持的格式：PNG / JPEG / GIF / WebP / BMP
  - 单张图上限 20MB（超过拒绝）
  - 宽 > 2560px 自动缩到 2560px（省 token，不丢关键信息）
  - 返回纯文本描述，不长于 2000 chars（防视觉模型跑偏输出小说）

档位：AUTO — 只读图 + 调 LLM 看图，无副作用
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from typing import Any

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool

from daemon_runtime import RUNTIME
from model_aliases import supports_vision

# ── 常量 ──────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 支持的图片格式 → MIME type
_EXT_MIME: dict[str, str] = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".bmp":  "image/bmp",
}

# 大图缩放阈值（宽或高超此值 → 等比缩到此值）
_MAX_DIMENSION = 2560

# 文件大小上限（字节）
_MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB

# 返回文字长度上限（chars）
_MAX_OUTPUT_CHARS = 2000

# ── 视觉 fallback 配置（从 .env 读取 · 与主模型完全解耦） ──

def _get_vision_fallback() -> tuple[str | None, str | None, str | None]:
    """读取独立视觉模型配置。返回 (model, base_url, api_key)。

    wish-4a6331b2 · 2026-06-03 独立配置系统：
      - 首先读 data/vision_config.json（WebUI 设置面板配的）
      - 回退到 .env 环境变量（命令行用户 / 老配置兼容）
      - 都未配时返回 (None, None, None)
    """
    from workers.vision_config import get_vision_model
    return get_vision_model()

# 看图 system prompt（给视觉模型的指令）
_LOOK_SYSTEM_PROMPT = (
    "你是一个高效的视觉助手。看用户发的图片，给出简洁准确的描述。"
    "不要加'这张图片显示'之类的废话开头，直接描述内容。"
    "如果图片里有文字，优先把文字逐字抄出来。"
    "如果图片是 UI/代码/错误信息，描述关键元素和位置。"
    "中文回复，控制在 500 字以内。"
)


# ── 图片处理 ──────────────────────────────────────────

def _read_and_encode(path_str: str) -> tuple[str, str]:
    """读取图片文件 · 必要时缩放 · 返回 (mime_type, base64_string)。

    Raises: FileNotFoundError, ValueError, OSError
    """
    file_path = Path(path_str)
    if not file_path.is_absolute():
        file_path = PROJECT_ROOT / file_path

    if not file_path.exists():
        raise FileNotFoundError(f"图片文件不存在: {file_path}")

    file_size = file_path.stat().st_size
    if file_size > _MAX_FILE_BYTES:
        raise ValueError(
            f"图片太大: {file_size / 1024 / 1024:.1f} MB · "
            f"上限 {_MAX_FILE_BYTES / 1024 / 1024:.0f} MB"
        )

    ext = file_path.suffix.lower()
    mime = _EXT_MIME.get(ext)
    if not mime:
        raise ValueError(
            f"不支持的图片格式: {ext} · "
            f"支持: {', '.join(_EXT_MIME.keys())}"
        )

    raw = file_path.read_bytes()

    # 检查是否需要缩放
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw))
        w, h = img.size
        if max(w, h) > _MAX_DIMENSION:
            ratio = _MAX_DIMENSION / max(w, h)
            new_size = (int(w * ratio), int(h * ratio))
            # 只对 RGB/RGBA 做 resize（P 模式先转）
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            img = img.resize(new_size, Image.LANCZOS)
            buf = io.BytesIO()
            save_fmt = "PNG" if img.mode == "RGBA" else "JPEG"
            img.save(buf, format=save_fmt, optimize=True)
            raw = buf.getvalue()
            # PNG 可能从 JPEG 源转过来——保持原 mime，base64 里 data URI 也兼容
            if save_fmt == "PNG" and ext in (".jpg", ".jpeg"):
                mime = "image/png"  # 实际编码变了，更新 mime
    except ImportError:
        pass  # 没有 Pillow 就不缩放，直接传原图

    b64 = base64.b64encode(raw).decode("ascii")
    return mime, b64


# ── 子 LLM 调用 ───────────────────────────────────────

def _vision_subcall(
    mime: str, b64: str, question: str,
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
) -> str:
    """用指定模型看图 · 返回文字描述。

    model / base_url / api_key:
      路径 A（多模态模型直接看）→ 用主模型 client (RUNTIME.client)
      路径 B（视觉 fallback）→ 可能用独立 client（如果配了独立 key/url）
    """
    if api_key and base_url:
        # 路径 B · 独立视觉模型 → 建临时 client
        # 用户可能贴完整 URL · OpenAI SDK 会自动加 /chat/completions · 这里去尾防重复
        _url = base_url.rstrip("/")
        if _url.endswith("/chat/completions"):
            _url = _url[: -len("/chat/completions")]
        from openai import OpenAI as _OpenAI
        client: Any = _OpenAI(api_key=api_key, base_url=_url, timeout=30)
    else:
        client = RUNTIME.client
        if client is None:
            raise RuntimeError("RUNTIME.client 未初始化且无独立视觉模型配置")

    data_uri = f"data:{mime};base64,{b64}"

    messages = [
        {"role": "system", "content": _LOOK_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        },
    ]

    resp = client.chat.completions.create(
        model=model,
        max_tokens=1024,
        messages=messages,
        temperature=0.3,  # 看图要准确，低温度
    )

    text = resp.choices[0].message.content or ""
    # 截断（防视觉模型跑偏）
    if len(text) > _MAX_OUTPUT_CHARS:
        text = text[:_MAX_OUTPUT_CHARS] + "…"
    return text.strip()


# ── 工具入口 ──────────────────────────────────────────

def _summarize(args: dict) -> str:
    path = args.get("path", "")
    question = args.get("question", "")
    q_tail = f"  q={question[:40]}…" if question else ""
    return f"look_at  path={path!r}{q_tail}"


def _run(args: dict) -> ToolResult:
    path_str = (args.get("path") or "").strip()
    if not path_str:
        return ToolResult(ok=False, output="", error="缺少参数 path · 传图片文件路径")

    question = (args.get("question") or "").strip()
    if not question:
        question = "请描述这张图片的内容。如果有文字，逐字抄出来。"

    # 1. 读图 + 编码
    try:
        mime, b64 = _read_and_encode(path_str)
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except OSError as e:
        return ToolResult(ok=False, output="", error=f"读取图片失败: {e}")

    # 2. 判断路径
    current_model = RUNTIME.model or ""
    use_vision_model: str
    path_label: str

    if supports_vision(current_model):
        use_vision_model = current_model
        path_label = f"路径 A · 当前模型 ({current_model}) 直接看图"
    else:
        # 读取独立视觉模型配置
        vis_model, vis_url, vis_key = _get_vision_fallback()
        if not vis_model:
            return ToolResult(
                ok=False, output="",
                error=(
                    f"当前模型 ({current_model}) 不支持视觉，且未配置视觉模型。\n"
                    "去 WebUI 设置面板 → 👁 视觉模型 → 配一个支持图片的模型即可。\n"
                    "推荐 Google AI Studio (免费): https://aistudio.google.com"
                ),
            )
        use_vision_model = vis_model
        path_label = (
            f"路径 B · 当前模型 ({current_model}) 不支持视觉 · "
            f"fallback → {vis_model}"
        )

    # 3. 调视觉模型
    try:
        # 路径 A: 无独立 key → 走主 client；路径 B: 有独立 key → 传独立 client 参数
        if use_vision_model == current_model:
            description = _vision_subcall(mime, b64, question, use_vision_model)
        else:
            _, vis_url, vis_key = _get_vision_fallback()
            description = _vision_subcall(mime, b64, question, use_vision_model, vis_url, vis_key)
    except Exception as e:
        return ToolResult(
            ok=False, output="",
            error=f"视觉模型调用失败: {type(e).__name__}: {e}",
        )

    # 4. 返回
    b64_len_kb = len(b64) * 3 // 4 // 1024  # base64 → 原始字节 ≈ 3/4
    output = (
        f"{path_label}\n"
        f"图片: {mime} · ~{b64_len_kb} KB (base64)\n"
        f"───\n"
        f"{description}"
    )
    return ToolResult(ok=True, output=output)


SPEC = ToolSpec(
    name="look_at",
    description=(
        "让 OPUS 看一张图片并返回文字描述。双路径：当前模型支持多模态（Claude/GPT/"
        "Gemini/Qwen）→ 直接看图；当前模型纯文本（DeepSeek/Kimi/GLM）→ 调 Gemini "
        "Flash Lite fallback 看图。\n\n"
        "**调用时机**：\n"
        "  - 截屏后想看屏幕内容（配合 take_screenshot）\n"
        "  - 用户 在 WebUI 上传了图片\n"
        "  - 用户 让你看某张图片 / 截图 / 照片\n"
        "  - 需要从图片中提取文字 / 错误信息\n\n"
        "**参数**：path（图片路径·必填），question（想问什么·可选·默认描述整张图）\n"
        "**返回**：纯文本描述。多模态模型看到的是原图（更精确），纯文本模型看到的是"
        "fallback 文字描述（够用）。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "图片文件路径。绝对路径或相对于 Daemonkey 根目录。支持 PNG/JPG/GIF/WebP/BMP。"
            },
            "question": {
                "type": "string",
                "description": "想问这张图片什么。默认'请描述这张图片的内容'。提示：'这张截图里有什么错误信息'/'图中文字是什么'/'识别图片中的物体'"
            },
        },
        "required": ["path"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
