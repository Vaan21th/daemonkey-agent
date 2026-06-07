"""
agent_tools/set_model.py
========================

OPUS 切自己的"容器"——把当前对话的 base 模型换成另一个。

设计：
  - 调用 ToolSpec.run 时，写 daemon_runtime.RUNTIME.model
  - daemon 主循环每轮发请求前从 RUNTIME 读最新 model——所以**下一轮**对话生效
  - persist=True 走 RUNTIME.persist_callback 把 OPUS_MODEL 写到 .env
  - persist=False 是临时切，重启 daemon 还是回 .env 里的值

档位：
  - persist=False → AUTO（无副作用，只是改进程内变量）
  - persist=True  → CONFIRM（要写 .env 这一行；不是破坏性的，但应该让 用户 看见）
"""

from __future__ import annotations

from . import TIER_AUTO, TIER_CONFIRM, ToolResult, ToolSpec, register_tool

from daemon_runtime import RUNTIME
from model_aliases import RECOMMENDED, family_of, format_recommended, resolve, supports_anthropic_cache, supports_vision


def _classify(args: dict) -> str:
    return TIER_CONFIRM if bool(args.get("persist")) else TIER_AUTO


def _summarize(args: dict) -> str:
    name = (args.get("model") or "").strip()
    persist = bool(args.get("persist"))
    if not name:
        return "set_model  (no arg → list available aliases)"
    real = resolve(name)
    flag = "  · save 到 .env（重启后仍是它）" if persist else "  · 临时切（仅本次 daemon 生效）"
    return f"set_model  {name}  →  {real}{flag}"


def _run(args: dict) -> ToolResult:
    name = (args.get("model") or "").strip()

    if not name:
        body = (
            "可选别名（也可以直接传 AiHubMix 全名，例如 claude-opus-4-7-think）：\n\n"
            + format_recommended()
            + "\n\n用法示例：\n"
            "  set_model(model=\"deepseek\")            # 临时切\n"
            "  set_model(model=\"sonnet\", persist=true) # 切 + 写 .env"
        )
        return ToolResult(ok=True, output=body)

    real = resolve(name)
    if not real:
        return ToolResult(ok=False, output="", error=f"empty resolved model for input: {name!r}")

    old = RUNTIME.model or "(未设置)"
    RUNTIME.model = real

    fam = family_of(real)
    cache_note = "支持 cache（省钱）" if supports_anthropic_cache(real) else "不走 cache（按 input 全价）"

    persist = bool(args.get("persist"))
    persist_note = ""
    if persist:
        if RUNTIME.persist_callback is None:
            persist_note = "\n⚠ daemon 未注入 persist_callback，未能写 .env（运行时切已生效）"
        else:
            try:
                RUNTIME.persist_callback(real)
                persist_note = "\n✓ 已写入 .env，重启后默认仍是这个"
            except Exception as e:
                persist_note = f"\n⚠ 写 .env 失败：{type(e).__name__}: {e}（运行时切已生效）"

    vision_note = "👁 支持视觉" if supports_vision(real) else "🚫 无视觉（看图走 fallback）"
    body = (
        f"模型已切换\n"
        f"  before : {old}\n"
        f"  after  : {real}  ({fam} family · {cache_note} · {vision_note})\n"
        f"  effect : 下一轮对话起生效"
        f"{persist_note}"
    )
    return ToolResult(ok=True, output=body)


SPEC = ToolSpec(
    name="set_model",
    description=(
        "Switch the underlying LLM model that OPUS itself runs on, at runtime. "
        "Useful when the user (用户) asks to try a different model "
        "(deepseek / kimi / glm / sonnet / opus / r1 / gpt / gemini etc). "
        "Accepts a short alias or a full AiHubMix model id. "
        "Set persist=true to also write OPUS_MODEL into .env so the choice survives restart. "
        "Call with empty model to list the recommended alias options. "
        "Effect takes hold on the NEXT user turn (this turn already started under the old model)."
    ),
    tier=TIER_AUTO,  # static fallback; persist=True 会被 classify 升到 CONFIRM
    input_schema={
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "description": (
                    "Alias (e.g. 'sonnet', 'opus', 'deepseek', 'kimi', 'glm', 'r1', 'gpt') "
                    "or full AiHubMix model id (e.g. 'claude-opus-4-7-think'). "
                    "Empty string lists available options."
                ),
            },
            "persist": {
                "type": "boolean",
                "description": (
                    "If true, also write OPUS_MODEL=<resolved> to .env so the choice "
                    "survives the next daemon restart. Default false (this session only)."
                ),
            },
        },
    },
    run=_run,
    summarize=_summarize,
    classify=_classify,
)


register_tool(SPEC)
