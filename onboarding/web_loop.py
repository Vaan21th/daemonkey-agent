"""
onboarding/web_loop.py
======================
网页版『相遇』tool-use 循环 —— onboard.py 终端版的孪生，去掉所有 print，
把工具调用收集成结构化事件返回给 server.py，由前端渲染。

跟终端版共用 onboarding_prompt + proto_tools，行为一致。
"""

from __future__ import annotations

import json

import proto_tools
from onboarding_prompt import ONBOARDING_SYSTEM_PROMPT


def _serialize_tool_calls(tool_calls) -> list[dict]:
    return [
        {
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments or "{}",
            },
        }
        for tc in tool_calls
    ]


_EMPTY_FALLBACK = "（嗯…我这会儿有点没接上你的话，你能再说一次吗？）"


def run_turn(client, model: str, max_tokens: int, messages: list) -> tuple[str, list[dict]]:
    """调 LLM → 有 tool_calls 就执行回灌 → 直到出纯文本。

    健壮性处理（卷六十三续四补一事故）：
      - 模型某轮『既没说话也没调工具』(content 空) → **不写进历史**(防污染上下文)·
        自动重试最多 2 次·仍空则用兜底句·绝不给前端一个空气泡。
      - 模型把『话 + 工具调用』放同一条消息时·那句话也要收集进 reply·
        不能因为后面还有工具轮就把它吞掉。

    Returns:
        (reply_text, tool_events) · tool_events = [{name, ok, out}, ...]
    """
    tool_events: list[dict] = []
    texts: list[str] = []
    empty_retries = 0

    while True:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": ONBOARDING_SYSTEM_PROMPT}] + messages,
            tools=proto_tools.TOOLS,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        text = (msg.content or "").strip()
        tool_calls = list(msg.tool_calls or [])

        # 这一轮模型什么都没给 → 别写进历史·重试
        if not text and not tool_calls:
            empty_retries += 1
            if empty_retries <= 2:
                continue
            break

        assistant_entry: dict = {"role": "assistant", "content": msg.content or ""}
        if tool_calls:
            assistant_entry["tool_calls"] = _serialize_tool_calls(tool_calls)
        messages.append(assistant_entry)
        if text:
            texts.append(text)

        if not tool_calls:
            break

        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            ok, out = proto_tools.run_tool(name, args)
            tool_events.append({"name": name, "ok": ok, "out": out})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": out,
            })

    reply = "\n\n".join(texts).strip()
    if not reply:
        reply = _EMPTY_FALLBACK
        messages.append({"role": "assistant", "content": reply})
    return reply, tool_events
