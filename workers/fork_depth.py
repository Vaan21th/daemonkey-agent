"""内核分叉深度 · 叠层 vs 浅叉 vs 深叉。

升级该不该让人去「合并我的改动」，取决于改动长在哪一层、有多深。
整文件指纹只能回答「跟官方不一样」；这里补「不一样到什么程度」。
"""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Callable, Optional

D0 = "D0"
D2 = "D2"
D3 = "D3"

SHALLOW_LINES = 40
SHALLOW_HUNKS = 4

OVERLAY_PREFIXES = (
    "agent_tools_user/",
    "api_routes_user/",
    "data/mods/",
)


def is_overlay_path(rel: str) -> bool:
    rel = str(rel or "").replace("\\", "/").lstrip("./")
    if rel.startswith("static/user/") and not rel.endswith("EXAMPLES.js"):
        return True
    return any(rel.startswith(p) for p in OVERLAY_PREFIXES)


def measure_text(official: str, user: str) -> tuple[int, int]:
    """返 (changed_lines, hunks)。changed 取官方/用户两侧较大跨度。"""
    a = (official or "").replace("\r\n", "\n").replace("\r", "\n").splitlines()
    b = (user or "").replace("\r\n", "\n").replace("\r", "\n").splitlines()
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    hunks = 0
    changed = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        hunks += 1
        changed += max(i2 - i1, j2 - j1)
    return changed, hunks


def classify_file(
    rel: str,
    *,
    official_text: Optional[str] = None,
    user_text: Optional[str] = None,
    takeover: bool = False,
    overlay: bool = False,
) -> dict:
    rel = str(rel or "").replace("\\", "/")
    item = {"file": rel, "depth": D3, "changed": 0, "hunks": 0, "reason": ""}
    if overlay or is_overlay_path(rel):
        item["depth"] = D0
        item["reason"] = "叠层目录，升级物理不碰"
        return item
    if takeover:
        item["depth"] = D3
        item["reason"] = "已整文件接管，官方修复不会自动进盘"
        return item
    if official_text is not None and user_text is not None:
        changed, hunks = measure_text(official_text, user_text)
        item["changed"] = changed
        item["hunks"] = hunks
        if changed <= SHALLOW_LINES and hunks <= SHALLOW_HUNKS:
            item["depth"] = D2
            item["reason"] = "浅叉，可合并或迁到 data/mods"
            return item
        item["reason"] = "深叉，整文件 LLM 合并会很费劲"
        return item
    item["reason"] = "内核文件与官方指纹不一致"
    return item


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def classify_pending(
    files: list[str],
    *,
    takeover: set[str] | None = None,
    official_loader: Optional[Callable[[str], Optional[str]]] = None,
    user_root: Optional[Path] = None,
) -> list[dict]:
    taken = takeover or set()
    root = user_root or Path(__file__).resolve().parent.parent
    out = []
    for rel in files:
        rel = str(rel).replace("\\", "/")
        user_text = _read(root / rel)
        official_text = None
        if official_loader is not None:
            try:
                official_text = official_loader(rel)
            except Exception:
                official_text = None
        out.append(classify_file(
            rel,
            official_text=official_text,
            user_text=user_text,
            takeover=rel in taken,
            overlay=is_overlay_path(rel),
        ))
    return out


def format_pending(items: list[dict], *, overlays_intact: list[str] | None = None) -> str:
    """升级预览 / 升级后报告用的人话。"""
    lines: list[str] = []
    intact = overlays_intact or []
    if intact:
        lines.append(f"叠层 MOD 原样保留 ({len(intact)}): " + ", ".join(intact[:8]))
        if len(intact) > 8:
            lines.append(f"  …另 {len(intact) - 8} 个")
        lines.append("这些在 data/mods / agent_tools_user / static/user，官方升级碰不到。")
    d0 = [i for i in items if i["depth"] == D0]
    d2 = [i for i in items if i["depth"] == D2]
    d3 = [i for i in items if i["depth"] == D3]
    if d2:
        lines.append(f"浅叉 D2 ({len(d2)} 个，建议迁到 MOD，或说「合并我的改动」):")
        for i in d2:
            lines.append(f"  ~ {i['file']}  +-{i['changed']} 行 / {i['hunks']} 段")
    if d3:
        lines.append(f"深叉 D3 ({len(d3)} 个，整文件合并费劲；优先拆成 MOD 或对照官方副本):")
        for i in d3:
            extra = f"  +-{i['changed']} 行" if i.get("changed") else ""
            lines.append(f"  ! {i['file']}{extra}  · {i['reason']}")
    if d0 and not intact:
        lines.append(f"叠层 D0 {len(d0)} 个 · 升级不覆盖")
    if not lines:
        return ""
    return "\n".join(lines)


def report_after_update(
    *,
    conflicts: list[dict],
    takeover: list[str],
    incoming: list[dict],
    overlay_names: list[str],
    user_root: Optional[Path] = None,
) -> str:
    root = user_root or Path(__file__).resolve().parent.parent
    items = []
    for row in conflicts:
        rel = str(row.get("file") or "")
        bak = Path(str(row.get("backup") or ""))
        user_text = _read(bak) if bak.is_file() else None
        official_text = _read(root / rel)
        items.append(classify_file(
            rel, official_text=official_text, user_text=user_text, overlay=False,
        ))
    for rel in takeover:
        items.append(classify_file(rel, takeover=True))
    body = format_pending(items, overlays_intact=overlay_names)
    extra = []
    if incoming:
        extra.append("已接管文件的官方新版落在 data/runtime/official_incoming/，可对照摘修复。")
        for row in incoming[:6]:
            extra.append(f"  = {row.get('file')} → {row.get('path')}")
    if not body and not extra:
        if overlay_names:
            return format_pending([], overlays_intact=overlay_names)
        return ""
    return "\n".join([p for p in (body, "\n".join(extra)) if p])
