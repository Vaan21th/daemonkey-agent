"""agent_tools/list_iron_rules.py
====================================

卷四十四 K stage 2c++ · wish-a72b2f0a 配套 · 列现有铁律编号 + 标题

LLM 调 add_iron_rule 之前 · 必须先调这个看现有最大编号 · 取 max+1。
也用来诊断 (BRO 问『现在有几条铁律』时直接调这个)。

tier: TIER_AUTO (只读 metadata)
"""

from __future__ import annotations

import re
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


ROOT = Path(__file__).resolve().parent.parent
DAEMON_RULES_PATH = ROOT / "data" / "cognition" / "daemon_rules.md"

# ── 铁律层预算 · wish-631ff85b ────────────────────────────────
# 2026-09-19 BRO：「我真的希望他少写」—— 铁律该薄。定 2,500 tok（改造前实测 2,388）。
# 贴着上限不是为了数字好看，是让写入回报能当场提醒「余量不足 / 已超」。
# 它是**镜子**不是硬闸（同核心层那格）：超了仍能写，但回报会追问一句。
BUDGET_TOK = 2500


def _summarize(args: dict) -> str:
    return "列 daemon_rules.md 现有铁律 (编号 + 标题) · LLM 加铁律前查重必备"


# ── 单一真相源 · wish-631ff85b ────────────────────────────────
# 铁律的解析判据只此一份：list / add / update 三个工具都从这里取。
# 之前 add_iron_rule 自己另写了一份 `^## 铁律 (\d+)\s+·` 正则 —— 那是手抄判据。
HEADER_RE = re.compile(r"^## 铁律 (\d+)\s+·\s+(.+)$", re.MULTILINE)
DOMAIN_RE = re.compile(r"<!--\s*domain:\s*(\w+)\s*-->")
# 下一个 `## ` 级小节的起点。
# ⚠ 不能拿「下一条铁律」当边界：最后一条铁律后面若还跟着别的小节（如文件尾的
#   `<!-- domain: global -->` + 「反面教材…」），用「下一条铁律」会让它把尾部整段吃进去 ——
#   那意味着 replace / delete 最后一条铁律时，会静默连文件尾一起删掉。
NEXT_SECTION_RE = re.compile(r"^(?:## |<!--\s*domain:)", re.MULTILINE)


def _next_section_start(text: str, from_pos: int) -> int:
    """本段正文的终点 = 下一个 `## ` 标题 / 下一条 `<!-- domain: -->` 注释 / 文件尾。

    两个都要：真文件尾部那句「反面教材…」前面**没有 `## ` 标题**，只有一条 domain 注释 ——
    光用 `## ` 兜不住，replace / delete 最后一条铁律时会把那句一起吃掉。
    """
    m = NEXT_SECTION_RE.search(text, from_pos)
    return m.start() if m else len(text)


def read_rules_text(path: Path | None = None) -> str:
    """读 daemon_rules.md · newline="" 不转换换行。

    为什么不用 Path.read_text：Python 3.11 还不支持 newline 参数，会隐式把 CRLF→LF；
    而写回时默认又 LF→CRLF。两端一撞，内容没变也变成满屏 git 改动。
    读写都走这里，才能做到「内容不变 → 字节不变」。
    """
    p = DAEMON_RULES_PATH if path is None else path
    with open(p, encoding="utf-8", newline="") as f:
        return f.read()


def count_tokens(text: str) -> int:
    """token 数（tiktoken · 失败按中文实测系数 0.67 字符/token 退算）。

    跟 api_routes/chat.py 面板用**同一把尺子** —— 两个地方显示的数必须能对上，
    否则 BRO 看到两个不一样的数，会以为哪里错了。
    """
    if not text:
        return 0
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        return int(len(text) / 0.67)


