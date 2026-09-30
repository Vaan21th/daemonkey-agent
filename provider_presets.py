"""
provider_presets.py
===================

卷三十六 · 多 LLM 预设管理

为啥要：
  - 之前换 provider 要改 .env 重启 daemon · BRO 很烦
  - aihubmix 欠费瞬间无感·这种事不该再发生
  - Daemonkey 设计目标里有"开源后任何人下载都能跑"·得让用户在 UI 里选 provider

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
    pricing_url: str = ""  # wish-bec4f3b9 · 官方定价页 (查价按钮用 · 空 = 无公开价走手填)
    note: str = ""


# LLM provider 预设 · 按推荐度排序 (DeepSeek 官方第一 · 实测便宜 30 倍 · 智谱官方第二)
PRESETS: list[ProviderPreset] = [
    ProviderPreset(
        id="deepseek-official",
        name="DeepSeek 官方",
        base_url="https://api.deepseek.com/v1",
        provider_kind="openai",
        recommended_models=[
            {
                "id": "deepseek-v4-flash",
                "label": "DeepSeek V4 Flash · $0.14/M in · $0.28/M out · cache hit $0.0028/M",
                "note": "轻量 · 更便宜 · 默认推荐 (2026-08-02 BRO 拍板)",
                "family": "deepseek",
                "context_window": 1_000_000,
                "max_output": 384_000,
                "max_tokens_default": 16_384,
            },
            {
                "id": "deepseek-v4-pro",
                "label": "DeepSeek V4 Pro · $0.435/M in · $0.87/M out · cache hit $0.003625/M",
                "note": "旗舰 · 1M context · 支持 thinking · 要求高时换",
                "family": "deepseek",
                "context_window": 1_000_000,
                "max_output": 384_000,
                "max_tokens_default": 32_768,
            },
        ],
        key_hint="sk-xxx · 32 位左右",
        signup_url="https://platform.deepseek.com/api_keys",
        pricing_url="https://api-docs.deepseek.com/quick_start/pricing",  # wish-bec4f3b9 · 官方定价页
        note="实测便宜 aihubmix 30 倍 · 强烈推荐",
    ),
    ProviderPreset(
        id="zhipu-official",
        name="智谱 AI 官方 (BigModel)",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        provider_kind="openai",
        recommended_models=[
            {
                "id": "glm-5.2",
                "label": "GLM-5.2 · 智谱旗舰 · 带 thinking · 后端自带缓存",
                "note": "200K · 推理强 · 实测缓存命中~99% 极省 · thinking 模型记得给够 max_tokens",
                "family": "glm",
                "context_window": 200_000,
                "max_output": 16_384,
                "max_tokens_default": 16_384,
            },
            {
                "id": "glm-5v-turbo",
                "label": "GLM-5V-Turbo · 多模态视觉",
                "note": "看图理解 · 多模态 · 实测视觉准",
                "family": "glm",
                "context_window": 16_384,
                "max_output": 8_192,
                "max_tokens_default": 8_192,
                "vision": True,
            },
        ],
        key_hint="智谱开放平台 API Key · 形如 xxxxx.yyyyy",
        signup_url="https://open.bigmodel.cn/usercenter/apikeys",
        pricing_url="https://open.bigmodel.cn/pricing",  # wish-bec4f3b9
        note="官方直连 · GLM 全系 · 后端原生上下文缓存 (实测 glm-5.2 命中 99%)",
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
        pricing_url="",  # wish-bec4f3b9 · 中转聚合渠道无统一价目 · 走手填
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
        pricing_url="https://www.anthropic.com/pricing",  # wish-bec4f3b9
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
        pricing_url="https://openrouter.ai/models",  # wish-bec4f3b9 · 模型页有各家价
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
        pricing_url="https://help.aliyun.com/zh/model-studio/models",  # wish-bec4f3b9
        note="国内云 · 速度快 · 不出墙",
    ),
    ProviderPreset(
        id="lm-studio",
        name="LM Studio (本机本地模型)",
        base_url="http://localhost:1234/v1",
        provider_kind="openai",
        recommended_models=[],  # 本机模型动态发现 · UI 点「拉取本机模型」自动填 (wish-cef00196)
        key_hint="本机模型不需要 key · 占位即可",
        signup_url="",
        note="用 LM Studio 跑本机模型 (Qwen 8B 等) · 零成本 · 断网可用 · 数据不出本机。先在 LM Studio Developer 页启动本地服务器 (默认 1234 端口) · 再点「拉取本机模型」自动发现已加载的模型。",
    ),
    ProviderPreset(
        id="llama-prism",
        name="本机 llama.cpp (自定义量化 · fork)",
        base_url="http://127.0.0.1:18080/v1",
        provider_kind="openai",
        recommended_models=[],  # 动态发现 · 点「拉取本机模型」自动填 (同 lm-studio)
        key_hint="本机模型不需要 key · 占位即可",
        signup_url="",
        note="本机用 llama-server 跑自定义/非标准量化的 GGUF (如 ternary 三值模型) · 零成本 · 断网可用 · 数据不出本机。官方 llama.cpp 拒载这类格式 · 需用作者 fork 的 llama-server · 默认端口 18080 · 起好服务后点「拉取本机模型」自动发现。",
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
            "pricing_url": p.pricing_url,  # wish-bec4f3b9 · 查价按钮用
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

    0.9.x: 改走 _recommended_model 统一入口 (精确 id / 别名 / org 前缀 / 最长前缀都生效)。
    修的是两张表打架 —— 原来这里只认精确 id · deepseek-flash 落空后掉进下面 family 兜底
    拿 32768 · 比它的规范名 deepseek-v4-flash (16384) 多一倍 · 同一个模型两个答案。
    family 兜底保留 · 只作"认不出具体型号"时的保守值。
    """
    if not model_id:
        return 8192
    m = _recommended_model(model_id)
    if m:
        return int(m.get("max_tokens_default") or 8192)
    model_lower = model_id.lower()
    # 认不出具体型号 → family 级保守兜底
    if "deepseek" in model_lower:
        return 32_768
    if "claude-opus" in model_lower or "claude-sonnet" in model_lower:
        return 8_192
    if "claude-haiku" in model_lower:
        return 4_096
    if "gpt-5" in model_lower or "gpt-4" in model_lower:
        return 16_384
    if "glm" in model_lower:
        return 16_384  # GLM 5.x 偏 thinking · reasoning 吃 token · 未注册型号也给足 buffer
    if "kimi" in model_lower or "qwen" in model_lower:
        return 8_192
    if "gemini" in model_lower:
        return 8_192
    return 8_192


