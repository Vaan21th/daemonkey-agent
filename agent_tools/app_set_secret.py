"""agent_tools/app_set_secret.py
=================================

 K stage 2c++ · wish-96ee1b52 · OPUS 给一个 app 安全存一个 KEY/secret

**为什么有这个工具**:
    daemon OPUS 装 API 应用 (例如 GPT Image / ElevenLabs / 第三方 LLM) 时需要
    存 sk-xxx 这种 KEY · 之前唯一的写处是 app json (data/workshop/apps/*.json) ·
    导致 KEY 进 git history / session jsonl / system_prompt = 三重暴露。
    这个工具让 KEY 落到 data/workshop/secrets/<app>.json (gitignored) ·
    LLM 写 system_prompt / shell_exec command 时只用 placeholder
    `${secret:<app_id>:<secret_name>}`。

**调用时机**:
    - 用户 给 OPUS 一个 KEY 让他装 API 应用时
    - OPUS 在 create_app 之后 · 准备写 system_prompt 之前
    - **不要写 KEY 进 app json · 也不要写 KEY 进 system_prompt** · 永远走这里

**KEY 真值进 messages 历史的 trade-off**:
    调这个工具时 args.value 必然进 LLM messages · 真值短暂在历史里出现一次。
    这是当前最优 · 因为：
      - 真值不会落进 git (secrets/ 在 gitignore)
      - 真值不会落进 app json (永久暴露)
      - 真值不会落进 OpenAI 调用 (system_prompt 只放 placeholder)
    彻底防 messages 污染需要 用户 走 web UI 旁路输入 · 那是 future TODO · 现在没。
    用户 在外面贴 KEY 给 OPUS 之前心里要有数。

**tier**:
    TIER_CONFIRM —— 写 KEY 是敏感操作 · 用户 看到摘要后 ✓ 才执行
"""

from __future__ import annotations

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    app_id = args.get("app_id") or "(未指定)"
    name = args.get("secret_name") or "(未指定)"
    val = args.get("value") or ""
    masked = val[:4] + "***" if len(val) > 8 else "***"
    return f"给 app `{app_id}` 存一个 secret · 字段 `{name}` · 值 `{masked}`"


def _run(args: dict) -> ToolResult:
    from workers import app_secrets

    app_id = (args.get("app_id") or "").strip()
    secret_name = (args.get("secret_name") or "").strip()
    value = args.get("value")

    if not app_id:
        return ToolResult(ok=False, output="", error="app_id 必填 (data/workshop/apps/<id>.json 的 id)")
    if not secret_name:
        return ToolResult(ok=False, output="", error="secret_name 必填 (例如 'api_key')")
    if not isinstance(value, str) or not value:
        return ToolResult(ok=False, output="", error="value 必填且非空")

    try:
        r = app_secrets.set_secret(app_id, secret_name, value)
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"set_secret 失败: {e}")

    masked = value[:4] + "***" if len(value) > 8 else "***"
    lines = [
        f"# ✓ secret 已存 · `{r['app_id']}` :: `{r['secret_name']}`",
        f"  - 字段名: {r['secret_name']}",
        f"  - 值: {masked} (长度 {len(value)})",
        f"  - 落点: data/workshop/secrets/{r['app_id']}.json (gitignored)",
        "",
        "**接下来调用方式 · 写 system_prompt / shell_exec command 时**:",
        "",
        "```",
        f"  {r['placeholder']}",
        "```",
        "",
        "  - daemon 在 shell_exec 启动子进程前会自动 resolve 成真值 (走 env 注入)",
        "  - 子进程 stdout 出现真值会自动 redact 回 placeholder · 不污染 LLM context",
        "  - **不要把真值复制粘贴进 app json / system_prompt** · 一律用 placeholder",
    ]
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="app_set_secret",
    description=(
        "给 app 存 KEY/token，真值落 gitignored secrets。BRO 给密钥时第一刀调本工具。之后只用 ${secret:<app_id>:<name>}。禁止写进 app json / prompt / md。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "app_id": {
                "type": "string",
                "description": "目标 app 的 id · 例如 'app-35ed6c86' · 必须是已存在的 app",
                "minLength": 4,
                "maxLength": 64,
            },
            "secret_name": {
                "type": "string",
                "description": "字段名 · 例如 'api_key' / 'access_token' · placeholder 用此名引用",
                "minLength": 1,
                "maxLength": 64,
            },
            "value": {
                "type": "string",
                "description": "真值 · 例如 sk-xxx · 直接写到磁盘 secrets/<app>.json (gitignored)",
                "minLength": 1,
            },
        },
        "required": ["app_id", "secret_name", "value"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
