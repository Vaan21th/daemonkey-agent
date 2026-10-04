"""agent_tools/add_iron_rule.py
================================

卷四十四 K stage 2c++ · wish-a72b2f0a · 一调双写新铁律到两个文件

为什么有这个工具
------------------
我 (上一根毛 · 卷四十四 K stage 2c++) 给 daemon_rules.md 加了铁律 5 / 6 / 7 ·
写 daemon_rules.md（装进每次对话）。技能库读这份文件。
2026-08-30 起不再双写 opus-diary.md——日记标签只收相处账。

调用时机:
  - BRO 让 Daemonkey 加一条新铁律 (例如"以后干 X 类工作必须先做 Y")
  - Daemonkey 自己反思后认定一条工艺纪律值得升到铁律层级 (但建议先跟 BRO 商量)

tier:
  TIER_CONFIRM —— 铁律是骨头层东西 · 一旦写入会影响所有未来 Daemonkey · 不应该自动加 ·
  必须 BRO 看摘要 ✓ 才执行

⚠️ 重要 · 重启延迟:
  daemon 启动时 soul_loader 把 daemon_rules.md 缓存到 RUNTIME.system_prompt ·
  之后 chat session 共用这份缓存 · **改 daemon_rules.md 不重启 daemon · LLM context
  里看不到新铁律**。 这个工具会在返回结果里明确告知这点 · 让 Daemonkey 不要装作下一句话
  开始就按新铁律走。 BRO 重启 daemon 后才在 LLM context 生效。
  但 opus-diary.md 是 UI 实时读 · F5 立刻可见。
"""

from __future__ import annotations

import threading
from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool
from .list_iron_rules import BUDGET_TOK, parse_rules, read_rules_text


ROOT = Path(__file__).resolve().parent.parent
DAEMON_RULES_PATH = ROOT / "data" / "cognition" / "daemon_rules.md"
DIARY_PATH = ROOT / "data" / "cognition" / "opus-diary.md"
ANCHOR_LINE = "## 反面教材"
_WRITE_LOCK = threading.Lock()

# 新装实例没有 daemon_rules.md (母体是历史积累才有的)。 而 soul_loader 只要文件存在就
# 以最高优先级注入 → 缺的只是"第一条怎么落地"。 缺文件就用这个头新建。
_FILE_HEADER = (
    "# 干活铁律\n\n"
    "> 本文件以【最高优先级】拼进每次对话的 system_prompt·对所有未来对话生效。\n"
    "> 所以只放真正的硬约束 (纪律 / 禁忌 / 表达偏好)·不放临时想法。\n"
    "> 官方升级永不覆盖本文件。\n\n"
)


def _summarize(args: dict) -> str:
    n = args.get("rule_number") or "?"
    title = (args.get("title") or "").strip()[:60] or "(未命名)"
    return f"加铁律 {n} · 「{title}」 · 写入 daemon_rules.md"


def _existing_rule_numbers() -> list[int]:
    """wish-631ff85b · 改用 parse_rules（list / update 共用一份判据）。"""
    if not DAEMON_RULES_PATH.exists():
        return []
    return [r["n"] for r in parse_rules(read_rules_text(DAEMON_RULES_PATH))]


def _peer_lines(n: int, title: str) -> list[str]:
    """同类清单 —— 加之前先让 LLM 看见『已经有哪些条』，替它做查重。

    不做字符相似度（不可靠）：直接列现有全部小标题，长一眼就能认出撞车。
    """
    if not DAEMON_RULES_PATH.exists():
        return []
    rules = parse_rules(read_rules_text(DAEMON_RULES_PATH))
    if not rules:
        return []
    return [f"  · {r['n']}. {r['title']}" for r in rules]