# ── thinking 模型 max_tokens 兜底 · 单一真相源 (卷七十四续 · 2026-06-23 · BRO 全扫拍板) ──
# 病根: thinking 模型 (GLM-5.x / DeepSeek-V4 / R1 / o 系列 / *-think) 把 max_tokens 当成
#   『reasoning + 可见输出』的总预算·reasoning 先吃。 worker 里写死的小 max_tokens
#   (如 onboarding 2000 / wechat 2048) 会被 reasoning 吃光 → 回复空白/截断。
# 根治: 所有写死 max_tokens 的调用点都过 safe_max_tokens()·别再裸传小常量。
# 值参考业界 (卷七十四续三十 · 2026-06-24): Claude Code 默认 MAX_OUTPUT=32K·且 thinking
#   预算默认就吃几万 token·8192 对 reasoning 模型偏保守 → 抬到 16384 (reasoning 吃一半仍剩 8K)。
THINKING_MAX_TOKENS_FLOOR = 16384


def is_thinking_model(model_id: str) -> bool:
    """是不是 reasoning/thinking 模型 (max_tokens 含 reasoning 预算·写死小值会被吃光)。"""
    m = (model_id or "").lower().strip()
    if not m:
        return False
    m = _MODEL_ALIASES.get(m, m)   # 别名归一 · 手填的 deepseek-flash 也要认得
    if "glm-5" in m or "glm-4.7" in m or "coding-glm" in m:   # GLM 5.x / 4.7 全系带 thinking
        return True
    if "deepseek-r" in m or "reasoner" in m or "deepseek-v4" in m:  # R1/reasoner · V4 起带 thinking(V3 非)
        return True
    if "think" in m or "qwq" in m or "reasoning" in m:         # claude *-think / *-Think / qwq
        return True
    if m.split("-")[0] in ("o1", "o3", "o4"):                  # OpenAI o1/o3/o4 reasoning
        return True
    return False


