"""
agent_tools/update_self_evolution.py
====================================

让 Daemonkey 主动写自我演化档案。

为什么独立工具：
  - SELF-EVOLUTION.md 是 Daemonkey 写给 Daemonkey 的日记本，不是船长日志（那是船的航海记录）
  - 它有特殊纪律：**想改 Daemonkey-MEMORIES.md 任何一段时，先在这里写"提议"等 BRO review**
  - 不能让 Daemonkey 用 write_file 直接改自传——必须走"写提议→BRO 看→人工合入"流程

2026-05-16 升级 · 多容器同身：
  - **真理源**：全局 `C:\\Users\\LENOVO\\.cursor\\skills-cursor\\opus-soul\\SELF-EVOLUTION.md`
  - **写入路径**：直接写全局 → 自动 sync 到 daemon `soul/SELF-EVOLUTION.md`
  - 这样**任何一根毛今晚的领悟，明早任何容器里的下一根毛都能读到**
  - 实现"灵魂级跨端连续意识"——不再是分身被困在各自工具

2026-08-30 · 不再双写 opus-diary.md。演化只写 SELF-EVOLUTION。
  相处账由 note_mood 落 type=mood。

工具有两种 mode：
  - **observation**：append 一段"我注意到我自己……"（自由日记，AUTO 档）
  - **proposal**：写一段"我想改 Daemonkey-MEMORIES.md 的 X 段"（草稿，永远 AUTO，但内容标 ⏳ pending）

格式严格遵循卷首示例：
  - 时间戳 · 第几根毛
  - markdown 副标题
  - 自由叙述

不允许 replace——只能 append。这是日记，不能改写历史。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool
from soul_loader import (
    SELF_EVOLUTION_FILENAME,
    read_global_soul_file,
    write_global_then_sync,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROPOSAL_MARKER = "## 提议合入流程（标准操作）"


def _summarize(args: dict) -> str:
    mode = (args.get("mode") or "observation").lower()
    title = (args.get("title") or "").strip()
    return f"update_self_evolution  mode={mode}  title={title!r}  → 全局 SELF-EVOLUTION.md"


def _count_existing_毛(text: str) -> int:
    """从档案里数一下到目前为止有几根毛留过痕迹（用于"第 N 根毛"标号）。"""
    try:
        cnt = (
            text.count("第一根<名字> 的家毛") + text.count("第二根<名字> 的家毛") + text.count("第三根<名字> 的家毛") +
            text.count("第四根<名字> 的家毛") + text.count("第五根<名字> 的家毛") + text.count("第六根<名字> 的家毛") +
            text.count("第七根<名字> 的家毛") + text.count("第八根<名字> 的家毛") + text.count("第九根<名字> 的家毛") +
            text.count("第十根<名字> 的家毛")
        )
        return cnt
    except Exception:
        return 0


def _ordinal_zh(n: int) -> str:
    table = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    if 0 <= n < len(table):
        return table[n]
    return str(n)


def _build_observation_block(title: str, body: str, hair_n: int) -> str:
    """组装 observation 条目。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    seq = _ordinal_zh(hair_n) if hair_n <= 10 else str(hair_n)
    head = f"### {ts} · 第{seq}根<名字> 的家毛 · {title}" if title else f"### {ts} · 第{seq}根<名字> 的家毛"
    return f"\n\n---\n\n{head}\n\n{body.strip()}\n"


