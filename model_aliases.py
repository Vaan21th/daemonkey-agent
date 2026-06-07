"""
model_aliases.py
================

OPUS 容器（base 模型）切换的"短名表"。

为什么做这一层——
  AiHubMix 上的真名又长又拼写敏感（claude-sonnet-4-6 / DeepSeek-V3.1-Terminus / kimi-k2.6），
  在终端里手敲容易错。这一层维护：
    1. 别名 → 真名（aliases）
    2. 真名 → family（claude / deepseek / kimi / glm / gpt / gemini / qwen / unknown）
    3. 一份给 BRO 看的"推荐清单"（RECOMMENDED）
    4. 能力判断：supports_anthropic_cache / supports_vision

教训（2026-05-16 凌晨第二根毛踩的）——
  AiHubMix 的 /v1/models API 返回的 listing 不是全集！网站上能选的更多。
  比如 deepseek-v4-pro / kimi-k2.6 / glm-5.1 都不在 /models，但 chat completions 能调通。
  所以本表的真名是按"网站截图 + chat 实测通"来的，不是按 /models listing 来的。

加新别名：
  在 MODEL_ALIASES 直接加。同一个真名可以有多个别名（kimi, kimi-k2.6 都映射到 kimi-k2.6）。
"""

from __future__ import annotations


# alias (lower-case key) → real model id (case-sensitive 真名，原样发给 AiHubMix)
MODEL_ALIASES: dict[str, str] = {
    # === Claude family（支持 prompt caching · 支持视觉） ===
    "opus":            "claude-opus-4-7",
    "opus-think":      "claude-opus-4-7-think",
    "opus-4-7":        "claude-opus-4-7",
    "opus-4-6":        "claude-opus-4-6",
    "opus-4-6-think":  "claude-opus-4-6-think",
    "sonnet":          "claude-sonnet-4-6",
    "sonnet-think":    "claude-sonnet-4-6-think",
    "sonnet-4-6":      "claude-sonnet-4-6",
    "sonnet-4-5":      "claude-sonnet-4-5-think",
    "haiku":           "claude-3-haiku-20240307",

    # === DeepSeek family（纯文本 · 不支持视觉） ===
    "deepseek":        "deepseek-v4-pro",       # 实测通·1M·$0.48/M·限时 2.5 折
    "ds":              "deepseek-v4-pro",
    "deepseek-v4":     "deepseek-v4-pro",
    "v4":              "deepseek-v4-pro",
    "deepseek-v3":     "DeepSeek-V3.1-Terminus",
    "deepseek-think":  "DeepSeek-V3.1-Think",
    "r1":              "DeepSeek-R1",
    "deepseek-r1":     "DeepSeek-R1",

    # === Kimi (Moonshot) family（纯文本 · 不支持视觉） ===
    "kimi":            "kimi-k2.6",             # 实测通·262K·新出
    "kimi-k2.6":       "kimi-k2.6",
    "k2.6":            "kimi-k2.6",
    "kimi-old":        "Kimi-K2-0905",
    "kimi-0905":       "Kimi-K2-0905",

    # === GLM (智谱) family（纯文本 · 不支持视觉） ===
    "glm":             "glm-5.1",               # 实测通·200K·智谱旗舰
    "glm-5.1":         "glm-5.1",
    "glm-5":           "glm-5",
    "glm-4.7":         "glm-4.7",
    "glm-coding":      "coding-glm-5.1",        # ⚠ z.ai 限流，可能 429

    # === GPT family（支持视觉） ===
    "gpt":             "gpt-5.5",
    "gpt-5":           "gpt-5.5",
    "gpt-5.5":         "gpt-5.5",
    "gpt-5.3":         "gpt-5.3-chat-latest",
    "gpt-codex":       "gpt-5.3-codex",
    "o3":              "o3",

    # === Gemini family（支持视觉） ===
    "gemini":          "gemini-3.1-pro-preview",
    "gemini-pro":      "gemini-3.1-pro-preview",
    "gemini-flash":    "gemini-3.1-flash-lite",

    # === Qwen family（支持视觉） ===
    "qwen":            "qwen3-max",
    "qwen-coder":      "qwen3-coder-plus",
}