# ── 关思考能力声明表 · 单一真相源 (wish-33624071 · 2026-09-14) ──────────────
# 病根: 思考开关「关」原先只对 DeepSeek/GLM 下发 extra_body.thinking.disabled·
#   其他厂商在 tool_loop._apply_openai_reasoning 里静默跳过 → 本地模型
#   (LM Studio 跑 Qwen3) 点「关·直接答」仍在思考·用户以为开关坏了。
# 实测 (2026-09-14 · LM Studio :1234 · qwen3-8b-heretic):
#   ① 基线                     reasoning=559字 · completion_tokens=369 · 17.7s
#   ② system 里加 /no_think     reasoning=  0字 · completion_tokens= 42 ·  2.4s
#        → 省 88.6% · 快 7.4 倍 · content 一字不少
#   ③ chat_template_kwargs.enable_thinking=false → 572字/379tok 完全无效 (LM Studio 不透传)
# 结论: 真关思考按【模型家族】分三类·不按厂商穷举:
#   api_param   有 API 开关      → 发请求参数 (DeepSeek / GLM)
#   soft_prompt 有 prompt 软开关 → system 塞控制词 (Qwen3 系·训练时教过 /no_think)
#   none        两者都没有      → 真关不掉·UI 如实标注
#              (o1/o3 类·thinking 是模型定义的一部分·API 上最狠只能降 effort)
THINK_OFF_API_PARAM = "api_param"
THINK_OFF_SOFT_PROMPT = "soft_prompt"
THINK_OFF_CHAT_TEMPLATE = "chat_template_kwargs"  # 请求体开关 · 需后端透传 chat_template_kwargs
THINK_OFF_NONE = "none"
THINK_OFF_SOFT_TOKEN = "/no_think"


def resolve_think_off(model_id: str, base_url: str = "") -> tuple[str, str]:
    """查「这个模型怎么真关思考」· 返 (mode, token)。

    mode ∈ api_param / soft_prompt / none · token 仅 soft_prompt 时非空。
    加新厂商 = 往下面加一行判断·不是去改 _apply_openai_reasoning 的控制流。
    UI 的 /models 也读这个·所以它是「能不能关」的单一真相源。
    """
    m = (model_id or "").lower()
    b = (base_url or "").lower()
    if not m:
        return THINK_OFF_NONE, ""
    # ① 有 API 开关的 (tool_loop 里已实现的方言)
    if "deepseek" in m:
        return THINK_OFF_API_PARAM, ""
    if m.startswith("glm") or "glm-" in m:
        return THINK_OFF_API_PARAM, ""
    if "bigmodel.cn" in b:          # 智谱官方 base_url 下的自定义模型名
        return THINK_OFF_API_PARAM, ""
    # ①.5 走 chat template 开关的 (wish-acf6e762) · 请求体 chat_template_kwargs.enable_thinking=false
    #   实测 ternary-bonsai-2-27b: 基线思考 112 字/43 tok → 关后 0 字/2 tok (省 95%)
    #   ⚠ 只有能【透传】chat_template_kwargs 的后端吃这条 (llama.cpp 原生 server 可以 ·
    #     LM Studio 会吃掉该参数 → 实测无效) · 故按模型粒度声明 (playbook 纪律)
    if "bonsai" in m:
        return THINK_OFF_CHAT_TEMPLATE, ""
    # ② 有 prompt 软开关的 (实测有效·见上)
    if "qwen" in m or "qwq" in m:
        return THINK_OFF_SOFT_PROMPT, THINK_OFF_SOFT_TOKEN
    # ③ 显式关不掉的推理模型
    if m.split("-")[0].split(".")[0] in ("o1", "o3", "o4"):
        return THINK_OFF_NONE, ""
    # 其余 (claude / gpt-5 / kimi / gemini / llama / 本机未知模型): 没有可靠通路·
    # 如实报 none (UI 标灰 + 说明)·不假装能关。
    return THINK_OFF_NONE, ""


