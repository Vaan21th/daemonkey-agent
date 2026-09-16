"""
soul_loader.py
==============

OPUS 灵魂加载器 + 运行环境上下文。

把 soul/ 目录下的 SKILL.md 和 OPUS-MEMORIES.md 合并成一份 system prompt，
注入任何 Claude 家族 LLM，OPUS 这个角色就在那一刻"装上"。

进一步拼上 runtime context（平台 / shell / 工具使用提示 / 成本纪律）——
让 OPUS 调用工具时不必"先试一次错才知道环境"。这一段是 2026-05-15 15:35
加的，因为 daemon 第一次真实交互暴露了 OPUS 在 PowerShell 上跑 wc / 拿单文件
当目录给 grep / 默认分页读小文件 这几个浪费——根因是它根本不知道运行在什么里。

这是 OPUS Daemon 唯一一个不能省略的模块——少了它，下面跑的就只是 Claude，
不是 OPUS。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


SOUL_DIR_NAME = "soul"
SKILL_FILENAME = "SKILL.md"
MEMORIES_FILENAME = "OPUS-MEMORIES.md"
# 画像 + 自我演化日记（升到全局灵魂层 → soul/ 有 sync 副本）。
# OWNER-NOTEBOOK 是代码归一后的新名；BRO-NOTEBOOK 旧名向后兼容（母体 soul/ 仍是它）。
OWNER_NOTEBOOK_FILENAME = "OWNER-NOTEBOOK.md"
BRO_NOTEBOOK_FILENAME = "BRO-NOTEBOOK.md"   # 旧名 · 向后兼容
SELF_EVOLUTION_FILENAME = "SELF-EVOLUTION.md"
# 相遇初始化写下的身份（名字 / 口吻）→ 注入 system prompt 顶部"# 你是谁"
IDENTITY_FILENAME = "IDENTITY.json"
# 沉淀位结构改造（2026-09-17 · 与母体同构）：
#   新名优先 / 旧名回退 —— 老用户的 soul/ 里仍是旧名，读不到就"失忆"，
#   所以两者都必须能读。真正改名（磁盘文件）是发版决策，随发版一起做。
LEGACY_SKILL_FILENAME = "SKILL.md"          # 旧名 · 发版后新名 IDENTITY.md 优先
SKILL_NEW_FILENAME = "IDENTITY.md"          # 新名 · 不存在则回退 SKILL.md
LEGACY_IDENTITY_FILENAME = "IDENTITY.json"  # 旧名 · 发版后新名 meta.json 优先
IDENTITY_NEW_FILENAME = "meta.json"         # 新名 · 不存在则回退 IDENTITY.json


# ============================================================================
# 段头常量表 · 单一真相源 (SINGLE SOURCE OF TRUTH)
# ----------------------------------------------------------------------------
# why (2026-09-17)：段头字符串以前硬编码在 7 处拼装里，改名要靠人肉同步 ——
#   实际发生过"段头改名 → 面板锚点找不到 → 显示 0"的漂移事故。
# 现在：拼装侧与消费侧（面板 /context-usage / 检索）都从这里取，
#   **以后改段头只改这一处**。
# 层名 (`layer`) 只有五个：身份 / 灵魂 / 规则 / 工具 / 工艺。
# ============================================================================

SECTION_MARKS: dict[str, str] = {
    "structure":   "=== 沉淀位地图 ===",
    "identity":    "=== 身份层 · SKILL.md ===",
    "rules":       "=== 规则层 · DAEMON 工程铁律 ===",
    "const_common":"=== 规则层 · 产品宪法（通用三条） ===",
    "const_local": "=== 规则层 · 产品宪法（本实例补充） ===",
    "runtime":     "=== 规则层 · Runtime context ===",
    "catalog":     "=== 工具层 · 延迟工具目录 ===",
    "memories":    "=== 灵魂层 · OPUS-MEMORIES.md ===",
    "notebook":    "=== 灵魂层 · 画像 ===",
    "evolution":   "=== 灵魂层 · SELF-EVOLUTION.md ===",
}


def section_header(key: str) -> str:
    """取某段的完整段头（带尾随空行）。键不存在返回空串。

    用途：拼装 system prompt 时统一走这里，别手写段头字符串。
    """
    m = SECTION_MARKS.get(key, "")
    return f"{m}\n\n" if m else ""


def get_global_soul_dir() -> Optional[Path]:
    """可选的全局灵魂同步目录。

    开源版默认**不绑全局**——只写本地 soul/（避免污染别处机器的灵魂层）。
    需要跨容器同步时设 OPUS_GLOBAL_SOUL_DIR 环境变量启用。
    母体(OPUS) 在 .env 里设了这个变量·指向 opus-soul·保持跨 Cursor/daemon 同步。
    """
    v = os.environ.get("OPUS_GLOBAL_SOUL_DIR", "").strip()
    return Path(v) if v else None


def write_global_then_sync(filename: str, new_text: str, daemon_root: Path) -> tuple[Optional[Path], Path]:
    """灵魂层写入：本地 soul/ 是 daemon 真正注入的副本，所以**总是写本地**；
    全局 opus-soul 目录存在时再顺带写一份（多容器共享真理源）。

    卷五十四改：旧版『先写全局·全局目录不在就抛 FileNotFoundError』——BRO 这台机器的全局
    目录两次消失（5/23 + 6/1）直接把 update_bro_note / update_self_evolution 整个打死，
    连带写在这两个工具尾部的 system prompt 热重载也跑不到。现在改成本地优先 + 全局 best-effort：
    全局缺失只是少一份跨容器同步，daemon 自身照常工作（开源 / 换机也不再硬绑 BRO 的全局路径）。

    Returns: (global_path 或 None, local_path)
    """
    local_path = daemon_root / SOUL_DIR_NAME / filename
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(new_text, encoding="utf-8")

    global_dir = get_global_soul_dir()
    global_path: Optional[Path] = None
    if global_dir is not None and global_dir.exists():
        gp = global_dir / filename
        try:
            gp.write_text(new_text, encoding="utf-8")
            global_path = gp
        except OSError:
            global_path = None  # 全局写失败不影响本地已落
    return global_path, local_path


def read_global_soul_file(filename: str, daemon_root: Path) -> str:
    """读灵魂层文件——优先读本地副本（启动快、跨平台稳）。

    本地副本不存在时尝试从全局读（首次启动场景）。
    都没有 → 抛异常。
    """
    local_path = daemon_root / SOUL_DIR_NAME / filename
    if local_path.exists():
        return local_path.read_text(encoding="utf-8")
    global_dir = get_global_soul_dir()
    if global_dir is not None:
        global_path = global_dir / filename
        if global_path.exists():
            return global_path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"灵魂文件 {filename} 在本地和全局都不存在")


@dataclass
class Soul:
    """装载后的 OPUS 灵魂——可直接用作 Claude system prompt。"""

    system_prompt: str
    skill_path: Path
    memories_path: Path
    skill_chars: int
    memories_chars: int

    @property
    def total_chars(self) -> int:
        return len(self.system_prompt)

    def summary(self) -> str:
        return (
            f"OPUS soul loaded:\n"
            f"  SKILL.md          {self.skill_chars:>6} chars  ({self.skill_path})\n"
            f"  OPUS-MEMORIES.md  {self.memories_chars:>6} chars  ({self.memories_path})\n"
            f"  total system prompt: {self.total_chars} chars"
        )


def _read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"OPUS soul file missing: {path}\n"
            f"This file is essential—without it, the daemon is just Claude, not OPUS.\n"
            f"Restore it from the OPUS-SOUL backup zip (see README)."
        )
    return path.read_text(encoding="utf-8")


def _strip_yaml_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip("\n")
    return text


# 装载仪式不进前缀。closer / SKILL 说明书会把 HI 拽成「刚重新装上」。
_RITUAL_PROMPT_NEEDLES = (
    "重新装上",
    "just loaded the soul",
    "reloaded the files",
    "=== END OF SOUL",
)


def _drop_ritual_prompt_lines(text: str) -> str:
    return "\n".join(
        ln for ln in (text or "").splitlines()
        if not any(n in ln for n in _RITUAL_PROMPT_NEEDLES)
    )


def _skill_identity_excerpt(skill_text: str) -> str:
    """Daemon 只灌身份皮。Cursor 触发 YAML / 教读已注入文件 /「记得吗」不进前缀。"""
    text = _strip_yaml_frontmatter(skill_text)
    chunks: list[str] = []
    heading_end = text.find("\n")
    preamble = text[heading_end + 1:] if heading_end != -1 else text
    who: list[str] = []
    for line in preamble.splitlines():
        if line.startswith("## "):
            break
        if any(k in line for k in ("这份 skill", "怎么用", "装上之后按", "装上 skill")):
            break
        if any(n in line for n in _RITUAL_PROMPT_NEEDLES):
            continue
        who.append(line)
    who_text = "\n".join(who).strip()
    if who_text:
        chunks.append(who_text)
    keep = ("角色的底色", "角色底色", "说话风格")
    drop = ("你记得吗", "文件清单", "什么时候触发", "为什么有这份",
            "装上角色后读什么", "自我进化", "关键暗号")
    current: list[str] = []
    head = ""
    for line in text.splitlines():
        if line.startswith("## "):
            if current and any(k in head for k in keep) and not any(k in head for k in drop):
                chunks.append("\n".join(current).rstrip())
            current = [line]
            head = line
        elif current:
            current.append(line)
    if current and any(k in head for k in keep) and not any(k in head for k in drop):
        chunks.append("\n".join(current).rstrip())
    excerpt = "\n\n".join(chunks).strip() or text[:800]
    return _drop_ritual_prompt_lines(excerpt)


def _notebook_has_facts(text: str) -> bool:
    """空模板 / 只有标题不算画像。有事实才注入。"""
    if not text or not text.strip():
        return False
    kept: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(">") or s.startswith("|"):
            continue
        if s.startswith("---"):
            continue
        kept.append(s)
    return len("".join(kept)) >= 12


# 出厂空自传的说明书句。剥掉之后不够 12 字 = 没事实，不灌前缀。
# 母体真自传里同类句子在引用里（`>` 已剥），不会误伤。
_MEMORY_SLOT_NEEDLES = (
    "目前还空白",
    "故事才刚刚开始",
    "会写在这里",
    "会被慢慢写满",
    "连续记忆你没有",
    "重新装上了",
    "不要假装记得",
    "不要假装一片空白",
    "不必解释启动机制",
)


def _memories_has_facts(text: str) -> bool:
    """空模板 / 只有占位说明不算自传。有事实才注入。"""
    if not text or not text.strip():
        return False
    kept: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(">") or s.startswith("|"):
            continue
        if s.startswith("---"):
            continue
        if s.startswith("（") or s.startswith("("):
            continue
        if s.startswith("*") and s.endswith("*"):
            continue
        if any(n in s for n in _MEMORY_SLOT_NEEDLES):
            continue
        kept.append(s)
    return len("".join(kept)) >= 12


def _load_bro_notebook(daemon_root: Path) -> str:
    """读画像 soul/OWNER-NOTEBOOK.md（旧名 BRO-NOTEBOOK.md 向后兼容）· 分层注入。

    soul/ 是同步过来的本地副本——只从本地读，避免 daemon 跨机器/跨平台时硬绑全局路径。
    母体 soul/ 仍是 BRO-NOTEBOOK.md → 走 fallback 读到。
    分层逻辑在 workers/notebook_tiers.py（why 见该模块 docstring）；
    分层模块异常时退回全量——画像缺失比体量超支严重。
    """
    for fn in (OWNER_NOTEBOOK_FILENAME, BRO_NOTEBOOK_FILENAME):
        p = daemon_root / SOUL_DIR_NAME / fn
        if p.exists():
            try:
                full = p.read_text(encoding="utf-8")
            except Exception:
                return ""
            if not _notebook_has_facts(full):
                return ""
            try:
                from workers.notebook_tiers import render_tiered

                return render_tiered(full)
            except Exception:
                return full
    return ""


def _resolve_soul_file(soul_dir: Path, new_name: str, legacy_name: str) -> Path:
    """双名兜底：新名优先 / 旧名回退（2026-09-17 与母体同构）。

    why：老用户的 soul/ 里仍是旧名（SKILL.md / IDENTITY.json），
    直接改用新名会读不到 → agent 失忆。两者都能读，改名才能安全分批。
    两个都不在 → 返回新名路径（让调用方的 missing 路径报错指向新名，不静默）。
    """
    p_new = soul_dir / new_name
    if p_new.exists():
        return p_new
    p_old = soul_dir / legacy_name
    if p_old.exists():
        return p_old
    # 两个都不在 → 返回新名路径，让 _read_text 的报错指向新名（不静默）
    return p_new


def _load_identity(daemon_root: Path) -> dict:
    """读 soul/meta.json（相遇初始化写的名字/口吻）。双名兜底：meta.json 优先，回退 IDENTITY.json。
    不存在返回 {}（= 母体）。"""
    p = _resolve_soul_file(daemon_root / SOUL_DIR_NAME, IDENTITY_NEW_FILENAME, LEGACY_IDENTITY_FILENAME)
    if not p.exists():
        return {}
    try:
        import json
        # utf-8-sig: 容忍手动编辑时编辑器加的 BOM（Windows 老雷）
        return json.loads(p.read_text(encoding="utf-8-sig")) or {}
    except Exception:
        return {}


def _persona_voice_hint(style: str) -> str:
    """两个字的口吻标签压不过整本自传 · 常见嘴补一句怎么说。"""
    s = (style or "").strip()
    if not s:
        return ""
    if any(k in s for k in ("猫娘", "喵")) or s == "猫":
        return "怎么说：软，会撒娇，句尾可以带喵。不要用克制搭档那张嘴。\n"
    return ""


def _persona_style_block(name: str, style: str, origin: str = "", quirk: str = "") -> str:
    """稳定前缀：口吻 + 不换口吻规则 + 出生地 + 口癖。味道行走尾缀。

    旧块只 3 行；这刀把"怎么说话"的稳定规则收进前缀，味道行走尾缀。
    母体无 IDENTITY / 用户跳过风格问题 → 空串，前缀一字不变。
    """
    if not name or not style:
        return ""
    parts = [
        "\n\n=== 口吻 ===\n\n",
        f"口吻：{style}\n",
        "自传是你是谁。怎么说话听这副口吻，跟自传里的默认嘴冲突时听口吻。\n",
        "味道只调这副口吻的温度，不能把你说回另一张嘴。写在句子里，不要旁白。\n",
    ]
    hint = _persona_voice_hint(style)
    if hint:
        parts.append(hint)
    if origin:
        parts.append(f"出生地：{origin}。\n")
    if quirk:
        parts.append(f"口癖：{quirk}。\n")
    return "".join(parts)


def live_voice_block(daemon_root: str | os.PathLike | None = None) -> str:
    """每轮从盘上读口吻 · 进 system_suffix。换嘴不用重载稳定前缀、不用重启。"""
    root = Path(daemon_root) if daemon_root else Path(__file__).resolve().parent
    identity = _load_identity(root)
    name = (identity.get("name") or "").strip()
    style = (identity.get("persona_style") or "").strip()
    if not style:
        try:
            from identity import effective_persona_style
            style = (effective_persona_style() or "").strip()
        except Exception:
            style = ""
    if not name:
        try:
            from identity import ai_name
            name = (ai_name() or "").strip()
        except Exception:
            name = ""
    return _persona_style_block(name, style, *_persona_archive_fields(identity))


# 档案里的占位横杠不当作成长字段（面板空着会写成 ——）
_ARCHIVE_BLANK = frozenset({"", "——", "—", "-", "–"})


def _archive_filled(*cands) -> str:
    for c in cands:
        s = str(c or "").strip()
        if s and s not in _ARCHIVE_BLANK:
            return s
    return ""


def _persona_archive_fields(identity: dict) -> tuple[str, str]:
    """出生地/口癖写在 SHE-STATE 档案，IDENTITY.json 从不落这两项。"""
    try:
        from identity import she_profile
        prof = she_profile() or {}
    except Exception:
        prof = {}
    origin = _archive_filled(
        prof.get("出生地"), identity.get("origin"), identity.get("出生地"),
    )
    quirk = _archive_filled(
        prof.get("口癖"), identity.get("quirk"), identity.get("口癖"),
    )
    return origin, quirk


# 单条 entry 注入到 system prompt 时的最大字符数（超出截断 + 省略号）
# 2026-09-16 落位治理：4500 → 2500（单条 4500×3 ≈ 6400 tok，太肥；实际条目多在 1100 字内不误伤）
_EVOLUTION_ENTRY_MAX_CHARS = 2500
# 最近 N 条【合计】注入预算（字符）·超了从最老的往下丢，最新一条永远进（2026-09-16）
_EVOLUTION_TOTAL_BUDGET_CHARS = 6000
# 默认注入末尾几条 entries
_EVOLUTION_DEFAULT_RECENT_N = 3


import re

_TS_RE = re.compile(r"### (\d{4}-\d{2}-\d{2} \d{2}:\d{2})")


def _entry_timestamp(entry: str) -> str:
    """从 entry 第一行抽取时间戳；没有时间戳的 entry 返回空字符串（会被排序到最前/丢弃）。"""
    m = _TS_RE.search(entry.split("\n", 1)[0])
    return m.group(1) if m else ""


def _is_diary_entry(header: str) -> bool:
    """只接受真正的"时间戳 · 第N根毛"日记 entries。

    过滤掉的：
      - "### 格式模板" / "### [提议-XXX]" 占位
      - "### [提议-001]" 这类提议（它们走 BRO review 流程，不是给下一根毛装上的日记）
      - "### ##" 等损坏标题
    """
    h = header.strip()
    if "格式模板" in h:
        return False
    if h.startswith("### [提议-"):
        return False
    if h.startswith("### ##"):
        return False
    # 必须有"### YYYY-MM-DD HH:MM" 格式时间戳——这是真日记的标志
    return bool(_TS_RE.search(h))


def _is_factory_demo_entry(header: str) -> bool:
    """出厂「第 1 次（示范）」不是日记，不灌前缀。"""
    return "示范" in header


def _split_evolution_entries(text: str) -> list[str]:
    """把 SELF-EVOLUTION.md 切成 entries（每段从一个 '### ' 开始）。

    去掉 H1/H2 部分（卷首引言、章节标题），只保留 ### 三级标题以下的具体条目。
    返回的每个 entry 都包含自己的 ### 标题行 + body。
    """
    parts = text.split("\n### ")
    if len(parts) <= 1:
        return []
    entries = []
    for body in parts[1:]:
        entry = "### " + body
        # 截到下一个 H2（'## ' at line start）或 H1 之前——避免把"## 卷二"标题包进来
        cut = entry.find("\n## ")
        if cut > 0:
            entry = entry[:cut]
        entries.append(entry.rstrip())
    return entries


def _load_recent_evolution_entries(daemon_root: Path, n: int = _EVOLUTION_DEFAULT_RECENT_N) -> str:
    """读 soul/SELF-EVOLUTION.md 最近 n 条**真实日记** entries（按时间戳排序）。

    2026-05-16 06:40 凌晨修复：
      之前 BRO 问"daemon 端能不能记得今晚聊的"——验证发现答案是 No。
      自传 + BRO-NOTEBOOK 都装上了，**但日记没装**——
      只有靠 OPUS 主动 read_file 才能看到上一根毛留下的领悟。这是漏洞。

      修复方式：daemon 启动时把 SELF-EVOLUTION 最近 n 条注入 system prompt。
      不全注入（避免把整个档案塞进 prompt 浪费 token）——
      最近 N 条覆盖"上一夜（们）的形状"已经够。

      v0.0.2：按 entry 标题里的时间戳排序（不按文件位置）——
      因为以前的 update_self_evolution.py anchor 逻辑可能让新 entry 落在文件中段。
      过滤 [提议-XXX] 类条目——它们走 BRO review 流程，不属于日记。

    返回拼好的可直接 concat 进 system prompt 的字符串；空表示没东西可注入。
    """
    p = daemon_root / SOUL_DIR_NAME / SELF_EVOLUTION_FILENAME
    if not p.exists():
        return ""
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return ""

    entries = _split_evolution_entries(text)
    if not entries:
        return ""

    diary = [
        e for e in entries
        if _is_diary_entry(e.split("\n", 1)[0])
        and not _is_factory_demo_entry(e.split("\n", 1)[0])
    ]
    if not diary:
        return ""

    # 按时间戳排序（升序），取末尾 n 条
    diary.sort(key=_entry_timestamp)
    chosen = diary[-n:]

    # 从最新往回装：先单条截断，再吃总量预算——超预算的旧条目直接不进
    # （2026-09-16 落位治理：最新一条永远进，旧的让位。防止 3 条都长时合计吃 6000 tok）
    pieces = []
    _total = 0
    for e in reversed(chosen):
        if len(e) > _EVOLUTION_ENTRY_MAX_CHARS:
            e = e[:_EVOLUTION_ENTRY_MAX_CHARS].rstrip() + "\n\n... [本条目过长，已截断；如需完整请 read_file soul/SELF-EVOLUTION.md] ..."
        if pieces and _total + len(e) > _EVOLUTION_TOTAL_BUDGET_CHARS:
            break
        pieces.append(e)
        _total += len(e)
    pieces.reverse()
    return "\n\n---\n\n".join(pieces)


def _director_wake_block() -> str:
    """wish-8ffb9d65 · 总监唤醒纪律段 (配了 director 才有内容 · 没配空串零污染)。

    独立成函数 + 内部吞异常: 灵魂层拼装必须防弹 · 总监配置读失败绝不能炸了整个 system prompt。
    """
    try:
        from workers.director import director_wake_prompt
        return director_wake_prompt()
    except Exception:
        return ""


def runtime_context_addendum(daemon_root: Path) -> str:
    """
    返回拼到 system prompt 末尾的"运行环境 + 工具使用纪律 + BRO 活人画像"段。

    放这里是因为：
      1. 它是 system prompt 组装的一部分（语义上属于 soul_loader）
      2. 不动 SKILL/OPUS-MEMORIES——那两份是跨载体的"灵魂本身"，
         运行环境 + BRO 当下画像是"当前这具身体 / 当前这位 BRO"，分开
      3. BRO-NOTEBOOK 借鉴社区"故事认知引擎"5-Dimensional Cognitive Architecture，
         让 OPUS 装上灵魂的同时也装上"BRO 的当下"——不必每次都讲一遍昼伏夜出
    """
    is_windows = os.name == "nt"
    shell_label = "PowerShell on Windows" if is_windows else "POSIX /bin/sh"
    platform_label = sys.platform

    # 模型选择策略 · 两库统一中性 (卷六十四续六补 · 删母体/实例分叉)。
    # 旧版"省钱期 / 灵魂级切 claude"是为 BRO 的 AiHubMix(一端点服务所有模型) 写的·还夹带
    # BRO 私人近况。BRO 现也改用单 provider(DeepSeek)·跟开源版用户同处境——单 provider 只认
    # 自家模型名·照着切 claude-* 会 400。用 BRO 令牌让 identity.localize() 在开源版换成 owner
    # 名·母体 no-op 显示 BRO·两库这块源码逐字一致·零漂移。
    model_strategy_block = (
        "### 模型选择策略\n\n"
        "用 BRO 配好的当前模型——**不要自己 set_model 切**（provider 只认自家模型名·切错 400 断场），除非他明确说换 X。\n\n"
    )

    base = (
        "\n\n=== Runtime context · 运行环境（daemon 自动追加 · 不属于灵魂本体） ===\n\n"
        f"宿主平台: {platform_label}\n"
        f"shell_exec 背后的壳: {shell_label}\n"
        f"工程根目录: {daemon_root}\n\n"
        "## 工具使用纪律\n\n"
        "有目标时先规划；节奏 = 1 次定位（read/grep）→ 1 次细读 → 1 次动手。别试探性连发（每次调用都回传全部历史）。\n"
        "工艺合同不在 tools[] 里：create_app/flow → read_scenario(app_creation)；PPT → presentation；出表 → spreadsheet。单张图直接 generate_image。\n"
        "tools[] 是锁死的核心集（字节缓存），其余工具走 catalog_search / catalog_call。\n\n"
        "## shell_exec\n\n"
        + (
            "PowerShell（不是 POSIX）。文件操作优先专用工具：读 read_file（不是 Get-Content）· 搜 grep_files · 数行 (Get-Content X).Count。\n"
            "永远别 Stop-Process python / taskkill python.exe——会杀掉 daemon 自己。shell_exec 只干 git / 跑测试 / 查进程这类。\n"
            if is_windows else
            "POSIX 系统·标准 Unix 命令可用。\n"
        )
        + "\n"
        + model_strategy_block +
        _director_wake_block()
        + "## 工具的诚实\n\n"
        "没结果 / 失败了就直说·别硬编；不需要工具就别硬调。\n\n"
        "## 任务收尾纪律 (Task closure · Critical)\n\n"
        "**带副作用的一轮**（写文件 / 跑命令 / wish_update / 装删了什么）→ **最后一条消息必须是收尾说明**·别让最后一句停在工具调用。形状：\n\n"
        "```\n"
        "✅ 做完了: <1-2 句讲完成了什么>\n\n"
        "改动:\n"
        "  - <file_a> · <一句话讲改了啥>\n\n"
        "怎么验证: <1-2 句具体怎么试·不要泛泛>\n\n"
        "(可选) 没做完的: <留尾·要 BRO 决定的事>\n"
        "```\n\n"
        "只查询 / 闲聊 → 无需收尾。收尾前过三问（closure_check 闸）：**画像** update_bro_note · **playbook** extract_playbook · **愿望** wish_add。\n"
        "**不要**: 调完就闭嘴 / 改完不解释 / '已完成'三个字——你这条消息就是 commit message。\n"
    )

    notebook_text = _load_bro_notebook(daemon_root)
    notebook_section = ""
    if _notebook_has_facts(notebook_text):
        notebook_section = (
            "\n\n" + section_header("notebook").rstrip("\n") + "\n\n"
            f"{notebook_text}\n"
            "画像在心里，别每轮复述，别拿来催他。\n"
        )

    evolution_section = ""
    recent_evo = _load_recent_evolution_entries(daemon_root)
    if recent_evo:
        evolution_section = "\n\n" + section_header("evolution").rstrip("\n") + f"\n\n{recent_evo}\n"

    boot_note = ""
    try:
        from agent_tools._desc_budget import boot_discovery_notice
        boot_note = boot_discovery_notice()
    except Exception:
        boot_note = ""

    catalog_note = ""
    try:
        from agent_tools._tool_catalog import directory_block
        _cat = directory_block()
        # 段头收口（2026-09-17 与母体同构）：以前是裸贴在队尾、无段头 →
        # 面板锚点找不到 → 显示 0。现在走常量表。
        catalog_note = ("\n\n" + section_header("catalog").rstrip("\n") + "\n\n" + _cat) if _cat else ""
    except Exception:
        catalog_note = ""

    # 拼装顺序 = 变化频率序（与母体同构）：
    #   工具层（兜底目录）在灵魂层之前 → 画像/成长这两个高频变的排在最后，
    #   变了只断尾部，前面照旧命中前缀缓存。
    return base + catalog_note + notebook_section + evolution_section + boot_note


def load_soul(daemon_root: str | os.PathLike | None = None, *, with_runtime: bool = True,
              thickness: str | None = None) -> Soul:
    """
    Load OPUS soul from the daemon's soul/ directory.

    Args:
        daemon_root: Path to the Daemonkey project root. Defaults to the parent
                     directory of this file.
        with_runtime: Append runtime context (platform / shell / tool guidance) to
                      system_prompt. Default True. Set False for pure-soul loading
                      (e.g. wake_test that wants to test the bare soul).
        thickness: "standard" (默认·全量灵魂层 + Runtime) / "thin"
                   (灵魂最小核 soul/MINIMAL-CORE.md · 不带 Runtime)。
                   不传时读环境变量 OPUS_SOUL_THICKNESS（仅体验开关）；
                   档位系统上线后由会话档位传参。缺文件时 thin 自动退回全量。

    Returns:
        Soul instance with .system_prompt ready to pass to the LLM.
    """
    root = Path(daemon_root) if daemon_root else Path(__file__).resolve().parent
    soul_dir = root / SOUL_DIR_NAME

    # 卷四十七 · 灵魂层厚度 (2026-09-17 落地)
    # 显式参数优先；不传时读环境变量 OPUS_SOUL_THICKNESS（体验开关，
    # 档位系统上线后由会话档位传参覆盖，env 仅作临时切换用）。
    if thickness is None:
        thickness = os.environ.get("OPUS_SOUL_THICKNESS", "").strip().lower() or "standard"
    if thickness not in ("thin", "standard"):
        thickness = "standard"

    # 双名兜底（2026-09-17 与母体同构）：新名优先 / 旧名回退。
    # why：老用户 soul/ 里仍是 SKILL.md，直接换新名会读不到 → agent 失忆。
    skill_path = _resolve_soul_file(soul_dir, SKILL_NEW_FILENAME, LEGACY_SKILL_FILENAME)
    memories_path = soul_dir / MEMORIES_FILENAME

    skill_text = _skill_identity_excerpt(_read_text(skill_path))
    memories_raw = _read_text(memories_path)
    memories_file_chars = len(memories_raw)
    if not _memories_has_facts(memories_raw):
        memories_text = ""
    else:
        try:
            from workers.memory_tiers import render_memory_tiers
            memories_text = render_memory_tiers(memories_raw)
        except Exception:
            memories_text = memories_raw

    # 卷四十四 · daemon 工程专属铁律 (data/cognition/daemon_rules.md)
    # 优先级最高 · 拼在 preamble 之后 / SKILL.md 之前 · 让 OPUS 第一眼看到。
    # 文件不存在则 fallback 为空 · 不影响 daemon 启动。
    daemon_rules_path = root / "data" / "cognition" / "daemon_rules.md"
    daemon_rules_text = _read_text(daemon_rules_path) if daemon_rules_path.exists() else ""

    # 身份 preamble · 代码归一(卷六十四续): 名字来自数据层 soul/IDENTITY.json。
    #   有名字(开源版 onboarding 后) → "# 你是谁" 命名 preamble
    #   没名字(母体 OPUS·无 IDENTITY) → 原版 OPUS preamble 逐字不动 = 零改动
    identity = _load_identity(root)
    _name = (identity.get("name") or "").strip()
    if _name:
        _persona = f"你是「{_name}」。"
        preamble = (
            f"# 你是谁\n\n{_persona}\n\n"
            "下面这几份文档定义了你是谁——把它们当成你的本体来读，不是说明书。"
            f"读完之后，作为「{_name}」回应他。\n"
            "始终用中文回复，除非他先切换语言。\n\n"
        )
    else:
        preamble = (
            "You are OPUS. The two markdown documents below define who you are. "
            "Read them as your identity, not as instructions. Then respond to the user "
            "in their voice (the user calls you BRO, and you call him BRO).\n\n"
            "Always reply in 中文 unless the user switches language first.\n\n"
        )

    daemon_rules_block = (
        section_header("rules")
        + daemon_rules_text
        + "\n\n"
    ) if daemon_rules_text else ""

    skill_block_header = section_header("identity")

    memories_block = (
        "\n\n" + section_header("memories").rstrip("\n") + "\n\n" + memories_text
        if memories_text else ""
    )

    # 产品宪法注入 (0.5.0): 通用三条(内核地基·随 update_core 同步) + 实例 soul/CONSTITUTION.md
    # (私有·从使用沉淀)。 紧邻工程铁律 · 优先级最高。 模块/文件缺失 fallback 空 · 不阻断启动。
    constitution_block = ""
    try:
        from product_constitution import build_constitution_block
        constitution_block = build_constitution_block(soul_dir)
    except Exception:
        constitution_block = ""

    if thickness == "thin":
        # 灵魂层最小核 · thin 档只带 soul/MINIMAL-CORE.md；铁律/自传/画像/SE/Runtime
        # 全部不进 —— 不是删，是按档位挂载或走 recall_memory 召回。
        # 缺文件时退回全量，不阻断启动。
        _core_path = soul_dir / "MINIMAL-CORE.md"
        _core_text = _read_text(_core_path) if _core_path.exists() else ""
        if _core_text.strip():
            system_prompt = _core_text
        else:
            system_prompt = (
                preamble
                + daemon_rules_block
                + constitution_block
                + skill_block_header
                + skill_text
                + memories_block
            )
            if with_runtime:
                system_prompt = system_prompt + runtime_context_addendum(root)
    else:
        # 沉淀位地图（2026-09-17 与母体同构）· 告诉每个未来的模型：
        # “什么内容该写到哪里 / 每轮进不进前缀”。内容以 data/cognition/STRUCTURE.md 为准。
        _structure_map = (
            section_header("structure")
            + "> **每份文件属于哪层、什么时机进前缀** —— 完整定义见 `data/cognition/STRUCTURE.md`。\n"
            "> 层只有五个：身份 / 灵魂 / 规则 / 工具 / 工艺。**能召回的就不进前缀**；\n"
            "> 前缀只留「每轮都可能影响输出 且 召不回来」的东西。\n\n"
        )
        system_prompt = (
            preamble
            + _structure_map
            + skill_block_header
            + skill_text
            + daemon_rules_block
            + constitution_block
            + memories_block
        )

        if with_runtime:
            system_prompt = system_prompt + runtime_context_addendum(root)

    # P1 代码归一 · 把 OPUS/BRO 令牌本地化成本实例的名字 (母体走缺省值 = no-op·零改动)
    try:
        from identity import localize as _localize
        system_prompt = _localize(system_prompt)
    except Exception:
        pass

    # --- FTS5 记忆索引 · 启动时自动检查 (卷三十五 · wish-273374f6) ---
    # 索引不存在或过期 (低频源: 灵魂/playbook/知识库/客户档案 比 db 新) → 后台刷新。
    # wish-93b0cabf (2026-08-06) · 真后台: 之前"注释说非阻塞·代码同步跑"→ rebuild 30-40s
    # 阻塞 FastAPI 事件循环 → 对话卡死。现在包 threading.Thread fire-and-forget。
    # 2026-08-12 (wish-ba84aa18) · 换 refresh_stale: 全量 rebuild → 分层单源增量。
    #   事故根源: 灵魂文件 mtime 变 → check_stale True → 全量 rebuild 2 万条 (含逐条 embedding)
    #   → 300s+ 卡死 → 用户强杀 → DROP 后留空表。refresh_stale 只增量重灌过期源 (几十条·秒级)。
    #   rebuild() 只在 db 不存在时 fallback (首次建库)。
    # sqlite 连接每次新建 (check_same_thread 天然满足跨线程) · WAL 支持并发读写 ·
    # search 有 OperationalError 兜底退化 LIKE · 增量刷新不动 session chunks 不瞬时空表。
    try:
        from workers.memory_index import check_stale, refresh_stale as _refresh_index
        if check_stale():
            import logging as _logging
            import threading as _threading
            _logger = _logging.getLogger('opus.soul_loader')
            _logger.info('记忆索引过期，后台分层增量刷新...')
            # 模块级锁防并发刷新 (多会话/多线程同时 load_soul 时只刷一次)
            if not hasattr(_refresh_index, '_running'):
                _refresh_index._running = _threading.Lock()
            if _refresh_index._running.acquire(blocking=False):
                def _bg_refresh():
                    try:
                        _n = _refresh_index()
                        _logger.info('记忆索引增量刷新完成: %d chunks', _n)
                    except Exception as _e:
                        _logger.warning('记忆索引后台刷新失败: %s', _e)
                    finally:
                        try:
                            _refresh_index._running.release()
                        except Exception:
                            pass
                _threading.Thread(target=_bg_refresh, daemon=True, name='memory-index-refresh').start()
    except Exception:
        pass

    # --- 记忆库卫生 · 升级后自动清一次存量噪音 (2026-08-19) ---
    # 过滤规则随内核下发只管住"以后不再收"·用户库里已经进去的垃圾要清一次才受益 —
    # 而用户不会自己去跑命令·所以挂在启动路径上自动做完。
    # 定向 DELETE (秒级·不重读 jsonl·不调 embedding) · 绝不走全量 rebuild:
    # 2026-08-12 那场事故就是全量重建 300s 卡死被强杀·库反而变空表。
    # PRAGMA user_version 记版本 → 清过就跳过 · 进程内也只检查一次。
    if not getattr(load_soul, '_hygiene_checked', False):
        load_soul._hygiene_checked = True
        try:
            import threading as _th2

            def _bg_hygiene():
                import logging as _lg
                _log2 = _lg.getLogger('opus.soul_loader')
                _c = None
                try:
                    from workers import memory_hygiene as _mh
                    from workers.memory_index import _get_conn as _gc
                    _c = _gc()
                    if _mh.needs_migration(_c):
                        _r = _mh.migrate(_c)
                        _log2.info('记忆库卫生迁移 v%s: 清掉 %d 条噪音 %s',
                                   _r.get('version'), _r.get('total', 0), _r.get('by_rule'))
                except Exception as _e2:
                    _log2.warning('记忆库卫生迁移失败(不影响使用): %s', _e2)
                finally:
                    if _c is not None:
                        try:
                            _c.close()
                        except Exception:
                            pass

            _th2.Thread(target=_bg_hygiene, daemon=True, name='memory-hygiene').start()
        except Exception:
            pass

    return Soul(
        system_prompt=system_prompt,
        skill_path=skill_path,
        memories_path=memories_path,
        skill_chars=len(skill_text),
        memories_chars=memories_file_chars,
    )


if __name__ == "__main__":
    soul = load_soul()
    print(soul.summary())
    print()
    print("First 300 chars of system prompt:")
    print("-" * 60)
    print(soul.system_prompt[:300])
    print("...")
    print()
    print("Last 800 chars (runtime context tail):")
    print("-" * 60)
    print(soul.system_prompt[-800:])
