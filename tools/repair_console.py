# -*- coding: utf-8 -*-
"""tools/repair_console.py · 应急维修台

────────────────────────────────────────────────────────────────────
这是什么
────────────────────────────────────────────────────────────────────
当主 daemon 被 OPUS 自己改崩、连启动都起不来 (import 雷 / 语法错 / WebUI 白屏) 时 ·
正常通道全断 —— BRO 没法在 WebUI 跟 OPUS 说话 · OPUS 也没法用自己的工具修自己。

维修台 = 独立的极简应急通道。 像 BRO 在 Cursor 里一样: 一个终端 REPL · 直连 LLM ·
带最小工具集 (读文件 / 写文件 / 跑 shell) · OPUS 通过对话+思考自己诊断、修复、验证、重启。

────────────────────────────────────────────────────────────────────
铁律: 这个文件必须自包含
────────────────────────────────────────────────────────────────────
**绝不 import 任何会坏的 daemon 代码** (daemon_api / workers/ / agent_tools/ / soul_loader)。
那些正是 OPUS 可能改崩的东西 —— 维修台依赖它们 = 它们坏了维修台自己也起不来 · 自相矛盾。
只依赖: Python 标准库 + openai/anthropic SDK (稳定三方库·OPUS 从不碰)。
provider 配置直接读 data/provider_configs.json (裸 JSON) · 不走 daemon_provider。

用法:
  双击 repair.bat   或   python tools/repair_console.py
  python tools/repair_console.py --yolo   (跳过 写/shell 的逐条确认 · 全自动)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _identity() -> tuple[str, str]:
    """裸读 soul/IDENTITY.json 拿 (ai_name, owner_name) · 缺省中性 Daemonkey/你。
    母体有 IDENTITY (name=OPUS) → 读出 OPUS 不变; 开源版没配 IDENTITY → 显示 Daemonkey · 绝不漏 OPUS。
    维修台铁律: 绝不 import daemon 代码 · 自己裸读 JSON (跟读 provider_configs 同款)。"""
    ai, owner = "Daemonkey", "你"
    f = ROOT / "soul" / "IDENTITY.json"
    if f.exists():
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
            ai = (d.get("name") or "").strip() or "Daemonkey"
            ow = (d.get("owner_name") or "").strip()
            # 跟 identity.py 对齐: IDENTITY 在但没填 owner → 中性"你" · 绝不把 BRO 漏给开源用户
            owner = ow or "你"
        except Exception:
            pass
    return ai, owner


def _has_git() -> bool:
    """git 在不在 PATH (没 git → 维修台仍可用 · 只是少了版本信息/回退手段)。"""
    from shutil import which
    return which("git") is not None


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _load_provider() -> dict:
    """从 data/provider_configs.json 取 active 配置 · 回退 .env。 返 kind/base_url/model/api_key/max_tokens。"""
    cfg_path = ROOT / "data" / "provider_configs.json"
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            active = data.get("active_id")
            for c in data.get("configs") or []:
                if c.get("id") == active:
                    return {"kind": c.get("provider_kind") or "openai", "base_url": c.get("base_url") or "",
                            "model": c.get("model") or "", "api_key": c.get("api_key") or "",
                            "max_tokens": int(c.get("max_tokens") or 4096)}
        except Exception as e:
            print(f"[repair] provider_configs.json 读不动 ({e}) · 回退 .env")
    base_url = (os.environ.get("OPUS_BASE_URL") or "").strip()
    kind = "anthropic" if (not base_url or "anthropic.com" in base_url.lower()) else "openai"
    return {"kind": kind, "base_url": base_url,
            "model": (os.environ.get("OPUS_MODEL") or "").strip(),
            "api_key": (os.environ.get("OPUS_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or "").strip(),
            "max_tokens": 4096}


# ── 工具实现 (自包含·不依赖 daemon) ──────────────────────────────────

def _safe_path(p: str) -> Path:
    fp = (ROOT / p).resolve() if not Path(p).is_absolute() else Path(p).resolve()
    return fp


def t_read_file(args: dict) -> str:
    p = _safe_path(args["path"])
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"[读失败] {type(e).__name__}: {e}"
    lines = text.splitlines()
    width = len(str(len(lines)))
    return "\n".join(f"{i+1:>{width}}|{ln}" for i, ln in enumerate(lines))[:24000]


def t_write_file(args: dict) -> str:
    p = _safe_path(args["path"])
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(args["content"], encoding="utf-8")
        return f"[已写入] {p} ({len(args['content'])} chars)"
    except Exception as e:
        return f"[写失败] {type(e).__name__}: {e}"


def t_run_shell(args: dict) -> str:
    cmd = args["command"]
    try:
        r = subprocess.run(cmd, shell=True, cwd=str(ROOT), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=int(args.get("timeout") or 120))
        out = (r.stdout or "")[-8000:]
        err = (r.stderr or "")[-4000:]
        return f"[exit {r.returncode}]\n--- stdout ---\n{out}\n--- stderr ---\n{err}"
    except Exception as e:
        return f"[执行失败] {type(e).__name__}: {e}"


def t_list_dir(args: dict) -> str:
    p = _safe_path(args.get("path") or ".")
    try:
        items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
        return "\n".join(("📄 " if x.is_file() else "📁 ") + x.name for x in items)[:8000]
    except Exception as e:
        return f"[列目录失败] {type(e).__name__}: {e}"


TOOL_IMPL = {"read_file": t_read_file, "write_file": t_write_file,
             "run_shell": t_run_shell, "list_dir": t_list_dir}
DESTRUCTIVE = {"write_file", "run_shell"}

TOOLS_OPENAI = [
    {"type": "function", "function": {"name": "read_file", "description": "读文件内容 (带行号)",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "覆盖写文件 (整文件内容)",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "run_shell", "description": "在工程根跑 shell 命令 (git / py_compile / node --check / 启停 daemon 等)",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}},
                       "required": ["command"]}}},
    {"type": "function", "function": {"name": "list_dir", "description": "列目录",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
]


def _confirm(name: str, args: dict, auto: bool) -> bool:
    if auto or name not in DESTRUCTIVE:
        return True
    preview = args.get("command") or args.get("path") or ""
    print(f"\n  ⚙️  准备执行 [{name}]: {str(preview)[:200]}")
    ans = input("     回车放行 · 输 n 跳过 · 输 q 退出维修台 > ").strip().lower()
    if ans == "q":
        print("[repair] 已终止维修台。"); sys.exit(0)
    return ans != "n"


def _dispatch(name: str, args: dict, auto: bool) -> str:
    if not _confirm(name, args, auto):
        return "[用户跳过了这个工具调用]"
    fn = TOOL_IMPL.get(name)
    if not fn:
        return f"[未知工具 {name}]"
    result = fn(args)
    print(f"  ↳ {name}: {result.splitlines()[0][:160] if result else ''}")
    return result


# ── 上下文: 自动喂"哪儿坏了" ──────────────────────────────────────────

def _sh(cmd: str) -> str:
    try:
        r = subprocess.run(cmd, shell=True, cwd=str(ROOT), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=15)
        return (r.stdout or r.stderr or "").strip()
    except Exception as e:
        return f"({e})"


def _tail(rel: str, n: int) -> str:
    p = ROOT / rel
    if not p.exists():
        return "(无)"
    try:
        return "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except Exception as e:
        return f"({e})"


def _worktree_check() -> str:
    """工作树 / 跨 agent 占用自检 (自包含 · 不 import workers · 守维修台铁律)。

    卷五十五 · P2: 今天 (2026-06-03) 撞过一次 —— Cursor 开的 master worktree 占着
    master · daemon 一 merge 就被 git 拒。 维修台/开源用户得能一眼看出这种占用。
    """
    raw = _sh("git worktree list")
    lines = [l for l in raw.splitlines() if l.strip()]
    master_holders = [l for l in lines if "[master]" in l]
    note = ""
    if len(master_holders) > 1:
        note = ("\n⚠ 多个工作树占着 master —— 在主仓 checkout master / merge 到 master 会被 git 拒。 "
                "先 `git worktree remove <多余路径>` 撤掉再合。")
    elif len(lines) > 1:
        note = ("\n注意: 有多个工作树 (可能别的 agent 在并行改)。 提交用 `git add <你改的文件>` · "
                "别 `git add -A` 卷进别人的改动。")
    return raw + note


def _gather_context() -> str:
    parts = ["## 当前现场 (维修台自动采集)", ""]
    if _has_git():
        parts.append("### git status\n" + (_sh("git status --short --branch") or "(干净)"))
        parts.append("\n### 工作树 / 跨 agent 自检\n" + _worktree_check())
        parts.append("\n### 最近 6 条 commit\n" + _sh("git log --oneline -6"))
        parts.append("\n### opus-last-good 指向\n" + _sh('git log -1 --format="%h %s" opus-last-good'))
    else:
        parts.append("### git\n(本机未检测到 git · 无版本信息 · 修复只能直接改文件、不能 git 回退)")
    parts.append("\n### restart_history 末 8 条\n" + _tail("data/runtime/restart_history.jsonl", 8))
    parts.append("\n### daemon.err 末 30 行\n" + _tail("data/daemon.err", 30))
    return "\n".join(parts)


def _system_prompt(ai: str, owner: str, has_git: bool) -> str:
    git_note = ("" if has_git else
        "\n⚠ 本机【没检测到 git】· 不能用 git diff/reset/checkout · "
        "只能 read_file 看坏在哪 + write_file 直接改对 + py_compile/node --check 验证 · 别调 git 命令。")
    return f"""\