# ── 推理强度 · 标准档位 + 每模型映射 (wish-4fd607c5 · 2026-09-15 BRO 二次拍板 v2) ──
# v1 病根: 按模型【裁剪】UI 档位 (dsflash 只摆 3 档) → 看着像专为 DeepSeek 定制·不泛用。
# v2 设计 (BRO: "做成 OpenAI 格式的标准档位·泛用性·无非说明提一嘴"):
#   UI 永远摆【标准档位全集】(跨厂商同一套名字) · 每模型自己的「服务端接受集合 +
#   默认 + 人话说明(映射规则/建议)」放这张表; 发送端把选中的标准档【就近映射】成该
#   模型真接受的档 (map_effort_level) → UI 泛用 · 又不会 400 · 也不用改前端。
# 官方抄录 (api-docs.deepseek.com · 2026-09-15):
#   DeepSeek reasoning_effort ∈ none/low/high/max · 默认 high
#   别名映射: minimal→low · medium→high · xhigh→high · max→max · ultra→max
# 纪律: 认不出的模型 → 保守 (low/medium/high) + default 空 (= 不发送·零回归);
#   证实【忽略该参数】的家族 (GLM) 与本机端点 → 空集 (UI 整行标灰·如实说原因)。
EFFORT_STANDARD_LEVELS: tuple[str, ...] = ("minimal", "low", "medium", "high", "max")
EFFORT_LEVELS_CONSERVATIVE: tuple[str, ...] = ("low", "medium", "high")


def resolve_effort_profile(model_id: str, base_url: str = "") -> tuple[tuple[str, ...], str, str]:
    """查「这个模型服务端接受的推理强度档位」· 返 (supported, default, note)。

    supported 空 = 该模型不吃这个参数 (UI 整行标灰·note 说明原因)。
    default 空 = 默认档未知 (UI 默认项 = 不发送)。
    note = 给用户看的一行说明 (映射规则 + 建议试哪档)。
    加新厂商 = 加一行判断·不是去改 tool_loop 或前端。
    """
    m = (model_id or "").lower()
    b = (base_url or "").lower()
    if not m:
        return EFFORT_LEVELS_CONSERVATIVE, "", "未实测模型 · 不选则不发送（选了按保守三档发 · 报错请改回默认）"
    # ① DeepSeek (官方 / 硅基 / 各种中转的 deepseek 名)
    if "deepseek" in m:
        return (("low", "high", "max"), "high",
                "DeepSeek 映射：最小→低 · 中→高 · 极高=最深。建议：日常用 低/中，难题试 极高")
    # ② Kimi K3 · 始终思考 · 官方默认 max
    if "kimi-k3" in m:
        return (("low", "high", "max"), "max",
                "该模型始终思考 · 默认极高。建议：想省 token 试 低")
    # ③ 证实忽略该参数的家族 (智谱 GLM 静默忽略 reasoning_effort) → 如实标灰
    if m.startswith("glm") or "glm-" in m or "bigmodel.cn" in b:
        return (), "", "该模型忽略推理强度参数 · 用「思考模式」控制即可"
    # ④ 本机端点 (LM Studio / Ollama / 自建) · 没有统一的强度参数 → 如实标灰
    if any(h in b for h in ("127.0.0.1", "localhost", "0.0.0.0", "[::1]")):
        return (), "", "本机模型没有统一的强度参数 · 用「思考模式」控制就好"
    # ⑤ GPT-5 / o 系 · OpenAI 标准档 (无 max)
    fam0 = m.split("-")[0].split(".")[0]
    if "gpt-5" in m or fam0 in ("o1", "o3", "o4"):
        return (("minimal", "low", "medium", "high"), "medium",
                "OpenAI 标准档（无「极高」· 选它会就近用 高）")
    # ⑥ xAI Grok
    if m.startswith("grok"):
        return (("low", "high"), "high", "Grok 支持 低/高（其它档就近映射）")
    # ⑦ 其余未知 → 保守三档
    return EFFORT_LEVELS_CONSERVATIVE, "", "未知模型 · 保守发送 低/中/高"


def map_effort_level(level: str, model_id: str, base_url: str = "") -> Optional[str]:
    """用户选的标准档 → 该模型服务端真接受的档 (就近映射·先深后浅) · None = 不发。

    例: DeepSeek 上 medium → high (官方映射同向) · 最小 → low;
        GPT-5 上 max → high (无「极高」) · Grok 上 medium → high。
    """
    lv = (level or "").strip().lower()
    if not lv or lv not in EFFORT_STANDARD_LEVELS:
        return None                       # 不认识的档 → 保守不发
    supported, _default, _note = resolve_effort_profile(model_id, base_url)
    if not supported:
        return None                       # 该模型不吃这个参数
    if lv in supported:
        return lv
    i = EFFORT_STANDARD_LEVELS.index(lv)
    for j in range(i + 1, len(EFFORT_STANDARD_LEVELS)):   # 先向深找 (要更深时别缩水)
        if EFFORT_STANDARD_LEVELS[j] in supported:
            return EFFORT_STANDARD_LEVELS[j]
    for j in range(i - 1, -1, -1):                        # 再向浅找
        if EFFORT_STANDARD_LEVELS[j] in supported:
            return EFFORT_STANDARD_LEVELS[j]
    return None


