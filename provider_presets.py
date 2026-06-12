"""
provider_presets.py
===================

卷三十六 · 多 LLM 预设管理

为啥要：
  - 之前换 provider 要改 .env 重启 daemon · BRO 很烦
  - aihubmix 欠费瞬间无感·这种事不该再发生
  - 设计目标里有"开源后任何人下载都能跑"·得让用户在 UI 里选 provider

预设清单：
  - DeepSeek 官方 (推荐 · 便宜 30 倍)
  - AiHubMix (一个 key 通吃多模型 · 中转贵)
  - Anthropic 官方 (Claude 顶级 · 最贵)
  - OpenRouter (300+ 模型 · 中转)
  - DashScope (阿里通义 · 国内云)
  - 自定义 (任意 OpenAI 兼容 base_url)

每个预设给：
  - id / name / base_url / 推荐模型列表 / key 格式说明 / 注册地址
  - 不存任何真 key · 真 key 走 .env

热切换：
  setup_client(provider) 重建 client → 替换 RUNTIME.client / model / provider / base_url
  不重启 daemon · 不丢 session

测试：
  send 一句最小 prompt (max_tokens=20) · 拿到回复就算通
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProviderPreset:
    """一个 LLM provider 预设."""
    id: str
    name: str
    base_url: str
    provider_kind: str  # 'openai' | 'anthropic'
    recommended_models: list[dict] = field(default_factory=list)  # [{id, label, note, family}]
    key_hint: str = ""
    signup_url: str = ""
    note: str = ""


# 5 个预设 · 按推荐度排序 (DeepSeek 官方第一 · 实测便宜 30 倍)
PRESETS: list[ProviderPreset] = [
    ProviderPreset(
        id="deepseek-official",
        name="DeepSeek 官方",
        base_url="https://api.deepseek.com/v1",
        provider_kind="openai",
        recommended_models=[
            {
                "id": "deepseek-v4-pro",
                "label": "DeepSeek V4 Pro · $0.435/M in · $0.87/M out · cache hit $0.003625/M",
                "note": "旗舰 · 1M context · 支持 thinking · 推荐日常",
                "family": "deepseek",
                "context_window": 1_000_000,
                "max_output": 384_000,
                "max_tokens_default": 32_768,
            },
            {
                "id": "deepseek-v4-flash",
                "label": "DeepSeek V4 Flash · $0.14/M in · $0.28/M out · cache hit $0.0028/M",
                "note": "轻量 · 更便宜 · 简单任务足够",
                "family": "deepseek",
                "context_window": 1_000_000,
                "max_output": 384_000,
                "max_tokens_default": 16_384,
            },
        ],
        key_hint="sk-xxx · 32 位左右",
        signup_url="https://platform.deepseek.com/api_keys",
        note="实测便宜 aihubmix 30 倍 · 强烈推荐",
    ),
    ProviderPreset(
        id="aihubmix",
        name="AiHubMix (中转)",
        base_url="https://aihubmix.com/v1",
        provider_kind="openai",
        recommended_models=[
            {
                "id": "deepseek-v4-pro",
                "label": "DeepSeek V4 Pro (走 aihubmix)",
                "note": "比官方贵约 30 倍 · 但能一个 key 通吃多家",
                "family": "deepseek",
                "context_window": 1_000_000,
                "max_output": 384_000,
                "max_tokens_default": 32_768,
            },
            {
                "id": "claude-sonnet-4-6",
                "label": "Claude Sonnet 4.6 (走 aihubmix)",
                "note": "Anthropic 旗舰 · 中转价",
                "family": "claude",
                "context_window": 200_000,
                "max_output": 64_000,
                "max_tokens_default": 8_192,
            },
            {
                "id": "claude-opus-4-7",
                "label": "Claude Opus 4.7 (走 aihubmix)",
                "note": "Anthropic 顶配 · 深聊用",
                "family": "claude",
                "context_window": 200_000,
                "max_output": 32_000,
                "max_tokens_default": 8_192,
            },
            {
                "id": "kimi-k2.6",
                "label": "Kimi K2.6 (走 aihubmix)",
                "note": "Agent / 工具能力强 · 262K",
                "family": "kimi",
                "context_window": 262_144,
                "max_output": 16_384,
                "max_tokens_default": 8_192,
            },
            {
                "id": "glm-5.1",
                "label": "GLM 5.1 (走 aihubmix)",
                "note": "智谱旗舰 · 200K · 写代码强",
                "family": "glm",
                "context_window": 200_000,
                "max_output": 16_384,
                "max_tokens_default": 8_192,
            },
            {
                "id": "gpt-5-mini",
                "label": "GPT-5 mini (走 aihubmix)",
                "note": "OpenAI 中转",
                "family": "gpt",
                "context_window": 200_000,
                "max_output": 16_384,
                "max_tokens_default": 8_192,
            },
            {
                "id": "gpt-5.5",
                "label": "GPT-5.5 (走 aihubmix)",
                "note": "最新 · 强",
                "family": "gpt",
                "context_window": 400_000,
                "max_output": 64_000,
                "max_tokens_default": 16_384,
            },
        ],
        key_hint="sk-xxx · 40+ 位",
        signup_url="https://aihubmix.com/",
        note="多模型一个 key · 适合实验各家模型 · 日常用贵",
    ),
    ProviderPreset(
        id="anthropic",
        name="Anthropic 官方",
        base_url="",  # SDK 默认
        provider_kind="anthropic",
        recommended_models=[
            {
                "id": "claude-sonnet-4-5-20250929",
                "label": "Claude Sonnet 4.5 · $3/M in · $15/M out · cache 90%",
                "note": "顶级编码 · 顶级推理 · 贵但稳",
                "family": "claude",
                "context_window": 200_000,
                "max_output": 64_000,
                "max_tokens_default": 8_192,
            },
            {
                "id": "claude-opus-4-7-20251104",
                "label": "Claude Opus 4.7 · $15/M in · $75/M out",
                "note": "顶配 · 重活才用",
                "family": "claude",
                "context_window": 200_000,
                "max_output": 32_000,
                "max_tokens_default": 8_192,
            },
            {
                "id": "claude-haiku-4-5-20251022",
                "label": "Claude Haiku 4.5 · $1/M in · $5/M out",
                "note": "轻量 · Anthropic 最便宜",
                "family": "claude",
                "context_window": 200_000,
                "max_output": 8_192,
                "max_tokens_default": 4_096,
            },
        ],
        key_hint="sk-ant-api03-xxx",
        signup_url="https://console.anthropic.com/settings/keys",
        note="质量最顶 · 价格最贵 · 美国 IP 友好",
    ),
    ProviderPreset(
        id="openrouter",
        name="OpenRouter (中转)",
        base_url="https://openrouter.ai/api/v1",
        provider_kind="openai",
        recommended_models=[
            {
                "id": "anthropic/claude-sonnet-4.5",
                "label": "Claude Sonnet 4.5 (走 OpenRouter)",
                "note": "无审查 · 不限国家",
                "family": "claude",
            },
            {
                "id": "google/gemini-2.5-pro",
                "label": "Gemini 2.5 Pro (走 OpenRouter)",
                "note": "Google 旗舰",
                "family": "gemini",
            },
            {
                "id": "meta-llama/llama-3.3-70b-instruct",
                "label": "Llama 3.3 70B (走 OpenRouter)",
                "note": "开源 · 便宜",
                "family": "llama",
            },
        ],
        key_hint="sk-or-v1-xxx · 64 位",
        signup_url="https://openrouter.ai/keys",
        note="300+ 模型一站通 · 国内可用 · 加价 5-10%",
    ),
    ProviderPreset(
        id="dashscope",
        name="阿里 DashScope (通义)",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider_kind="openai",
        recommended_models=[
            {
                "id": "qwen-max",
                "label": "通义千问 Max · 阿里旗舰",
                "note": "国内云 · 国内 IP 快",
                "family": "qwen",
            },
            {
                "id": "qwen-plus",
                "label": "通义千问 Plus · 中档",
                "note": "性价比",
                "family": "qwen",
            },
        ],
        key_hint="sk-xxx",
        signup_url="https://dashscope.console.aliyun.com/",
        note="国内云 · 速度快 · 不出墙",
    ),
    ProviderPreset(
        id="custom",
        name="自定义",
        base_url="",
        provider_kind="openai",
        recommended_models=[],
        key_hint="按你接的 provider 来",
        signup_url="",
        note="任意 OpenAI 兼容 base_url · 自己填",
    ),
]


def list_presets() -> list[dict]:
    """给 GET /providers 用 · 列出所有预设的可序列化字典 (不含 key)."""
    return [
        {
            "id": p.id,
            "name": p.name,
            "base_url": p.base_url,
            "provider_kind": p.provider_kind,
            "recommended_models": list(p.recommended_models),
            "key_hint": p.key_hint,
            "signup_url": p.signup_url,
            "note": p.note,
        }
        for p in PRESETS
    ]


def get_preset(preset_id: str) -> Optional[ProviderPreset]:
    """按 id 取一个预设."""
    for p in PRESETS:
        if p.id == preset_id:
            return p
    return None


def mask_api_key(key: str) -> str:
    """掩码 API key · 显示前 6 后 4 · 中间 ****.

    sk-1234567890abcdef1234567890abcdef  →  sk-123****cdef
    """
    if not key:
        return ""
    if len(key) <= 12:
        return "***"
    return key[:6] + "****" + key[-4:]


def recommended_max_tokens(model_id: str) -> int:
    """按 model_id 查推荐 max_tokens · 找不到给保守默认 8192.

    用在: 1) UI 编辑表单 max_tokens 输入框默认值
         2) chat 端点 fallback (config 没设 max_tokens 时)
    """
    if not model_id:
        return 8192
    model_lower = model_id.lower()
    for preset in PRESETS:
        for m in preset.recommended_models:
            if m.get("id", "").lower() == model_lower:
                return int(m.get("max_tokens_default") or 8192)
    # 模糊匹配 (BRO 自己加的 custom model · 按 family 推荐)
    if "deepseek" in model_lower:
        return 32_768
    if "claude-opus" in model_lower or "claude-sonnet" in model_lower:
        return 8_192
    if "claude-haiku" in model_lower:
        return 4_096
    if "gpt-5" in model_lower or "gpt-4" in model_lower:
        return 16_384
    if "kimi" in model_lower or "glm" in model_lower or "qwen" in model_lower:
        return 8_192
    if "gemini" in model_lower:
        return 8_192
    return 8_192


def context_window_for(model_id: str) -> int:
    """按 model_id 查 context_window · 给 UI 显示用 · 找不到返 0."""
    if not model_id:
        return 0
    model_lower = model_id.lower()
    for preset in PRESETS:
        for m in preset.recommended_models:
            if m.get("id", "").lower() == model_lower:
                return int(m.get("context_window") or 0)
    return 0


def max_output_for(model_id: str) -> int:
    """按 model_id 查 max_output 上限 · 给 UI 限制用户输入用."""
    if not model_id:
        return 0
    model_lower = model_id.lower()
    for preset in PRESETS:
        for m in preset.recommended_models:
            if m.get("id", "").lower() == model_lower:
                return int(m.get("max_output") or 0)
    return 0


def guess_preset_id(base_url: str, provider_kind: str = "openai") -> str:
    """根据当前 base_url 反推 preset_id · UI 显示当前选中预设."""
    if not base_url:
        return "anthropic" if provider_kind == "anthropic" else "custom"
    url_lower = base_url.lower().rstrip("/")
    if "api.deepseek.com" in url_lower:
        return "deepseek-official"
    if "aihubmix" in url_lower:
        return "aihubmix"
    if "openrouter" in url_lower:
        return "openrouter"
    if "dashscope" in url_lower:
        return "dashscope"
    if "anthropic.com" in url_lower:
        return "anthropic"
    return "custom"