def parse_rules(text: str) -> list[dict]:
    """把 daemon_rules.md 切成 [{n, title, domain, start, end, body}] · 按 n 排序。

    start/end 是原文偏移 · 给 replace / delete 精确定位那一段用。
    """
    matches = list(HEADER_RE.finditer(text))
    rules = []
    for idx, m in enumerate(matches):
        try:
            num = int(m.group(1))
        except ValueError:
            continue
        title = m.group(2).strip()
        title_main = re.sub(r"\s*\([^)]*\)\s*$", "", title)
        body_start = m.end()
        body_end = _next_section_start(text, body_start)
        body = text[body_start:body_end]
        # domain 注释写在标题【之前】（与文件现有格式 / add_iron_rule 写出格式一致）：
        #   <!-- domain: X -->
        #   ## 铁律 N · 标题
        # 所以要**往前找** —— 上一个规则段末尾到本标题之间那一段。
        # wish-631ff85b 修：旧版在 body 里 search，取到的是**下一条**的 domain（静默错位）。
        prev_end = matches[idx - 1].end() if idx > 0 else 0
        prelude = text[prev_end:m.start()]
        dm = DOMAIN_RE.search(prelude)
        domain = dm.group(1).strip().lower() if dm else "global"
        # block_start = 本条 domain 注释的起点（若有）· 否则就是标题起点。
        # replace / delete 必须用它：拿标题起点当界的话，旧 domain 注释会留在原地，
        # 跟新写的凑成两条（解析时 search 取第一个 → 改 domain 静默失效）。
        block_start = prev_end + dm.start() if dm else m.start()
        rules.append({
            "n": num,
            "title": title_main,
            "domain": domain,
            "block_start": block_start,
            "start": m.start(),
            "end": body_end,
            "body": body,
        })
    rules.sort(key=lambda r: r["n"])
    return rules


def _run(args: dict) -> ToolResult:
    # 0.9.6 修 · 新装实例还没这个文件 —— 那是"一条铁律都还没加"的正常状态·不是故障。
    #   原先报 error 会让 LLM 以为系统坏了·转而不敢调 add_iron_rule 加第一条。
    if not DAEMON_RULES_PATH.exists():
        return ToolResult(ok=True, output=(
            "还没有任何铁律 (data/cognition/daemon_rules.md 尚未建立)。\n"
            "加第一条 → add_iron_rule · rule_number=1 (文件会自动建好)。"
        ))

    text = read_rules_text()

    # 卷四十六 II · wish-ff100836 · 解析 domain 注释 (与 add_iron_rule 写出格式呼应)
    # wish-631ff85b · 判据归一：改用 parse_rules（list / add / update 共用一份）
    rules = parse_rules(text)

    if not rules:
        return ToolResult(ok=True, output="(daemon_rules.md 没匹配 `## 铁律 N · ...` 格式 · 文件可能损坏)")

    # 按 domain 分组统计
    by_domain: dict[str, list[dict]] = {}
    for r in rules:
        by_domain.setdefault(r["domain"], []).append(r)

    lines = [
        f"# 现有铁律 (共 {len(rules)} 条 · 加新铁律传 rule_number={rules[-1]['n'] + 1})",
        "",
        "## 按 domain 分组",
        "",
    ]
    for dom in sorted(by_domain.keys()):
        lines.append(f"### `{dom}` ({len(by_domain[dom])} 条)")
        for r in by_domain[dom]:
            lines.append(f"  - **铁律 {r['n']}** · {r['title']}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("→ 调 `add_iron_rule` 加新条目 · rule_number 必须 = " + str(rules[-1]["n"] + 1))
    lines.append("→ domain 默认 'global' (所有场景看见) · 可选 self_evolution / app_creation / workflow_creation / client_ops / production / reflection")

    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="list_iron_rules",
    description=(
        "列 daemon_rules.md 现有所有铁律 (编号 + 标题) · 给 LLM 加铁律前查重用\n\n"
        "**用途**:\n"
        "  - 调 add_iron_rule 之前 · 看现有最大编号 · 取 max+1 (防漏编 / 撞号)\n"
        "  - 用户问『现在工程多少条铁律』时直接调这个回\n"
        "  - 你自己反思想加铁律前 · 看是否已有同类规则 (避免重复)"
    ),
    tier=TIER_AUTO,
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