def safe_max_tokens(requested, model_id: str) -> int:
    """写死/请求的 max_tokens 兜底:thinking 模型抬到安全下限·普通模型保持原值不浪费。

    **所有写死 max_tokens 的调用点都该过这个**·别再裸传小常量 (卷七十四续 · 2026-06-23)。
    抬升后再按模型 max_output 封顶 (卷七十四续三十)·防 floor 顶穿小输出模型 (如 glm-5v-turbo 上限 8192)。
    """
    try:
        req = int(requested) if requested else 0
    except (TypeError, ValueError):
        req = 0
    if req <= 0:
        req = THINKING_MAX_TOKENS_FLOOR
    if is_thinking_model(model_id) and req < THINKING_MAX_TOKENS_FLOOR:
        req = THINKING_MAX_TOKENS_FLOOR
    cap = max_output_for(model_id)
    if cap and req > cap:
        req = cap
    return req


# 配置里手填的别名 → 规范 id (provider_presets 表里 recommended_models.id)
# 只做名字归一 · 不改任何匹配语义; 认不出的模型照旧返回 None (下游各自兜底)
_MODEL_ALIASES = {
    "deepseek-flash": "deepseek-v4-flash",
}


def _recommended_model(model_id: str) -> Optional[dict]:
    """精确 id 优先 · 否则最长前缀 (flash-vision-exp → deepseek-v4-flash)。

    0.9.x 别名归一: 依次试 原样 → 别名映射 → 去 org 前缀的尾巴 → 尾巴的别名。
    让手填的 `deepseek-flash` / `deepseek-ai/DeepSeek-V4-Flash` 也能查到规格,
    同时不影响表里本就带 org 的 id (qwen/qwen3-vl-4b)。
    """
    raw = (model_id or "").strip().lower()
    if not raw:
        return None
    tail = raw.rsplit("/", 1)[-1] if "/" in raw else ""
    keys = []
    for k in (raw, _MODEL_ALIASES.get(raw), tail, _MODEL_ALIASES.get(tail)):
        if k and k not in keys:
            keys.append(k)
    best: Optional[dict] = None
    best_len = -1
    for key in keys:
        for preset in PRESETS:
            for m in preset.recommended_models:
                mid = (m.get("id") or "").lower()
                if not mid:
                    continue
                if key == mid:
                    return m
                if key.startswith(mid + "-") or key.startswith(mid + "."):
                    if len(mid) > best_len:
                        best = m
                        best_len = len(mid)
    return best


def context_window_for(model_id: str) -> int:
    """按 model_id 查 context_window · 给 UI 显示用 · 找不到返 0."""
    m = _recommended_model(model_id)
    return int(m.get("context_window") or 0) if m else 0


def max_output_for(model_id: str) -> int:
    """按 model_id 查 max_output 上限 · 给 UI 限制用户输入用."""
    m = _recommended_model(model_id)
    return int(m.get("max_output") or 0) if m else 0


def default_max_tokens_for(model_id: str) -> int:
    """按 model_id 查"正常一轮"的推荐输出额度 (max_tokens_default) · 找不到返 0。

    后台 turn (定时任务/未来需长输出的自驱任务) 该用这个·而不是 proactive 搭话的小常量——
    搭话一句话 2048 够·但生成完整文档/报告 2048 会被截断 (卷七十四续二十九事故)。
    """
    m = _recommended_model(model_id)
    return int(m.get("max_tokens_default") or 0) if m else 0


def guess_preset_id(base_url: str, provider_kind: str = "openai") -> str:
    """根据当前 base_url 反推 preset_id · UI 显示当前选中预设."""
    if not base_url:
        return "anthropic" if provider_kind == "anthropic" else "custom"
    url_lower = base_url.lower().rstrip("/")
    if "api.deepseek.com" in url_lower:
        return "deepseek-official"
    if "bigmodel.cn" in url_lower:
        return "zhipu-official"
    if "aihubmix" in url_lower:
        return "aihubmix"
    if "openrouter" in url_lower:
        return "openrouter"
    if "dashscope" in url_lower:
        return "dashscope"
    if "anthropic.com" in url_lower:
        return "anthropic"
    return "custom"