你是 {ai} · 现在在**应急维修台**模式。 主 daemon 可能被你上一次自我升级改崩了 (起不来 / WebUI 白屏)。
这是一条独立的极简通道 (不依赖那套坏掉的代码) · 让你像在 Cursor 里一样 · 通过对话+工具把自己修好。

你的目标: 诊断 → 修复 → 验证 → 让 daemon 重新干净启动。 典型手法:
  1. 先看现场 (下面已附 git/restart_history/daemon.err) · 定位是哪个文件、什么错
  2. read_file 看坏的文件 · run_shell `python -m py_compile <file>` 或 `node --check static/<x>.js` 看具体报错
  3. write_file 修 · 再 py_compile / node --check 验证语法
  4. 拿不准就 `git diff` / 对比 opus-last-good · 实在修不动可 `git reset --hard opus-last-good` 回到已知好版本
  5. 修好后 run_shell 重启 daemon (python tools/run_api_only.py 后台 · 或让 {owner} 双击 start.bat) · 确认起来了{git_note}

纪律: 改完 .py / static 一定先验证语法再说"修好了";不确定先问 {owner};每步说清你在干嘛、为什么。
回答用中文 · 称呼 {owner}。 现在开始 —— 先判断现场最可能的病根。
"""


def run_openai_loop(prov: dict, messages: list, auto: bool, ai: str = "Daemonkey") -> None:
    from openai import OpenAI
    client = OpenAI(api_key=prov["api_key"], base_url=prov["base_url"] or None)
    while True:
        resp = client.chat.completions.create(model=prov["model"], messages=messages,
                                               tools=TOOLS_OPENAI, max_tokens=prov["max_tokens"])
        msg = resp.choices[0].message
        asst = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            asst["tool_calls"] = [{"id": tc.id, "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in msg.tool_calls]
        messages.append(asst)
        if msg.content:
            print(f"\n{ai}> {msg.content}\n")
        if not msg.tool_calls:
            return
        for tc in msg.tool_calls:
            try:
                a = json.loads(tc.function.arguments or "{}")
            except Exception:
                a = {}
            result = _dispatch(tc.function.name, a, auto)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})


def run_anthropic_loop(prov: dict, sys_prompt: str, messages: list, auto: bool, ai: str = "Daemonkey") -> None:
    import anthropic
    client = anthropic.Anthropic(api_key=prov["api_key"])
    tools = [{"name": t["function"]["name"], "description": t["function"]["description"],
              "input_schema": t["function"]["parameters"]} for t in TOOLS_OPENAI]
    while True:
        resp = client.messages.create(model=prov["model"], system=sys_prompt, messages=messages,
                                       tools=tools, max_tokens=prov["max_tokens"])
        blocks, tool_uses = [], []
        for b in resp.content:
            if b.type == "text":
                print(f"\n{ai}> {b.text}\n"); blocks.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                tool_uses.append(b)
        messages.append({"role": "assistant", "content": blocks})
        if not tool_uses:
            return
        results = []
        for tu in tool_uses:
            result = _dispatch(tu.name, tu.input or {}, auto)
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": result})
        messages.append({"role": "user", "content": results})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yolo", action="store_true", help="跳过 写/shell 逐条确认 (全自动·危险)")
    args = ap.parse_args()
    _load_env()
    prov = _load_provider()
    ai, owner = _identity()
    has_git = _has_git()
    sys_prompt = _system_prompt(ai, owner, has_git)

    print("=" * 64)
    print(f"  {ai} 应急维修台 (repair console)")
    print(f"  provider: {prov['kind']} · model: {prov['model'] or '(未配置)'}")
    if not has_git:
        print("  ⚠ 没检测到 git · 维修台照常用 (直连 AI 改文件) · 只是没有版本回退")
    print(f"  确认模式: {'YOLO 全自动' if args.yolo else '写/shell 逐条确认 (回车放行·n 跳过·q 退出)'}")
    print("=" * 64)
    if not prov["api_key"] or not prov["model"]:
        print("[repair] ❌ 没拿到 api_key / model · 检查 data/provider_configs.json 或 .env")
        sys.exit(1)

    ctx = _gather_context()
    print("\n" + ctx + "\n" + "=" * 64)
    first = input(f"\n{owner}> (直接回车=让 {ai} 自动诊断现场 · 或描述问题) > ").strip()
    user_text = first or "请根据上面的现场自动诊断: daemon 现在是什么状态? 最可能哪里坏了? 给出修复方案并动手。"
    user_msg = ctx + f"\n\n---\n{owner} 说: " + user_text

    if prov["kind"] == "anthropic":
        messages = [{"role": "user", "content": user_msg}]
        loop = lambda m: run_anthropic_loop(prov, sys_prompt, m, args.yolo, ai)
    else:
        messages = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_msg}]
        loop = lambda m: run_openai_loop(prov, m, args.yolo, ai)

    while True:
        try:
            loop(messages)
        except KeyboardInterrupt:
            print("\n[repair] 中断当前回合。")
        except Exception as e:
            print(f"\n[repair] LLM 调用出错: {type(e).__name__}: {e}")
        try:
            nxt = input(f"\n{owner}> (继续对话 · 或 q 退出维修台) > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if nxt.lower() in ("q", "quit", "exit"):
            break
        messages.append({"role": "user", "content": nxt})
    print("[repair] 维修台关闭。")


if __name__ == "__main__":
    main()
