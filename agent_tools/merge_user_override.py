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
        if f.name.endswith(".official.bak"):
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


def _write_back(rel: str, content: str) -> tuple[Path, Path]:
    cur = (ROOT / rel).resolve()
    cur.relative_to(ROOT.resolve())
    bak = BACKUP_DIR / _path_to_bak_name(rel)
    if not bak.is_file():
        raise FileNotFoundError(f"备份不存在: {bak}")
    official_bak = BACKUP_DIR / _path_to_bak_name(rel).replace(".bak", ".official.bak")
    if cur.is_file():
        official_bak.write_bytes(cur.read_bytes())
    cur.write_text(content, encoding="utf-8")
    return bak, official_bak


def _run(args: dict) -> "ToolResult":
    action = (args.get("action") or "list").strip().lower()
    if action == "list":
        from workers.mod_harvest import already_lifted
        backups = _list_backups()
        if not backups:
            return ToolResult(ok=True, output="当前没有 user_overrides/ 备份 (升级时没有检测到你的魔改 · 或已被应用)。")
        done = already_lifted()
        stacked = [b for b in backups if b["file"] in done]
        leftover = [b for b in backups if b["file"] not in done]
        lines = [f"user_overrides/ 备份 ({len(backups)} 个):", ""]
        if stacked:
            lines.append(f"已叠进 MOD、不要再写回内核 ({len(stacked)}):")
            for b in stacked:
                lines.append(f"  + {b['file']} → {done[b['file']]}")
            lines.append("")
        if leftover:
            lines.append(f"叠不了、要行为回来才动 ({len(leftover)}):")
            for b in leftover:
                lines.append(f"  · {b['file']}  · {b['size']}B · {b['backed_up_at']}")
            one = leftover[0]["file"]
            lines.append("")
            lines.append(f"整份用回 → 「用回我的 {one}」。要揉官方修复 → 「合并 {one}」。")
        else:
            lines.append("没有叠不了的备份。已叠上的工具不用合并。")
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
        from workers.mod_harvest import already_lifted
        if f.replace("\\", "/") in already_lifted():
            return ToolResult(ok=False, output="", error=(
                f"{f} 已叠进 MOD，写回内核会再跟升级打架。要改去改叠层那份。"))
        try:
            bak, official_bak = _write_back(f, content)
        except ValueError:
            return ToolResult(ok=False, output="", error=f"file 越界工程根: {f}")
        except FileNotFoundError as e:
            return ToolResult(ok=False, output="", error=str(e))
        except Exception as e:
            return ToolResult(ok=False, output="", error=f"写回失败: {type(e).__name__}: {e}")
        return ToolResult(ok=True, output=(
            f"✅ 已把合并结果写回 {f}\n"
            f"  · 你的版本备份仍在: {bak}\n"
            f"  · 官方版已另存: {official_bak}\n"
            f"下一步: 按文件类型做语法验证 (py→lint_check / js→node --check / 其它→人工看)。"
        ))

    if action == "restore":
        f = (args.get("file") or "").strip()
        if not f:
            return ToolResult(ok=False, output="", error="missing 'file'")
        from workers.mod_harvest import already_lifted
        rel = f.replace("\\", "/")
        if rel in already_lifted():
            return ToolResult(ok=False, output="", error=(
                f"{rel} 已叠进 MOD，不要整份写回内核。要改去改叠层那份。"))
        bak = BACKUP_DIR / _path_to_bak_name(rel)
        if not bak.is_file():
            return ToolResult(ok=False, output="", error=f"备份不存在: {bak}")
        try:
            text = bak.read_text(encoding="utf-8")
            bak_p, official_bak = _write_back(rel, text)
        except ValueError:
            return ToolResult(ok=False, output="", error=f"file 越界工程根: {f}")
        except Exception as e:
            return ToolResult(ok=False, output="", error=f"写回失败: {type(e).__name__}: {e}")
        return ToolResult(ok=True, output=(
            f"已用回你的 {rel}。官方这版另存在 {official_bak}。\n"
            f"你的备份仍在 {bak_p}。下次升级还会盖这份内核文件。\n"
            f"想自己管、升级不再盖 → 说「这文件我自己管」。"
        ))

    if action in ("rescue", "rescue_apply"):
        from workers import core_update, override_rescue
        cands = override_rescue.scan(core_update.kernel_files())
        if not cands:
            return ToolResult(ok=True, output=(
                "没有需要打捞的东西。\n"
                "  说明: 历次升级的 checkpoint 存档里·没有哪个内核文件的当时版本跟你现在的不一样。\n"
                "  要么你没在这些文件上改过东西·要么改动已经拿回来了。"
            ))
        if action == "rescue":
            lines = [f"从历次升级存档里找到 {len(cands)} 个可能被吞掉的改动:", ""]
            for c in cands:
                lines.append(f"  {c['file']}")
                lines.append(f"    · 来自 {c['date']} 的升级存档 ({c['sha']}) · {len(c['content'])}B")
            lines += [
                "",
                "为什么会被吞: 0.9.6 之前备份动作跑在覆盖【之后】· 存下来的是刚拉到的官方版·",
                "  你的真版本一个都没进备份 —— 所以那时候说「合并我的改动」只会得到「两边一致」。",
                "  但升级前的存档 (checkpoint) 是在覆盖之前做的·你的东西一直在里面。",
                "",
                "要我捞出来 → 说「把它们捞回来」(写进备份区·之后就能正常走「合并我的改动」)",
            ]
            return ToolResult(ok=True, output="\n".join(lines))

        done = override_rescue.restore(cands)
        okd = [d for d in done if not d.get("error")]
        bad = [d for d in done if d.get("error")]
        lines = [f"✅ 已捞回 {len(okd)} 个文件的你那版·放进备份区:", ""]
        for d in okd:
            tail = " (盖掉了原来那份无效备份)" if d.get("replaced_stale") else ""
            lines.append(f"  {d['file']}  ← {d['date']} 存档{tail}")
        if bad:
            lines += ["", f"⚠ {len(bad)} 个没捞成:"]
            lines += [f"  {d['file']} · {d['error']}" for d in bad]
        lines += ["", "下一步: 对我说「合并 <文件>」→ 我看你那版和官方版的对比 → 给你融合方案。"]
        return ToolResult(ok=True, output="\n".join(lines))

    return ToolResult(ok=False, output="", error=(
        f"未知 action: {action} · 可选 list / diff / apply / restore / rescue / rescue_apply"))