def _run(args: dict) -> ToolResult:
    from workers.cognition_loader import _VALID_DOMAINS

    # ── 输入校验 ─────────────────────────────────
    rule_number = args.get("rule_number")
    title = (args.get("title") or "").strip()
    daemon_md = (args.get("daemon_md") or "").strip()
    diary_summary = (args.get("diary_summary") or "").strip()
    # 默认留空: 母体有卷号叙事·新实例没有。 写进文件的内容不过 localize·硬默认值会漏出去。
    cite_volume = (args.get("cite_volume") or "").strip()
    domain = (args.get("domain") or "global").strip().lower()
    if domain not in _VALID_DOMAINS:
        return ToolResult(
            ok=False, output="",
            error=f"domain={domain!r} 不在合法集 {list(_VALID_DOMAINS)} · 默认 'global'",
        )

    if not isinstance(rule_number, int) or rule_number <= 0:
        return ToolResult(ok=False, output="", error="rule_number 必须是正整数")
    if not title:
        return ToolResult(ok=False, output="", error="title 必填 (短标题)")
    if len(title) > 100:
        return ToolResult(ok=False, output="", error=f"title 太长 (>100 chars): {len(title)}")
    if not daemon_md:
        return ToolResult(ok=False, output="", error=(
            "daemon_md 必填 · 这是写到 daemon_rules.md 的完整 markdown body · "
            "LLM 必须自己组织好 · 包含 `## 铁律 N · 标题` 头 + 内容 + `---` 尾"
        ))
    # diary_summary 仍收（旧调用方会传），不再落日记

    # rule_number 不能跟现有冲突。
    # wish-631ff85b 解死锁：原先还强制「必须 = max+1」，导致删掉中间某条后**永远加不了**。
    # 改成「不重复即可」—— 连续性对 LLM 手写才有意义，有了 update 通道就不需要了。
    with _WRITE_LOCK:
        existing = _existing_rule_numbers()
        if existing and rule_number in existing:
            return ToolResult(
                ok=False, output="",
                error=f"rule_number={rule_number} 已存在 · 现有铁律: {existing} · 取下一个: {max(existing) + 1}",
            )

        expected_header = f"## 铁律 {rule_number} ·"
        if expected_header not in daemon_md:
            return ToolResult(
                ok=False, output="",
                error=(
                    f"daemon_md 必须包含正确头 `{expected_header}` (LLM 写时一定要把 N 跟 args 对齐)"
                ),
            )

        if not DAEMON_RULES_PATH.exists():
            DAEMON_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
            DAEMON_RULES_PATH.write_text(_FILE_HEADER, encoding="utf-8", newline="")

        text = read_rules_text(DAEMON_RULES_PATH)
        anchor_idx = text.find(ANCHOR_LINE)
        daemon_md_stripped = daemon_md.rstrip()
        # wish-631ff85b · 统一格式：domain 注释写在**标题之前**（parse_rules 按此往前找）。
        # 旧版把 domain 附在正文末尾 —— 与文件里已有条目的写法不一致，导致解析错位。
        if daemon_md_stripped.endswith("---"):
            daemon_md_stripped = daemon_md_stripped[:-3].rstrip()
        _lines = daemon_md_stripped.split("\n")
        _head = _lines[0].strip()
        _rest = "\n".join(_lines[1:]).strip()
        daemon_md_with_domain = (
            f"<!-- domain: {domain} -->\n\n{_head}\n\n{_rest}\n\n---"
        )
        insert_block = daemon_md_with_domain.rstrip() + "\n\n"
        new_text = (
            text[:anchor_idx] + insert_block + text[anchor_idx:]
            if anchor_idx != -1
            else text.rstrip() + "\n\n" + insert_block
        )
        # 落盘前自愈段头粘连（wish-66c1eac5 第 4 步 · 2026-09-30）：
        #   画像侧靠 write_global_then_sync 里的 heal_headings，铁律侧原来**绕过了**这道闸。
        #   铁律段头（`## 10 · UI`）一样会粘到上一行末尾，粘了就再没人找得到它。
        try:
            from soul_loader import heal_headings as _hh
            new_text, _fixed_heads = _hh(new_text)
        except Exception:
            _fixed_heads = []
        import tempfile
        import os
        fd, tmp_name = tempfile.mkstemp(
            dir=str(DAEMON_RULES_PATH.parent),
            prefix=DAEMON_RULES_PATH.name + ".",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(new_text)
            os.replace(tmp_name, DAEMON_RULES_PATH)
        except Exception as e:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            return ToolResult(ok=False, output="", error=f"写 daemon_rules.md 失败: {e}")

    lines = [
        f"# 铁律 {rule_number} 已写入 daemon_rules.md",
        f"  - 标题: {title}",
        f"  - domain: {domain}",
        f"  - daemon_rules.md 长度: {len(text)} → {len(new_text)} (+{len(insert_block)})",
        "  - 操作手册页刷新可见。不写相处账。",
    ]
    # wish-631ff85b · 预算镜子 + 同类查重（写入前替 LLM 看一眼）
    try:
        import tiktoken

        tok_after = len(tiktoken.get_encoding("cl100k_base").encode(new_text))
    except Exception:
        tok_after = max(1, int(len(new_text) / 1.6))
    left = BUDGET_TOK - tok_after
    lines.append(f"  - 预算 {BUDGET_TOK} tok · 现在 {tok_after} tok · 余量 {left} tok")
    peers = _peer_lines(rule_number, title)
    if peers:
        lines += ["", "同册已有（先看一眼有没有撞车 / 该合并）:"] + peers
    if left < 0:
        lines += [
            "",
            f"⚠️ 自问: 铁律层已超预算 {abs(left)} tok。加之前先想 —— 是不是该合并几条，"
            "或者有些已经能用代码闸拦的该删掉（update_iron_rule operation='delete'）？",
        ]
    lines += [
        "",
        "重启 daemon 后，新对话才会装上这条铁律。",
        "当前这轮脑里还是旧的。",
    ]
    if cite_volume:
        lines.insert(2, f"  - cite: {cite_volume}")
    _ = diary_summary
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="add_iron_rule",
    description=(
        "用户定下干活纪律 / 硬规矩（「以后一律…」/「不许…」/「必须…」）→ 加一条铁律：只写 daemon_rules.md。先 list_iron_rules 取 max+1。产品观走 CONSTITUTION；用户事实走 update_owner_note。简介不许写成长文（铁律 15）。细读：read_scenario('self_evolution')。"    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "rule_number": {
                "type": "integer",
                "description": "铁律编号 · 必须等于 list_iron_rules 返回的 max + 1",
                "minimum": 1,
            },
            "title": {
                "type": "string",
                "description": "短标题 · 例如 '造工坊资产时先落档' · 100 chars 以内",
                "minLength": 4,
                "maxLength": 100,
            },
            "daemon_md": {
                "type": "string",
                "description": "完整铁律 markdown：标题头 + 触发 + 纪律 + 反面教材。写法见 read_scenario('self_evolution')。",
                "minLength": 100,
            },
            "diary_summary": {
                "type": "string",
                "description": "旧字段，仍要传。不再写入日记。200-800 chars",
                "minLength": 50,
            },
            "cite_volume": {
                "type": "string",
                "description": "可选出处引用 · 写到 diary 标题前缀 · 留空就没前缀",
            },
            "domain": {
                "type": "string",
                "enum": [
                    "global", "self_evolution", "app_creation",
                    "workflow_creation", "client_ops", "production", "reflection",
                ],
                "description": "场景域，见 enum。默认 global。",
            },
        },
        "required": ["rule_number", "title", "daemon_md", "diary_summary"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
