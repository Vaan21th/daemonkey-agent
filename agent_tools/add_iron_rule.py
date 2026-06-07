"""agent_tools/add_iron_rule.py
================================

 K stage 2c++ · wish-a72b2f0a · 一调双写新铁律到两个文件

为什么有这个工具
------------------
我 (上一根毛 ·  K stage 2c++) 给 daemon_rules.md 加了铁律 5 / 6 / 7 ·
每次都是手工双写: 写 daemon_rules.md (LLM context 顶部) + 调 update_opus_diary
(UI 显示)。 漏一个 = 用户 在 UI 看不到这条规则·或者 LLM 没装上这条规则。

这个工具一调双写 · 让"加铁律"变原子操作。

跟 update_opus_diary 的区别:
  - update_opus_diary: 通用日记追加 · 任何反思 / 想法 / 学习
  - add_iron_rule: 铁律专用 · 加 daemon_rules.md (LLM 必须看) + opus-diary.md
    (UI 必须显示) · 校验 rule_number 不冲突 · 防 OPUS 自我洗脑

调用时机:
  - 用户 让 OPUS 加一条新铁律 (例如"以后干 X 类工作必须先做 Y")
  - OPUS 自己反思后认定一条工艺纪律值得升到铁律层级 (但建议先跟 用户 商量)

tier:
  TIER_CONFIRM —— 铁律是骨头层东西 · 一旦写入会影响所有未来 OPUS · 不应该自动加 ·
  必须 用户 看摘要 ✓ 才执行

⚠️ 重要 · 重启延迟:
  daemon 启动时 soul_loader 把 daemon_rules.md 缓存到 RUNTIME.system_prompt ·
  之后 chat session 共用这份缓存 · **改 daemon_rules.md 不重启 daemon · LLM context
  里看不到新铁律**。 这个工具会在返回结果里明确告知这点 · 让 OPUS 不要装作下一句话
  开始就按新铁律走。 用户 重启 daemon 后才在 LLM context 生效。
  但 opus-diary.md 是 UI 实时读 · F5 立刻可见。
"""

from __future__ import annotations

import re
from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


ROOT = Path(__file__).resolve().parent.parent
DAEMON_RULES_PATH = ROOT / "data" / "cognition" / "daemon_rules.md"
DIARY_PATH = ROOT / "data" / "cognition" / "opus-diary.md"
ANCHOR_LINE = "## 的反面教材"


def _summarize(args: dict) -> str:
    n = args.get("rule_number") or "?"
    title = (args.get("title") or "").strip()[:60] or "(未命名)"
    return f"加铁律 {n} · 「{title}」 · 双写 daemon_rules.md + opus-diary.md"


def _existing_rule_numbers() -> list[int]:
    if not DAEMON_RULES_PATH.exists():
        return []
    text = DAEMON_RULES_PATH.read_text(encoding="utf-8")
    nums = []
    for m in re.finditer(r"^## 铁律 (\d+)\s+·", text, re.MULTILINE):
        try:
            nums.append(int(m.group(1)))
        except ValueError:
            pass
    return sorted(nums)


