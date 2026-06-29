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
#
# ⚠ 这个值在 stream=True 下是『两个 SSE chunk 之间的最大间隔』(httpx read timeout)·
# 不是整轮总时长。 thinking 模型在 reasoning 阶段可能长时间不吐 SSE chunk:
#   - DeepSeek-R1 会一字一字吐 reasoning_content (tool_loop line 775 接住) · 静默短
#   - GLM-5.x 的推理偏『后端静默思考』· 大输入 + 复杂生成时静默期轻松破 60s
# 卷七十四续 · 2026-06-23: GLM-5.2 写长 WISH (in 11.6 万 token) 反复 60s ReadTimeout 500。
#
# 老默认 60s 假设『正常推理 30-50s 完成』· 对 GLM thinking 不成立。 而当初用短 timeout
# 保『停止按钮响应快』的理由 · 已被 tool_loop 的 cancel watcher (50ms 心跳强 close stream)
# 取代 —— 停止响应不再依赖这个值。 故默认提到 300s · 给 thinking 模型足够静默窗口 ·
# 真服务端 hang 仍有 300s 兜底 + watcher 随时可中断。
# 可被环境变量覆盖 (OPUS_LLM_TIMEOUT_SEC) · 不改这里就走默认 300。
def _get_llm_timeout() -> float:
    raw = os.getenv("OPUS_LLM_TIMEOUT_SEC", "").strip()
    if not raw:
        return 300.0
    try:
        v = float(raw)
        return v if v > 0 else 300.0
    except ValueError:
        return 300.0


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


def _remove_env_kv(key: str) -> None:
    """从 .env 删掉某个 key= 行(找不到就什么都不做)。

    用于品牌前缀迁移:写新的 DAEMONKEY_xxx 时顺手清掉历史残留的 OPUS_xxx 行·
    避免 .env 里同一项两个前缀并存(并存时虽有 env_aliases 兜底·但行多了脏)。
    """
    if not ENV_PATH.exists():
        return
    raw = ENV_PATH.read_bytes()
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    pat = re.compile(rf"^\s*{re.escape(key)}\s*=")
    kept = [ln for ln in lines if not pat.match(ln)]
    if len(kept) != len(lines):
        ENV_PATH.write_bytes("\n".join(kept).encode("utf-8"))


# 对外可见的 env 前缀 · 用 DAEMONKEY_ 取代历史内部前缀(避免内部代号泄漏到用户 .env)。
PUBLIC_ENV_PREFIX = "DAEMONKEY_"


def write_public_env(key: str, value: str) -> None:
    """写"用户可见"配置到 .env——OPUS_ 前缀的一律落成 DAEMONKEY_(品牌干净)。

    - 内核几百处仍读 `os.environ["OPUS_*"]`·这里同时把内部 OPUS_ 名写进 os.environ·
      让运行中的 daemon 立刻拿到新值(不必重启)。
    - .env 文件里只留 DAEMONKEY_ 那一行·并清掉历史残留的 OPUS_ 行(老用户迁移)。
    - 非 OPUS_ 前缀(如 ANTHROPIC_API_KEY)原样写·不动。
    """
    if not key.startswith("OPUS_"):
        write_env_kv(key, value)
        os.environ[key] = value
        return
    suffix = key[len("OPUS_"):]
    pub = PUBLIC_ENV_PREFIX + suffix
    write_env_kv(pub, value)
    if pub != key:
        _remove_env_kv(key)  # 清掉旧前缀残留行
    os.environ[pub] = value
    os.environ[key] = value  # 内部恒读 OPUS_* · 即时生效


def clean_base_url(url: str) -> str:
    """去掉用户误贴的完整端点尾巴。

    OpenAI 兼容 SDK 只要 base(通常到 /v1)·会自己拼 /chat/completions。
    用户贴成 https://x/v1/chat/completions 时·SDK 会拼成 .../chat/completions/chat/completions
    → 404。这里把尾部的 /chat/completions(或 /completions)去掉·让初见/换 key 直接能连。
    """
    u = (url or "").strip().rstrip("/")
    for tail in ("/chat/completions", "/completions"):
        if u.endswith(tail):
            u = u[: -len(tail)].rstrip("/")
            break
    return u


def _friendly_provider_error(exc: Exception, base_url: str) -> str:
    """把 OpenAI SDK 异常翻成给用户看的中文提示。

    重点是 base_url 的 /v1 纠偏:很多 OpenAI 兼容中转的 base_url 该不该带 /v1
    因家而异(DeepSeek 要 /v1·有的根路径就够)·系统无法一刀切。 错配时 SDK 报 404 ·
    这里据此给出"加 /v1 / 去 /v1"的具体可粘贴地址·让用户在初见页当场试·不必去翻 .env。
    """
    name = type(exc).__name__
    msg = str(exc)
    low = f"{name} {msg}".lower()
    u = (base_url or "").rstrip("/")
    if "model" in low and ("not" in low or "exist" in low or "invalid" in low or "不存在" in msg):
        return "模型名可能不对。换成该 provider 实际支持的模型名再试。"
    if "notfound" in low or "404" in low or "not found" in low:
        if u.endswith("/v1"):
            alt = u[: -len("/v1")].rstrip("/")
            return f"接口地址 404(路径不对)。试试去掉结尾的 /v1 → {alt}"
        alt = f"{u}/v1"
        return f"接口地址 404(路径不对)。试试在结尾加上 /v1 → {alt}"
    if "authentication" in low or "401" in low or "api key" in low or "apikey" in low or "unauthorized" in low:
        return "API Key 不对或无权限(接口地址看起来是对的)。检查 Key 后重填。"
    if "permission" in low or "403" in low:
        return "无访问权限(403)。确认这个 Key 是否开通了所填模型。"
    if "timeout" in low or "timed out" in low:
        return "连接超时。检查网络 / 接口地址是否可达(国外服务可能需要代理)。"
    if "connection" in low or "connect" in low or "getaddrinfo" in low or "name resolution" in low:
        return f"连不上接口地址。确认 {u} 拼写正确、可访问。"
    return f"连接失败:{name}: {msg[:200]}"


def probe_openai(api_key: str, base_url: str, model: str = "", timeout: float = 30.0) -> tuple[bool, str]:
    """初见 / 换 key 时先试连一个 OpenAI 兼容端点。

    返回 (ok, error):ok=True 表示 key 有效且端点可达;ok=False 时 error 是给
    用户看的中文提示(含 /v1 纠偏建议)。 调用方应在 ok=False 时【不落盘】并把
    error 抛回前端·避免坏配置写进 .env 后把初见页卡死(只能手改 .env 的老坑)。
    """
    try:
        from openai import OpenAI
    except ImportError:
        return False, "openai 包未安装·请先装依赖。"
    try:
        from provider_presets import safe_max_tokens
        test_model = (model or "").strip() or "gpt-4o-mini"
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        client.chat.completions.create(
            model=test_model,
            max_tokens=safe_max_tokens(16, test_model),
            messages=[{"role": "user", "content": "ping"}],
        )
        return True, ""
    except Exception as e:  # noqa: BLE001 — 任何失败都翻成提示·不让异常冒泡
        return False, _friendly_provider_error(e, base_url)
