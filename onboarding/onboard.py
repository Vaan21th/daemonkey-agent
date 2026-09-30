"""
onboarding/onboard.py
=====================
最小可跑的 Daemonkey "相遇" onboarding 原型。

目的：先验证体验，再搬骨架。可以先在终端跳一遍三幕相遇，
感觉对了，再决定要不要搬进正式流程。

特点：
  - 复用 .env 的 DAEMONKEY_API_KEY / DAEMONKEY_BASE_URL / DAEMONKEY_MODEL
    （兼容历史名 OPUS_API_KEY / OPUS_BASE_URL / OPUS_MODEL · DAEMONKEY_ 优先）
  - **完全自包含**的极简 tool-use 循环：不 import 主工程的 tool_loop / REGISTRY，
    只挂三个 onboarding 工具——避免把 50+ 个主工程工具拖进"相遇"污染体验。

跑法（在项目根目录）：
  .venv\\Scripts\\python.exe onboarding\\onboard.py

重新体验：删掉 soul/onboarding.json 再跑（或加 --reset）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 让 `import onboarding_prompt / proto_tools` 在任何 cwd 下都能找到本目录
sys.path.insert(0, str(Path(__file__).resolve().parent))

import proto_tools  # noqa: E402
from onboarding_prompt import ONBOARDING_SYSTEM_PROMPT  # noqa: E402


ROOT = Path(__file__).resolve().parent
DAEMON_ROOT = ROOT.parent
ENV_PATH = DAEMON_ROOT / ".env"

DIM = "\033[90m"
CYAN = "\033[96m"
GREEN = "\033[92m"
RESET = "\033[0m"


def load_env(path: Path) -> dict:
    """极简 .env 解析（不引入 python-dotenv）。"""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _env(env: dict, name: str) -> str:
    """双前缀读取：DAEMONKEY_<x> 优先，回退 OPUS_<x>（历史名）。"""
    return (env.get("DAEMONKEY_" + name) or env.get("OPUS_" + name) or "").strip()


def build_client(env: dict):
    from openai import OpenAI

    api_key = _env(env, "API_KEY")
    base_url = _env(env, "BASE_URL")
    model = _env(env, "MODEL") or "anthropic/claude-sonnet-4.5"
    if not api_key or not base_url:
        print(f"{DIM}缺 DAEMONKEY_API_KEY / DAEMONKEY_BASE_URL（在 .env 里）。{RESET}")
        sys.exit(1)
    # 跟主工程对齐 · thinking 模型 (GLM-5.x 等) 静默推理久 · 60s 太短会 ReadTimeout
    timeout = float(_env(env, "LLM_TIMEOUT_SEC") or 300)
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    return client, model


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


def run_turn(client, model: str, max_tokens: int, messages: list) -> str:
    """极简 tool-use 循环：调 LLM → 有 tool_calls 就执行回灌 → 直到出纯文本。"""
    while True:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": ONBOARDING_SYSTEM_PROMPT}] + messages,
            tools=proto_tools.TOOLS,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        text = msg.content or ""
        tool_calls = list(msg.tool_calls or [])

        assistant_entry: dict = {"role": "assistant", "content": text}
        if tool_calls:
            assistant_entry["tool_calls"] = _serialize_tool_calls(tool_calls)
        messages.append(assistant_entry)

        if not tool_calls:
            return text

        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            ok, out = proto_tools.run_tool(name, args)
            flag = "✓" if ok else "✗"
            print(f"{DIM}   [{flag} {name}] {out}{RESET}")
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": out,
            })
        # 带着工具结果再转一圈，让 LLM 接着说话


def main() -> None:
    if "--reset" in sys.argv:
        import shutil
        if proto_tools.DATA_DIR.exists():
            shutil.rmtree(proto_tools.DATA_DIR)
        print(f"{DIM}已重置 data/，重新开始相遇。{RESET}\n")

    env = load_env(ENV_PATH)
    client, model = build_client(env)
    # thinking 模型 (GLM-5.x 等) reasoning 吃 token · 默认抬到 8000 防初见回复空白 (CLI 原型·自包含)
    max_tokens = int(_env(env, "MAX_TOKENS") or 8000)

    print(f"{DIM}{'─' * 56}{RESET}")
    print(f"{DIM}Daemonkey · 相遇原型   (model: {model}){RESET}")
    print(f"{DIM}输入 /quit 退出。第一次见面，它会先开口。{RESET}")
    print(f"{DIM}{'─' * 56}{RESET}\n")

    messages: list = [
        {"role": "user", "content": "[系统提示：用户刚第一次打开应用。请你主动开口，开始第一幕『相遇』。]"}
    ]

    while True:
        try:
            reply = run_turn(client, model, max_tokens, messages)
        except Exception as e:
            print(f"{DIM}[LLM 调用出错] {type(e).__name__}: {e}{RESET}")
            break

        print(f"{CYAN}Daemonkey{RESET}  {reply}\n")

        if proto_tools.is_onboarded():
            print(f"{GREEN}── 相遇完成 ──{RESET}")
            print(f"{DIM}产物落在 soul/："
                  f"IDENTITY.json / OWNER-NOTEBOOK.md / onboarding.json{RESET}")
            break

        try:
            user = input(f"{GREEN}你{RESET}  ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}（中断·下次再聊）{RESET}")
            break
        if user.lower() in ("/quit", "/exit", "退出", "quit", "exit"):
            print(f"{DIM}（先到这·下次见）{RESET}")
            break
        if not user:
            continue
        messages.append({"role": "user", "content": user})


if __name__ == "__main__":
    main()
