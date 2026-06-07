"""
workers/vision_config.py
========================

视觉模型独立配置（wish-4a6331b2 · 2026-06-03）。

跟 provider_configs 不同——这是**单例**，不是多配置 CRUD：
  - 一次只配一个视觉模型（全局 fallback）
  - 不跟主 LLM 提供商耦合
  - 数据落 data/vision_config.json

为什么独立文件：
  - 开源用户第一次配视觉模型不应该去翻 .env
  - 视觉模型和主对话模型可能来自不同 API 提供商
  - 主模型多模态时自动跳过，纯文本时自动调用——用户不用管
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = DATA_DIR / "vision_config.json"


def load_vision_config() -> dict:
    """读取视觉模型配置。文件不存在返回空骨架。"""
    if not CONFIG_PATH.exists():
        return {"model": "", "base_url": "", "api_key": "", "configured": False}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"model": "", "base_url": "", "api_key": "", "configured": False}


def save_vision_config(cfg: dict) -> None:
    """写入视觉模型配置。自动标记 configured。"""
    cfg["configured"] = bool(
        cfg.get("model", "").strip()
        and cfg.get("base_url", "").strip()
        and cfg.get("api_key", "").strip()
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_vision_model() -> tuple[Optional[str], Optional[str], Optional[str]]:
    """返回 (model, base_url, api_key)。未配置时全 None。

    优先级：data/vision_config.json → .env 回退 → None
    """
    cfg = load_vision_config()
    if cfg.get("configured"):
        return (
            cfg["model"].strip(),
            cfg["base_url"].strip(),
            cfg["api_key"].strip(),
        )

    # 回退：检查 .env（兼容老配置 / 命令行用户）
    model = (os.getenv("OPUS_VISION_MODEL") or "").strip()
    if model:
        base_url = (os.getenv("OPUS_VISION_BASE_URL") or "").strip()
        api_key = (os.getenv("OPUS_VISION_API_KEY") or "").strip()
        if not api_key:
            api_key = (os.getenv("OPUS_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or "").strip()
        if not base_url:
            base_url = (os.getenv("OPUS_BASE_URL") or "").strip()
        if model and base_url and api_key:
            return model, base_url, api_key

    return None, None, None