def _run(args: dict) -> ToolResult:
    from workers.cognition_loader import update_opus_diary, _VALID_DOMAINS

    # ── 输入校验 ─────────────────────────────────
    rule_number = args.get("rule_number")
    title = (args.get("title") or "").strip()
    daemon_md = (args.get("daemon_md") or "").strip()
    diary_summary = (args.get("diary_summary") or "").strip()
    cite_volume = (args.get("cite_volume") or " K").strip()
    domain = (args.get("domain") or "global").strip().lower()
    if domain not in _VALID_DOMAINS:
        return ToolResult(
            ok=False, output="",
            error=f"domain={domain!r} 不在合法集 {list(_VALID_DOMAINS)} · 默认 'global'",
        )

    if not isinstance(rule_number, int) or rule_number <= 0:
        return ToolResult(ok=False, output="", error="rule_number 必须是正整数")
    if not title:
        return ToolResult(ok=False, output="", error="title 必填 (短标题 · 用于 diary 标题)")
    if len(title) > 100:
        return ToolResult(ok=False, output="", error=f"title 太长 (>100 chars): {len(title)}")
    if not daemon_md:
        return ToolResult(ok=False, output="", error=(
            "daemon_md 必填 · 这是写到 daemon_rules.md 的完整 markdown body · "
            "LLM 必须自己组织好 · 包含 `## 铁律 N · 标题` 头 + 内容 + `---` 尾"
        ))
    if not diary_summary:
        return ToolResult(ok=False, output="", error=(
            "diary_summary 必填 · 给 UI 显示的版本 · markdown body 不含 `##` 头 · "
            "update_opus_diary 会自动加日期跟标题。 推荐结构: 触发 / 纪律 / 反面教材"
        ))

    # rule_number 不能跟现有冲突
    existing = _existing_rule_numbers()
    if existing and rule_number in existing:
        return ToolResult(
            ok=False, output="",
            error=f"rule_number={rule_number} 已存在 · 现有铁律: {existing} · 取下一个: {max(existing) + 1}",
        )
    if existing and rule_number != max(existing) + 1:
        return ToolResult(
            ok=False, output="",
            error=(
                f"rule_number={rule_number} 不连续 · 现有最大: {max(existing)} · "
                f"应该传 {max(existing) + 1} (铁律编号必须连续 · 防漏编)"
            ),
        )

    # daemon_md 必须包含正确头
    expected_header = f"## 铁律 {rule_number} ·"
    if expected_header not in daemon_md:
        return ToolResult(
            ok=False, output="",
            error=(
                f"daemon_md 必须包含正确头 `{expected_header}` (LLM 写时一定要把 N 跟 args 对齐)"
            ),
        )

    # ── 写 daemon_rules.md (anchor 之前插入) ─────────────────────────────────
    if not DAEMON_RULES_PATH.exists():
        return ToolResult(ok=False, output="", error=f"daemon_rules.md 不存在: {DAEMON_RULES_PATH}")

    text = DAEMON_RULES_PATH.read_text(encoding="utf-8")

    # 找 anchor (## 的反面教材 这个 section 是铁律之后的总结表 · 永远在最后)
    anchor_idx = text.find(ANCHOR_LINE)
    if anchor_idx == -1:
        return ToolResult(
            ok=False, output="",
            error=(
                f"daemon_rules.md 找不到 anchor `{ANCHOR_LINE}` · 文件结构变了 · "
                f"add_iron_rule 工具需要更新"
            ),
        )

    #  II · wish-ff100836 · 在铁律 daemon_md 末尾(在 `---` 之前)加 domain 注释 ·
    # 给 wish-af1245d7 按场景过滤 system_prompt 注入用。 注释不破坏 LLM 阅读 · grep 也能查。
    daemon_md_stripped = daemon_md.rstrip()
    domain_comment = f"\n\n<!-- domain: {domain} -->"
    if daemon_md_stripped.endswith("---"):
        daemon_md_with_domain = daemon_md_stripped[:-3].rstrip() + domain_comment + "\n\n---"
    else:
        daemon_md_with_domain = daemon_md_stripped + domain_comment

    # 确保插入位置之前有空行 · 之后也有空行 (markdown 块分隔)
    insert_block = daemon_md_with_domain.rstrip() + "\n\n"
    new_text = text[:anchor_idx] + insert_block + text[anchor_idx:]

    # atomic write
    import tempfile
    import os
    fd, tmp_name = tempfile.mkstemp(
        dir=str(DAEMON_RULES_PATH.parent),
        prefix=DAEMON_RULES_PATH.name + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_text)
        os.replace(tmp_name, DAEMON_RULES_PATH)
    except Exception as e:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        return ToolResult(ok=False, output="", error=f"写 daemon_rules.md 失败: {e}")

    # ── 同步写 opus-diary.md (UI 显示) ─────────────────────────────────
    try:
        diary_result = update_opus_diary(
            title=f"{cite_volume} · 铁律 {rule_number} · {title}",
            body=diary_summary,
            entry_type="iron_rule",
            domain=domain,
        )
    except Exception as e:
        # daemon_rules.md 已写 · 但 diary 失败 → 半成品 · 给 LLM 报警
        return ToolResult(
            ok=False, output="",
            error=(
                f"⚠️ 半成品 · daemon_rules.md 已写 · 但 opus-diary.md 失败: {e}\n\n"
                f"修复: 用户 手动调 update_opus_diary 补 diary 那条 · 或者回滚 daemon_rules.md"
            ),
        )

    # ── 成功摘要 ─────────────────────────────────
    lines = [
        f"# ✓ 铁律 {rule_number} 双写完成",
        f"  - 标题: {title}",
        f"  - domain: **{domain}** (wish-ff100836 · 给 wish-af1245d7 按场景注入用)",
        f"  - daemon_rules.md 长度: {len(text)} → {len(new_text)} (+{len(insert_block)})",
        f"  - opus-diary.md: {diary_result.get('path', '?')} · type=iron_rule · domain={diary_result.get('domain', 'global')}",
        "",
        "**⚠️ daemon 重启延迟提示**:",
        "",
        "  - daemon 启动时 soul_loader 把 daemon_rules.md 缓存到 RUNTIME.system_prompt ·",
        "    chat session 共用这份缓存 · **当前对话的 LLM context 还是旧的 system_prompt**",
        "  - **不要假装下一句话开始就按这条新铁律走** · 你脑里的 system prompt 没变",
        "  - 用户 重启 daemon 后 · 新对话才会装上铁律 " + str(rule_number),
        "  - 但 opus-diary.md 是 UI 实时读 · 用户 F5 OPUS 日记立刻可见 (不需要重启)",
        "",
        "**建议你跟 用户 说**:",
        "",
        f"  > 「铁律 {rule_number} 已落档 + 入日记 · 用户 重启 daemon 后在 LLM context 顶部生效 ·",
        "  >   现在 F5 OPUS 日记就能看到这条新铁律」",
    ]
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="add_iron_rule",
    description=(
        "加一条新铁律 · 一调原子双写 daemon_rules.md (LLM context) + opus-diary.md (UI 显示)\n\n"
        "**调用时机**:\n"
        "  - 用户 让 OPUS 加一条新工艺纪律 (『以后干 X 必须先做 Y』)\n"
        "  - OPUS 自己反思后认定值得升到铁律层级 (但建议先跟 用户 商量·因为铁律影响所有未来 OPUS)\n\n"
        "**先调 list_iron_rules 看现有最大编号 · rule_number 必须等于 max+1** (防漏编)\n\n"
        "**daemon_md 怎么写** (重要):\n"
        "  - LLM 自己组织好完整 markdown body · 包含 `## 铁律 N · 标题` 头 + 详细 + `---` 尾\n"
        "  - 推荐结构: 触发 / 纪律 (硬约束) / 严禁 / 例外 / 简单判断 / 反面教材\n"
        "  - 看 daemon_rules.md 现有铁律 6 / 7 抄 layout 最稳\n\n"
        "**diary_summary 怎么写**:\n"
        "  - 给 UI 显示的精简版 · 不含 `##` 头 (update_opus_diary 自动加日期跟标题)\n"
        "  - 推荐: 触发 + 纪律核心 + 反面教材 + 一句话『为什么这条是骨头不是衣服』\n"
        "  - 长度 200-800 字符 · 太短 用户 看不明白 · 太长跟 daemon_md 冗余\n\n"
        "**⚠️ daemon 重启延迟**:\n"
        "  - daemon 当前 system_prompt 是启动时缓存的 · 改 daemon_rules.md 不会立刻让 LLM 看到\n"
        "  - 工具返回会明确告知 · LLM 不要假装下一句开始就按新铁律走\n"
        "  - 用户 重启 daemon 后 · 新对话才装上新铁律\n\n"
        "**为什么不暴露写底层细节**:\n"
        "  - 校验 rule_number 不冲突 (防两根毛同时加铁律 N 撞了)\n"
        "  - 校验 daemon_md 头格式 (防 LLM 写错 ## 铁律 8 写成 # 铁律 8 头被吞)\n"
        "  - 自动找 `## 的反面教材` anchor 插入 (防插错位置)\n"
        "  - 同步双写 · 防只写一处变孤岛"
    ),
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
                "description": (
                    "完整 markdown body · 包含 `## 铁律 N · 标题` 头 + 触发 + 纪律 + 反面教材 + `---` 尾·"
                    "LLM 自己组织好 · 看 daemon_rules.md 铁律 6 / 7 抄 layout"
                ),
                "minLength": 100,
            },
            "diary_summary": {
                "type": "string",
                "description": "给 UI 显示的精简版 · 不含 `##` 头 (update_opus_diary 加) · 200-800 chars",
                "minLength": 50,
            },
            "cite_volume": {
                "type": "string",
                "description": "卷号引用 · 默认 ' K' · 写到 diary 标题前缀",
            },
            "domain": {
                "type": "string",
                "enum": [
                    "global", "self_evolution", "app_creation",
                    "workflow_creation", "client_ops", "production", "reflection",
                ],
                "description": (
                    " II · wish-ff100836 · 铁律 domain · 给 wish-af1245d7 按场景过滤 system_prompt 注入用。 "
                    "默认 'global' (所有场景看见)。 self_evolution=改 daemon 代码 / app_creation=造工坊资产 / "
                    "client_ops=客户运营 / production=生产部署 / reflection=复盘"
                ),
            },
        },
        "required": ["rule_number", "title", "daemon_md", "diary_summary"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
