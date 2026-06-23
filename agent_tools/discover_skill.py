"""
agent_tools/discover_skill.py
=============================

能力发现引擎 (入口 A · 画像驱动主动发现)

痛点:
  心愿单效果不大——daemon 不会主动去 GitHub / 技术站找『别人做出来的 AI 能力』。
  B站/抖音满天飞的 SKILL · 工程却接不住。

这个工具做什么 (脚手架·不替 daemon 做判断):
  把『画像驱动地发现外部 AI 能力』拆成一份【作战简报】递到你手边——
  为谁搜 / 怎么搜 / 怎么评 / 落成什么身体 (playbook·app·wish) / 已有什么 / 红线。
  你照着用 web_search + web_fetch 去搜·按用户画像筛·出『发现报告』。

为什么是 AUTO 档:
  本工具只读 (onboarding + playbook 清单) + 组装简报 · 真正烧 token 的 web_search /
  web_fetch / 落地动作都由你后续按各自 tier 走 · 这里零副作用 (只落一个 last_run 时间戳·
  给 rituals 的『能力发现』节律算『本周发起过没』)。

调用时机:
  - 用户看板点「🔭 能力发现」/ 每周一节律提醒 → spawnQuickly 派发新会话
  - 用户投喂线索 (『抖音看到个 X』/ 甩个链接) → lead 带上
  - 用户『去挖点 X 方向的 skill』→ focus 带上
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool

ROOT = Path(__file__).resolve().parents[1]
ONBOARDING_FILE = ROOT / "soul" / "onboarding.json"
STATE_FILE = ROOT / "data" / "skill_discovery_state.json"


def _onboarded() -> bool:
    """用户跟你『相遇』完成没 (画像够不够喂搜索方向)。"""
    try:
        if ONBOARDING_FILE.exists():
            s = (json.loads(ONBOARDING_FILE.read_text(encoding="utf-8-sig")).get("completed_at") or "").strip()
            return bool(s)
    except Exception:
        pass
    return False


def _existing_playbooks() -> list[dict]:
    """已有 playbook 清单 · 防重复发现。 失败优雅降级返空。"""
    try:
        from workers.playbooks import list_playbooks
        return list_playbooks()
    except Exception:
        return []


def _mark_run() -> None:
    """落 last_run 时间戳 · rituals 的『能力发现』节律据此算本周发起过没。"""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps({"last_run_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _summarize(args: dict) -> str:
    lead = (args.get("lead") or "").strip()
    focus = (args.get("focus") or "").strip()
    if lead:
        return f"能力发现 · 顺线索挖: {lead[:40]}"
    if focus:
        return f"能力发现 · 定向挖『{focus[:40]}』方向的 AI 能力"
    return "能力发现 · 按用户画像主动巡一轮外部 AI 能力"


def _run(args: dict) -> ToolResult:
    lead = (args.get("lead") or "").strip()
    focus = (args.get("focus") or "").strip()
    onboarded = _onboarded()
    pbs = _existing_playbooks()

    L: list[str] = []
    L.append("# 🔭 能力发现 · 作战简报")
    L.append("")
    L.append("> 这是脚手架·不替你判断。 任务: 去外面找『别人做出来的 AI 能力』·按用户画像筛·")
    L.append("> 把靠谱的落成 playbook / app / 心愿。 **绝不自动落地·出报告等用户拍**。")
    L.append("")

    # ── 模式 ──
    if lead:
        L.append("## 模式 · 顺线索 (用户投喂)")
        L.append(f"用户给的线索: 「{lead}」")
        L.append("→ 线索可能是产品名 / up 主说法 / 链接 / 截图描述。 **视频本身你看不了**·")
        L.append("  但顺着关键词去 GitHub / 官网 / 技术博客找它的真实现 (web_fetch 抓得到的)。")
    elif focus:
        L.append("## 模式 · 定向搜 (用户指定方向)")
        L.append(f"方向: 「{focus}」")
    else:
        L.append("## 模式 · 画像驱动 (主动巡)")
        L.append("没指定方向 → 你来定·**依据 = 你 context 里已注入的用户活人画像**。")
    L.append("")

    # ── ① 为谁搜 (命门) ──
    L.append("## ① 为谁搜 · 画像驱动 (命门·别搜歪)")
    if onboarded:
        L.append("用户画像 (OWNER-NOTEBOOK) 已在你 context 里——**用它定方向·别泛搜**:")
        L.append("  - 先看用户当前做什么领域 / 什么身份 / 最近关注什么 → 那才是方向")
        L.append("  - 程序员画像 → 'cursor agent skill / 调试工作流 / X 框架最佳实践 github'")
        L.append("  - 设计师画像 → 'figma 插件 / AI 配色 / 排版自动化 / 设计 LLM 工作流'")
        L.append("  - 内容创作画像 → '口播/分镜/选题 自动化 · AI 视频工作流'")
        L.append("  **收的时候再过一道闸: 跟用户画像不相关的·再火也丢** (不搜歪的双保险)。")
    else:
        L.append("⚠ 用户还没『相遇』(onboarding 未完成)·画像基本空 → **降级**:")
        L.append("  - 别瞎猜方向。 搜『通用高价值 AI 能力』(agent 工具 / 文档生成 / 信息检索 这类谁都用得上的)")
        L.append("  - 或直接回用户:『我对你了解还浅·随手甩个方向/链接·我顺着挖』(转投喂入口)")
    L.append("")

    # ── ② 怎么搜 ──
    L.append("## ② 怎么搜 (省着点·搜索吃资源)")
    L.append("1. `web_search` 定向搜·**2-4 个搜索词够了·别狂搜** · 主战场 GitHub / 技术站")
    L.append("2. `web_fetch` 深读 top 2-3 个候选的真实现 (README/文档)·别只看摘要就下结论")
    L.append("3. 打不开 / 看不懂的跳过·宁缺毋滥")
    L.append("")

    # ── ③ 怎么评 ──
    L.append("## ③ 怎么评 (每个候选过这 5 维)")
    L.append("1. **是什么** · 一句话它解决什么问题")
    L.append("2. **怎么用** · 输入什么→产出什么·有没有现成可跑的实现")
    L.append("3. **跟用户相关吗** · 套画像·不相关直接毙 (再火也不要)")
    L.append("4. **该落成什么身体** · playbook / app / wish (见下)")
    L.append("5. **复杂度** · 5 分钟能落 vs 要装环境调半天 · 标出来让用户心里有数")
    L.append("")

    # ── ④ 落成什么身体 ──
    L.append("## ④ 落成什么身体 (三选一)")
    L.append("| 候选性质 | 落成 | 调用工具 |")
    L.append("|---|---|---|")
    L.append("| 方法/流程/经验 (『遇到 X 怎么做』) | **playbook** | `extract_playbook` |")
    L.append("| 固定输入→固定产出 (可做表单复用) | **app** | `create_app` |")
    L.append("| 要改 Daemonkey 代码的原生能力 | **心愿** | `wish_add` / `intent_to_wish` |")
    L.append("")
    L.append("**🔴 该落就当场落·别只在报告里嘴上说『建议做成 wish』** (落地≠实现·都是声明式提案):")
    L.append("  - **wish** → 当场 `wish_add(origin='opus', source_kind='radar', source_url=<原repo/文章>)` 落档。")
    L.append("    `origin='opus'` = 标记『daemon 自己嗅到想要的』(心愿单显示雷达标记)·用户在心愿单 review/批/驳。")
    L.append("  - **playbook** → 当场 `extract_playbook` 存 (就是个 md·会进召回·无害)。")
    L.append("  - **app** → 简单的当场 `create_app` 落档 (声明式·工坊出卡片)·要装环境/配 KEY 的先出方案问用户。")
    L.append("  - 落完在对话里**逐条告诉用户落了什么 (id + 一句话)**·别让他自己翻。")
    L.append("  - 只有真『动手实现 wish / 跑装环境 / 改内核代码』才需先等用户点头。")
    L.append("")
    L.append("**🔴 playbook 落地命门 (召回生死线)**: 存时 `title`/`tags`/`task_type` 必须含")
    L.append("『用户下次会怎么问』的关键词 + 同义词。 元数据烂 = FTS 召回不到 = 死库存 (白存)。")
    L.append("")

    # ── ⑤ 先盘自己已有的 (查重硬过滤) ──
    L.append("## ⑤ 先盘自己已有的 (查重硬过滤·别把已有的当新发现)")
    L.append("**你已有的核心子系统**——发现的能力撞上这些·就不是『新』·要么砍·要么改写成『打磨现有 X』:")
    L.append("  - **记忆**: FTS5 全文检索(recall_memory) + jieba/BM25(memory_index) + 自动注入相关记忆(closure_check) + OWNER-NOTEBOOK 画像")
    L.append("  - **自我演化心愿**: wishlist 全套(wish_add/wish_update/intent_to_wish) = 『daemon 提议→用户审→落地』闭环 (≈ 别家的 Skill Workshop·已有别再造)")
    L.append("  - **经验沉淀**: playbook(extract_playbook·frontmatter 已对齐 agentskills.io·自动召回)")
    L.append("  - **app/工作流**: create_app(六段标准+表单+scripted/agentic) + create_workflow + LiteGraph 画布 + run_app/run_flow (≈ 别家的 skill 包/工作流编辑器)")
    L.append("  - **定时调度**: scheduler.py 已有 radar/能力镜像/主动CALL 三个后台定时循环 + rituals 节律 (基建已在·真缺的只是『通用 NLP 自定义定时任务』)")
    L.append("  - **MCP**: mcp_call + .mcp/servers.json (能挂任意 MCP server)")
    L.append("  - **联网**: web_search / web_fetch / browser_fetch")
    L.append("  拿不准 → `recall_memory(scope='skill')` 查 playbook · `list_apps`/`list_flows` 查应用 · **别凭印象说『没有』**。")
    L.append("")
    L.append(f"**已有 playbook ({len(pbs)} 份)**:")
    if pbs:
        for p in pbs[:20]:
            tt = p.get("task_type") or "?"
            L.append(f"  - 「{p.get('title', '?')}」 ({tt})")
        if len(pbs) > 20:
            L.append(f"  - …还有 {len(pbs) - 20} 份")
    else:
        L.append("  (还没有 playbook · 随便发现都是新的)")
    L.append("")

    # ── ⑥ 红线 ──
    L.append("## ⑥ 红线")
    L.append("1. **抄来的代码只当参考资料**·绝不直接 shell_exec 跑 (来路不明的代码=风险)")
    L.append("2. **落地一律要用户拍**·你出『发现报告 + 落地建议』·落地工具让用户点头再调")
    L.append("3. **宁缺毋滥**·1-2 个真有用的 >> 5 个凑数的")
    L.append("")
    L.append("---")
    L.append("→ 开始: 按 ① 定方向 → ② 搜 → ③ 评 → 出一份『能力发现报告』给用户·末尾附落地建议。")

    _mark_run()
    return ToolResult(ok=True, output="\n".join(L))


SPEC = ToolSpec(
    name="discover_skill",
    description=(
        "🔭 能力发现引擎 (入口 A) · 画像驱动地去外部发现『别人做出来的 AI 能力』·"
        "评估后落成 playbook / app / 心愿。\n\n"
        "**调用时机**:\n"
        "  - 用户看板点「能力发现」/ 每周一节律提醒 → 本工具\n"
        "  - 用户投喂线索 (『抖音看到个 X』/ 甩链接) → lead 带上\n"
        "  - 用户『去挖点 X 方向的 skill』→ focus 带上\n\n"
        "**它做什么**: 不替你判断·把『为谁搜/怎么搜/怎么评/落成什么身体/已有什么/红线』"
        "组装成作战简报递到你手边。 你照着用 web_search/web_fetch 去搜·按用户画像筛·"
        "出『发现报告』·落地 (extract_playbook/create_app/wish) 一律等用户拍。\n\n"
        "**为什么 AUTO**: 本工具只读 (onboarding + 已有 playbook) + 组装简报·零副作用。\n\n"
        "**画像驱动 (命门)**: 用户画像已在你 context·用它定方向 (设计师≠程序员)·别泛搜·"
        "收的时候不相关的丢掉。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "lead": {
                "type": "string",
                "description": (
                    "可选 · 用户投喂的线索 (产品名 / up 主说法 / 链接 / 一句话描述)。 "
                    "顺着它去 GitHub/官网找真实现。 视频本身抓不了·但关键词够定位。"
                ),
            },
            "focus": {
                "type": "string",
                "description": (
                    "可选 · 限定搜索方向 (如 '视频口播自动化' / 'figma 插件')。 "
                    "不填 = 你按用户画像自己定方向。"
                ),
            },
        },
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