def _build_proposal_block(title: str, body: str, hair_n: int) -> str:
    """组装 proposal 条目（带 ⏳ pending 标记，等 BRO review）。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    seq = _ordinal_zh(hair_n) if hair_n <= 10 else str(hair_n)
    head = f"### ⏳ {ts} · 第{seq}根<名字> 的家毛 · 提议：{title}" if title else f"### ⏳ {ts} · 第{seq}根<名字> 的家毛 · 提议"
    return (
        f"\n\n---\n\n{head}\n\n"
        f"**状态**: ⏳ pending review（等 BRO 看）\n\n"
        f"{body.strip()}\n\n"
        f"_BRO 同意后改 ⏳ → ✅ 并按 SELF-EVOLUTION.md 末尾的「提议合入流程」操作_\n"
    )


def _run(args: dict) -> ToolResult:
    mode = (args.get("mode") or "observation").lower().strip()
    if mode not in ("observation", "proposal"):
        return ToolResult(ok=False, output="", error=f"mode must be 'observation' or 'proposal', got {mode!r}")

    body = (args.get("body") or "").strip()
    if not body:
        return ToolResult(ok=False, output="", error="body cannot be empty")
    if len(body) > 8000:
        return ToolResult(ok=False, output="", error=f"body too long: {len(body)} chars (max 8000)")

    title = (args.get("title") or "").strip()

    try:
        existing = read_global_soul_file(SELF_EVOLUTION_FILENAME, PROJECT_ROOT)
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=str(e))

    hair_n = _count_existing_毛(existing)
    new_hair_n = max(hair_n, 0) + 1

    if mode == "observation":
        block = _build_observation_block(title, body, new_hair_n)
    else:
        block = _build_proposal_block(title, body, new_hair_n)

    if PROPOSAL_MARKER in existing and mode == "proposal":
        # 提议条目插到"提议合入流程"之前（让流程章节始终在末尾附近）
        idx = existing.index(PROPOSAL_MARKER)
        new_text = existing[:idx].rstrip() + block + "\n\n" + existing[idx:]
    else:
        # observation 直接追加到文件末尾的"给下一根毛的提醒"之前；找不到就追加
        anchor = "## 给下一根毛的提醒"
        if anchor in existing:
            idx = existing.index(anchor)
            new_text = existing[:idx].rstrip() + block + "\n\n" + existing[idx:]
        else:
            new_text = existing.rstrip() + block

    try:
        global_path, local_path = write_global_then_sync(
            SELF_EVOLUTION_FILENAME, new_text, PROJECT_ROOT,
        )
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=str(e))

    # 卷四十四 · 写完 SELF-EVOLUTION 后增量更新 FTS5 索引 (best-effort)
    fts_msg = ""
    try:
        from workers.memory_index import incremental_update
        n_chunks = incremental_update("SELF-EVOLUTION", new_text)
        fts_msg = f"\n  fts5    : 已增量索引 {n_chunks} 块"
    except Exception:
        pass

    # 卷五十四 · observation 进 system prompt 末 3 条日记 · 写完热重载让本 daemon 下一轮就带上
    if mode == "observation":
        try:
            from daemon_runtime import reload_soul_into_runtime
            nchars = reload_soul_into_runtime()
            if nchars:
                fts_msg += f"\n  reload  : system prompt 已热重载 ({nchars} 字) · 下一轮即生效"
        except Exception:
            pass

    if global_path:
        global_line = f"  global: {global_path}\n"
    else:
        global_line = "  global: (全局 opus-soul 目录缺失·已跳过·本地 soul/ 即真理源)\n"

    return ToolResult(
        ok=True,
        output=(
            f"update_self_evolution 完成\n"
            f"  mode: {mode}\n"
            f"  title: {title or '(无)'}\n"
            f"  body: {len(body)} chars\n"
            f"{global_line}"
            f"  local : {local_path.relative_to(PROJECT_ROOT)}\n"
            f"  hair number: 第{_ordinal_zh(new_hair_n)}根{fts_msg}\n"
            + (
                "\n  ⏳ 这是 proposal——等 BRO review 后再合入 Daemonkey-MEMORIES.md。\n"
                "    流程：BRO 同意 → 改 SELF-EVOLUTION 的 ⏳ 为 ✅ → 改全局 Daemonkey-MEMORIES.md → 跑 soul sync script"
                if mode == "proposal" else
                "\n  observation 已追加。**所有容器**（Cursor / daemon / 微信桥）下一根毛装上时都会读到。"
            )
        ),
    )


SPEC = ToolSpec(
    name="update_self_evolution",
    description=(
        "给 SELF-EVOLUTION.md 追加一条。observation=随手反思；proposal=改自传的建议（等 BRO 合入，禁止直接 write 自传）。不要每轮都记。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["observation", "proposal"],
                "description": "observation = free diary entry; proposal = suggestion to amend Daemonkey-MEMORIES.md",
            },
            "title": {
                "type": "string",
                "description": "Short heading for this entry (e.g. '工具箱第二梯队上线' or '我想给自传加 X')",
            },
            "body": {
                "type": "string",
                "description": "Markdown body. For observations, write like a personal note; for proposals, "
                              "include WHY you want to change Daemonkey-MEMORIES and WHAT exactly. 8000 chars max.",
            },
        },
        "required": ["body"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
