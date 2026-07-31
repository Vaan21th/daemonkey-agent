"""
agent_tools/merge_user_override.py · 用户魔改合并工具 (wish-f2f0f9de · B 层)
=====================================================================

升级保护层 B: 用户魔改被官方升级覆盖后 · 把用户版本合并回来。
语义判断交给 OPUS(LLM) · 本工具只做 读备份 / 看对比 / 写回 三个机械动作。

动作:
  list            · 列 data/runtime/user_overrides/ 的备份 (文件 + 大小 + 时间)
  diff  {file}    · 输出 用户版(备份) vs 官方新版(当前文件) 的统一 diff (供 LLM 分析)
  apply {file, content} · 把合并结果写回目标文件 (content = LLM 产出 · 用户已确认)

标准流程 (对话驱动 · OPUS 主持 · 全程询问用户):
  1. 用户说「合并我的改动」→ list 看有哪些备份
  2. 逐个 diff → LLM 分析两边改动:
       - 用户改的区域 ≠ 官方改的区域 → 直接融合 (两边都保留)
       - 同一区域冲突 → 给用户选: 保留我的 / 用官方的 / 融合
  3. 用户确认合并方案 → apply 写回 → 按文件类型语法验证 → 完成

红线:
  - apply 前必须用户明确确认 (这是用户自己的代码 · LLM 不自动改)
  - 写回前 OPUS 自己先 diff 预览给用户看
  - 备份文件永不删除 (应用成功后可提示用户自己清理)
"""

from __future__ import annotations

import difflib
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool

ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / "data" / "runtime" / "user_overrides"

# 备份文件名: 路径下划线化 + .bak (跟 core_update._backup_user_overrides 一致)
def _path_to_bak_name(f: str) -> str:
    return f.replace("/", "__").replace("\\", "__") + ".bak"


def _bak_to_path(name: str) -> Optional[str]:
    """备份文件名 → 原始相对路径 (agent_tools/update_core.py → agent_tools/update_core.py)"""
    if not name.endswith(".bak"):
        return None
    stem = name[:-4]
    return stem.replace("__", "/")


def _list_backups() -> list[dict]:
    if not BACKUP_DIR.is_dir():
        return []
    out = []
    for f in sorted(BACKUP_DIR.iterdir()):
        if not f.is_file() or not f.name.endswith(".bak"):
            continue
        rel = _bak_to_path(f.name)
        if not rel:
            continue
        out.append({
            "file": rel,
            "backup": str(f),
            "size": f.stat().st_size,
            "backed_up_at": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return out


def _run(args: dict) -> "ToolResult":
    action = (args.get("action") or "list").strip().lower()
    if action == "list":
        backups = _list_backups()
        if not backups:
            return ToolResult(ok=True, output="当前没有 user_overrides/ 备份 (升级时没有检测到你的魔改 · 或已被应用)。")
        lines = [f"user_overrides/ 备份 ({len(backups)} 个):", ""]
        for b in backups:
            lines.append(f"  {b['file']}")
            lines.append(f"    · 备份: {b['backup']}")
            lines.append(f"    · {b['size']}B · {b['backed_up_at']}")
        lines.append("")
        lines.append("对某个文件说「合并 <文件>」→ 我看对比 → 给你合并方案。")
        return ToolResult(ok=True, output="\n".join(lines))

    if action == "diff":
        f = (args.get("file") or "").strip()
        if not f:
            return ToolResult(ok=False, output="", error="missing 'file' (备份里的文件路径 · 用 list 看)")
        bak = BACKUP_DIR / _path_to_bak_name(f)
        cur = ROOT / f
        if not bak.is_file():
            return ToolResult(ok=False, output="", error=f"备份不存在: {bak} · 先用 list 看有哪些")
        if not cur.is_file():
            return ToolResult(ok=False, output="", error=f"目标文件不存在: {cur} (官方可能已删它)")
        user_text = bak.read_text(encoding="utf-8", errors="replace").splitlines()
        official_text = cur.read_text(encoding="utf-8", errors="replace").splitlines()
        diff = difflib.unified_diff(
            user_text, official_text,
            fromfile="你的版本 (备份)", tofile="官方新版 (当前)",
            lineterm="",
        )
        diff_text = "\n".join(diff)
        # 统计
        adds = sum(1 for l in diff_text.splitlines() if l.startswith("+") and not l.startswith("+++"))
        dels = sum(1 for l in diff_text.splitlines() if l.startswith("-") and not l.startswith("---"))
        head = (
            f"=== {f} · 你的版本 vs 官方新版 ===\n"
            f"你的版 {len(user_text)} 行 · 官方版 {len(official_text)} 行 · "
            f"差异 +{adds}/-{dels}\n"
            "(- 你的版本独有 · + 官方新版独有 · 空格=两边一致)\n\n"
        )
        return ToolResult(ok=True, output=head + (diff_text[:6000] if diff_text else "(两边完全一致)"))

    if action == "apply":
        f = (args.get("file") or "").strip()
        content = args.get("content")
        if not f or content is None:
            return ToolResult(ok=False, output="", error="missing 'file' + 'content' (合并结果写回目标)")
        bak = BACKUP_DIR / _path_to_bak_name(f)
        cur = ROOT / f
        if not bak.is_file():
            return ToolResult(ok=False, output="", error=f"备份不存在: {bak}")
        # 写回 (先备份当前官方版到 .official 防手抖)
        try:
            official_bak = BACKUP_DIR / _path_to_bak_name(f).replace(".bak", ".official.bak")
            if cur.is_file():
                official_bak.write_bytes(cur.read_bytes())
            cur.write_text(content, encoding="utf-8")
        except Exception as e:
            return ToolResult(ok=False, output="", error=f"写回失败: {type(e).__name__}: {e}")
        return ToolResult(ok=True, output=(
            f"✅ 已把合并结果写回 {f}\n"
            f"  · 你的版本备份仍在: {bak}\n"
            f"  · 官方版已另存: {official_bak}\n"
            f"下一步: 按文件类型做语法验证 (py→lint_check / js→node --check / 其它→人工看) · "
            f"确认 OK 后这文件就是你的魔改+官方修复融合版。"
        ))

    return ToolResult(ok=False, output="", error=f"未知 action: {action} · 可选 list / diff / apply")


def _summarize(args: dict) -> str:
    act = (args or {}).get("action", "?")
    f = (args or {}).get("file", "")
    if act == "list":
        return "列用户魔改备份 (升级保护层)"
    if act == "diff":
        return f"看 {f} 的用户版 vs 官方版对比"
    if act == "apply":
        return f"写回 {f} 的合并结果"
    return f"merge_user_override: {act}"


SPEC = ToolSpec(
    name="merge_user_override",
    description=(
        "用户魔改合并工具 (升级保护层 B · wish-f2f0f9de)。"
        "升级时用户魔改的白名单文件被官方覆盖后 · 备份在 data/runtime/user_overrides/。"
        "本工具: list 列备份 · diff 看用户版vs官方版对比 · apply 写回合并结果。"
        "语义判断由 OPUS 自己做 (读 diff → 分析 → 给用户方案 → 用户确认 → apply)。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "diff", "apply"], "description": "list=列备份 / diff=看某文件对比 / apply=写回合并结果"},
            "file": {"type": "string", "description": "diff/apply 用 · 目标文件路径 (备份里的原始路径)"},
            "content": {"type": "string", "description": "apply 用 · 合并后的完整文件内容"},
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