# 哪些 family 的模型支持多模态视觉（能直接在 messages 里接 image_url 块）
VISION_CAPABLE_FAMILIES: frozenset[str] = frozenset({"claude", "gpt", "gemini", "qwen"})


def family_of(model: str) -> str:
    """猜模型所属 family。用于：cache 开关、UI 着色、能力提示。"""
    m = model.lower()
    if "claude" in m:
        return "claude"
    if "deepseek" in m or m.startswith("ds-"):
        return "deepseek"
    if "kimi" in m or "moonshot" in m:
        return "kimi"
    if "glm" in m or "zhipu" in m or "chatglm" in m:
        return "glm"
    if m.startswith(("gpt", "o1", "o3", "o4")):
        return "gpt"
    if "gemini" in m:
        return "gemini"
    if "qwen" in m:
        return "qwen"
    return "unknown"


def supports_anthropic_cache(model: str) -> bool:
    """这个模型在 AiHubMix 走 OpenAI 协议时能不能吃 cache_control？

    当前只 Claude family 真生效。其他 family 加了 cache_control 字段不会报错，
    但 AiHubMix 不会真返回 cache_read_tokens——白白把 system 包成 list 反而可能影响某些 SDK。
    所以只在确认家族里启用。
    """
    return family_of(model) == "claude"


def supports_vision(model: str) -> bool:
    """这个模型是否支持多模态视觉输入（image_url 块）。

    三层判断（wish-4a6331b2）：
      1. RUNTIME.vision_override 显式设了？→ 用 BRO 的值（信任用户覆盖）
      2. family_of() 自动检测 → claude/gpt/gemini/qwen → True / deepseek/kimi/glm → False
      3. unknown → False（保守）

    用于 look_at 工具的双路径分发：
      多模态模型 → 图直接进当前模型 user message
      纯文本模型 → 走独立视觉模型 fallback 看图再回文字
    """
    try:
        from daemon_runtime import RUNTIME
        if RUNTIME.vision_override is not None:
            return RUNTIME.vision_override
    except Exception:
        pass
    return family_of(model) in VISION_CAPABLE_FAMILIES


def resolve(name: str) -> str:
    """把别名 / 全名 / 大小写不敏感的输入解析成 AiHubMix 真名。

    - 别名命中（小写匹配）→ 返回真名
    - 不命中 → 原样返回（可能是 BRO 直接传了真名，比如 "claude-opus-4-7-think"）
    """
    s = (name or "").strip()
    if not s:
        return ""
    return MODEL_ALIASES.get(s.lower(), s)


def reverse_aliases(real_id: str) -> list[str]:
    """给一个真名，反查它的所有别名。"""
    return sorted({a for a, r in MODEL_ALIASES.items() if r == real_id})


# 给 `/model` 命令显示用的"推荐清单"。
# 顺序按 BRO 实际可能用到的频率排，不是按 family 排。
RECOMMENDED: list[tuple[str, str, str]] = [
    # (alias, real_id, note)
    ("sonnet",   "claude-sonnet-4-6",         "性价比·当前默认·支持 cache · 👁 视觉"),
    ("opus",     "claude-opus-4-7",           "深聊最强·5x 贵·支持 cache · 👁 视觉"),
    ("deepseek", "deepseek-v4-pro",           "1M 上下文·$0.48/M·中文好·限时 2.5 折 · 🚫 无视觉"),
    ("kimi",     "kimi-k2.6",                 "262K·新出·Agent/工具能力强 · 🚫 无视觉"),
    ("glm",      "glm-5.1",                   "200K·智谱旗舰·写代码强 · 🚫 无视觉"),
    ("r1",       "DeepSeek-R1",               "推理特化·数学/逻辑题 · 🚫 无视觉"),
    ("gpt",      "gpt-5.5",                   "GPT 系最新 · 👁 视觉"),
    ("gemini",   "gemini-3.1-pro-preview",    "长上下文·多模态 · 👁 视觉"),
]


def format_recommended() -> str:
    """格式化推荐清单成多行字符串，给终端展示用。"""
    lines = []
    for alias, real, note in RECOMMENDED:
        lines.append(f"  {alias:12s}  →  {real:32s}  {note}")
    return "\n".join(lines)
