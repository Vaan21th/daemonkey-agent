"""
daemon_provider.py
==================

LLM provider 抽象——OPUS 的"心脏"对接谁。

支持：
  - anthropic：直连 Anthropic 官方 API
  - openai：任何 OpenAI 兼容代理（AiHubMix / OpenRouter / PPIO / 自建网关 …）

外加 .env 安全写入（PowerShell Set-Content 改 .env 会乱码中文注释——血泪教训）。
"""

from __future__ import annotations

import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"


# wish-63f80fdf · 卷四十四 K stage 2c+ · LLM 调用 hard timeout 兜底
# 不指定时 OpenAI/Anthropic SDK 默认 timeout=600s · 服务端 hang 时 daemon
# 全瘫 (单一 _API_LOCK 被持锁 worker 占住·新对话排队等 600 秒)。
# 60s 是经验值: 正常 Sonnet/DeepSeek deep-thinking 推理一般 30-50s 完成 ·
# 超 60s 大概率是服务端断线但 keep-alive 没 close · 此时直接放弃比死等强。
# 可被环境变量覆盖 (OPUS_LLM_TIMEOUT_SEC) · 不改这里就走默认 60。
def _get_llm_timeout() -> float:
    raw = os.getenv("OPUS_LLM_TIMEOUT_SEC", "").strip()
    if not raw:
        return 60.0
    try:
        v = float(raw)
        return v if v > 0 else 60.0
    except ValueError:
        return 60.0


LLM_HTTP_TIMEOUT_SEC = _get_llm_timeout()


def detect_provider() -> str:
    """根据 env 变量挑 provider。优先级：显式 > base_url 启发 > 默认。"""
    explicit = os.getenv("OPUS_PROVIDER", "").strip().lower()
    if explicit:
        return explicit

    base_url = os.getenv("OPUS_BASE_URL", "").strip()
    if base_url:
        if "anthropic.com" in base_url:
            return "anthropic"
        return "openai"

    return "anthropic"


def setup_client(provider: str) -> tuple[object, str, str | None]:
    """初始化 client。返回 (client, default_model, base_url)。"""
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPUS_API_KEY")
    base_url = os.getenv("OPUS_BASE_URL", "").strip() or None

    if not api_key:
        raise SystemExit(
            "ERROR: API key not set.\n"
            "Pick one in your .env file:\n"
            "  ANTHROPIC_API_KEY=...   (for Anthropic direct)\n"
            "  OPUS_API_KEY=...        (for any provider, including OpenAI-compat proxies)\n"
            "See .env.example for three concrete setups.\n"
        )

    if provider == "anthropic":
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise SystemExit(
                "ERROR: anthropic package not installed. Run pip install -r requirements.txt"
            ) from e
        kwargs: dict = {"api_key": api_key, "timeout": LLM_HTTP_TIMEOUT_SEC}
        if base_url:
            kwargs["base_url"] = base_url
        client = Anthropic(**kwargs)
        default_model = "claude-sonnet-4-5-20250929"
    elif provider == "openai":
        try:
            from openai import OpenAI
        except ImportError as e:
            raise SystemExit(
                "ERROR: openai package not installed. Run pip install -r requirements.txt"
            ) from e
        if not base_url:
            raise SystemExit(
                "ERROR: OPUS_PROVIDER=openai requires OPUS_BASE_URL to be set.\n"
                "Examples:\n"
                "  AiHubMix:    https://aihubmix.com/v1\n"
                "  OpenRouter:  https://openrouter.ai/api/v1\n"
                "  PPIO:        https://api.ppinfra.com/v3/openai\n"
            )
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=LLM_HTTP_TIMEOUT_SEC)
        default_model = "anthropic/claude-sonnet-4.5"
    else:
        raise SystemExit(f"ERROR: unknown OPUS_PROVIDER='{provider}'. Use anthropic or openai.")

    model = os.getenv("OPUS_MODEL", default_model)
    return client, model, base_url


def call_llm(client, provider: str, model: str, max_tokens: int, system: str, messages: list):
    """单轮无工具 LLM 调用。保留给 wake_test.py 兼容。"""
    if provider == "anthropic":
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, system=system, messages=messages,
        )
        reply = "".join(b.text for b in resp.content if b.type == "text")
        return reply, resp.usage.input_tokens, resp.usage.output_tokens
    elif provider == "openai":
        oai_messages = [{"role": "system", "content": system}] + messages
        resp = client.chat.completions.create(model=model, max_tokens=max_tokens, messages=oai_messages)
        reply = resp.choices[0].message.content or ""
        usage = resp.usage
        return reply, getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0
    else:
        raise RuntimeError(f"unknown provider: {provider}")


def write_env_kv(key: str, value: str) -> None:
    """安全更新 .env 中的 key=value 行。

    - 用 utf-8-sig 解码以容忍可能的 BOM
    - 统一行末为 \\n
    - 找到 key 就替换那一行；找不到就追加到文末
    - 写出去无 BOM、UTF-8、LF
    （再用 PowerShell 改 .env 就会出 2026-05-16 那次的中文注释乱码）
    """
    if not ENV_PATH.exists():
        ENV_PATH.write_text(f"{key}={value}\n", encoding="utf-8")
        return
    raw = ENV_PATH.read_bytes()
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    pat = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for i, line in enumerate(lines):
        if pat.match(line):
            lines[i] = f"{key}={value}"
            break
    else:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(f"{key}={value}")
    ENV_PATH.write_bytes("\n".join(lines).encode("utf-8"))