def _summarize(args: dict) -> str:
    act = (args or {}).get("action", "?")
    f = (args or {}).get("file", "")
    if act == "list":
        return "列用户魔改备份 (升级保护层)"
    if act == "diff":
        return f"看 {f} 的用户版 vs 官方版对比"
    if act == "apply":
        return f"写回 {f} 的合并结果"
    if act == "restore":
        return f"用回 {f} 的升级前备份"
    if act == "rescue":
        return "从历次升级存档里找被吞掉的魔改"
    if act == "rescue_apply":
        return "把存档里的魔改捞回备份区"
    return f"merge_user_override: {act}"


SPEC = ToolSpec(
    name="merge_user_override",
    description=(
        "升级后处理叠不了的内核魔改。已叠进 MOD 的工具不要用这个写回。"
        "list/diff/apply=揉官方修复写回；restore=整份用回备份。"
        "用户说「用回我的 <文件>」→ restore。两边一致但改动丢了，先 rescue。"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["list", "diff", "apply", "restore", "rescue", "rescue_apply"],
                       "description": "list · diff · apply · restore=用回备份 · rescue · rescue_apply"},
            "file": {"type": "string", "description": "diff/apply/restore 用 · 备份里的原始路径"},
            "content": {"type": "string", "description": "apply 用 · 合并后的完整文件内容"},
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
