"""agent_tools/update_iron_rule.py
====================================

wish-631ff85b · 铁律的改 / 删通道

为什么有这个工具
-----------------
2026-09-19 BRO 拍板：铁律**留前缀、不走召回**（判据是「可判定性」不是「重要性」），
但要做归口治理。查现状时挖出根因：

  · add_iron_rule 只能加 · 没有 edit / delete —— **铁律在结构上只能长**
  · 更糟：add 强制「编号必须连续」 → 一旦真删了中间某条，再加就被永远锁死

所以补这条通道。它跟 add 是同一层级的骨头工具（都是 TIER_CONFIRM）。

operation:
  - replace · 换掉第 N 条的整段（content = 完整新 markdown，含 `## 铁律 N · 标题` 头）
              · 新 content 若没带 `<!-- domain: X -->`，自动继承旧条的 domain
  - delete  · 删掉第 N 条（不需要 content）

为什么 delete 也要 CONFIRM:
  铁律影响所有未来对话。误删的代价高于误加 —— 加错了能删，删错了没人知道少了什么。

⚠️ 重启延迟:
  同 add_iron_rule —— daemon 启动时把 daemon_rules.md 缓存进 RUNTIME.system_prompt，
  改完要重启才在新对话生效。本工具会在回报里明说，别装作下一句就按新版本走。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool
from .add_iron_rule import _WRITE_LOCK  # 共用一把写锁 · 防 add/update 并发覆盖
from .list_iron_rules import BUDGET_TOK, parse_rules, read_rules_text

ROOT = Path(__file__).resolve().parent.parent
DAEMON_RULES_PATH = ROOT / "data" / "cognition" / "daemon_rules.md"


def _summarize(args: dict) -> str:
    op = args.get("operation") or "?"
    n = args.get("rule_number") or "?"
    zh = {"replace": "改", "delete": "删"}.get(op, op)
    return f"{zh}铁律 {n} · 写入 daemon_rules.md"


def _est_tok(text: str) -> int:
    try:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        return max(1, int(len(text) / 1.6))  # 中文混合粗估


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        # newline="" 必填：默认会把 LF 悄悄转成 CRLF，等于每次写入都改掉整个文件的换行风格
        # （git 上显示满屏改动）。读写两端都用 newline=""，才能做到「内容不变 → 字节不变」。
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _run(args: dict) -> ToolResult:
    op = (args.get("operation") or "").strip().lower()
    n = args.get("rule_number")
    content = (args.get("content") or "").strip()

    if op not in ("replace", "delete"):
        return ToolResult(ok=False, output="", error=(
            f"operation={op!r} 不合法 · 只支持 'replace'（换整条）/ 'delete'（删一条）"
        ))
    if not isinstance(n, int) or n <= 0:
        return ToolResult(ok=False, output="", error="rule_number 必须是正整数")

    if not DAEMON_RULES_PATH.exists():
        return ToolResult(ok=False, output="", error="data/cognition/daemon_rules.md 不存在 · 无可改")

    with _WRITE_LOCK:
        text = read_rules_text(DAEMON_RULES_PATH)
        rules = parse_rules(text)
        target = next((r for r in rules if r["n"] == n), None)
        if target is None:
            have = ", ".join(str(r["n"]) for r in rules) or "(空)"
            return ToolResult(ok=False, output="", error=(
                f"铁律 {n} 不存在 · 现有编号: {have}"
            ))

        tok_before = _est_tok(text)

        if op == "delete":
            # 连它的 domain 注释一起删（block_start）· 不残留孤零注释
            new_text = text[:target["block_start"]] + text[target["end"]:]
            new_text = new_text.rstrip() + "\n"
        else:
            if not content:
                return ToolResult(ok=False, output="", error=(
                    "operation='replace' 时 content 必填 · 完整 markdown（含 `## 铁律 N · 标题` 头）"
                ))
            if f"## 铁律 {n} ·" not in content:
                return ToolResult(ok=False, output="", error=(
                    f"content 必须含正确头 `## 铁律 {n} ·`（编号要跟 rule_number 对齐）"
                ))
            body = content.rstrip()
            if "<!--" not in body:
                # 新 content 没带 domain 注释 → 继承旧条，避免静默退化成 global。
                # 格式统一：注释写在**标题之前**（parse_rules 按此往前找）。
                # ⚠ 标题之后的部分必须**原样**保留（含它自己的空行）：用 partition("\n") 会吃掉一个换行，
                #   导致「replace 同样内容」不是幂等的 —— 静默吞掉标题后的空行。
                _i = body.find("\n")
                _head = body if _i == -1 else body[:_i]
                _tail = "" if _i == -1 else body[_i:]
                body = f"<!-- domain: {target['domain']} -->\n\n{_head}{_tail}"
            new_text = text[:target["block_start"]] + body + "\n\n" + text[target["end"]:]

        try:
            _atomic_write(DAEMON_RULES_PATH, new_text)
            written = True
        except Exception as e:
            return ToolResult(ok=False, output="", error=f"写 daemon_rules.md 失败: {e}")

    tok_after = _est_tok(new_text)
    delta = tok_after - tok_before
    left = BUDGET_TOK - tok_after
    zh = {"replace": "改", "delete": "删"}[op]

    lines = [
        f"# 铁律 {n} 已{zh} · 「{target['title']}」",
        f"  - 域: {target['domain']}",
        f"  - 本条 {delta:+d} tok · 文件 {tok_before}→{tok_after} tok",
        f"  - 预算 {BUDGET_TOK} tok · 余量 {left} tok" + ("  ⚠️ 已超预算" if left < 0 else ""),
        f"  - 现有 {len(rules) + (-1 if op == 'delete' else 0)} 条",
    ]
    if written and left < 0:
        lines += [
            "",
            f"⚠️ 自问: 铁律层已超额 {abs(left)} tok。要加东西之前先想 —— "
            "是不是该把某几条合并、或者已有代码闸能拦的该删掉？",
        ]
    lines += [
        "",
        "重启 daemon 后新对话才装上这次改动。当前这轮脑里还是旧的。",
    ]
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="update_iron_rule",
    description=(
        "改 / 删 daemon_rules.md 里已有的铁律（replace / delete）。"
        "铁律只增不减的根因就是缺这条通道。加新铁律仍走 add_iron_rule。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["replace", "delete"],
                "description": "replace=换整条（需 content）· delete=删掉这条",
            },
            "rule_number": {
                "type": "integer",
                "description": "目标铁律编号 · 先 list_iron_rules 看现有",
                "minimum": 1,
            },
            "content": {
                "type": "string",
                "description": "replace 时的完整新 markdown（含 `## 铁律 N · 标题` 头）。delete 不用传。",
            },
        },
        "required": ["operation", "rule_number"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
