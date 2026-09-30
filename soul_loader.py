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
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# 宪法段头从内核模块取 —— 单一真相源（2026-09-19 wish-50e6d578）。
# why 敢直接 import 不写兜底：product_constitution 是白名单内核文件、只依赖 pathlib，
#   且本文件末尾本来就 import 它（build_constitution_block）——它缺了 daemon 根本起不来；
#   在这里再抄一份兜底字符串，只会让「两张皮」重新长回来（那是本次要杀的病）。
from product_constitution import MARK_CONST_COMMON as _CONST_COMMON_MARK
from product_constitution import MARK_CONST_LOCAL as _CONST_LOCAL_MARK


SOUL_DIR_NAME = "soul"
# 身份入口文档（原 SKILL.md）。2026-09-17 改名 —— 原因：「SKILL」让人误以为是「一项技能」，
# 实际它是「角色入口」（第一轮就让模型装上「我是谁」），与 SKILL 生态撞名。
# 新名优先 · 旧名兜底（照 OWNER-NOTEBOOK 双名做法）· 老用户 soul/ 不被覆盖仍走旧名。
IDENTITY_DOC_FILENAME = "IDENTITY.md"
SKILL_FILENAME = IDENTITY_DOC_FILENAME      # 新名（保留旧变量名供外部引用）
LEGACY_SKILL_FILENAME = "SKILL.md"          # 旧名 · 兜底
MEMORIES_FILENAME = "OPUS-MEMORIES.md"

# 自传是否进前缀（2026-09-18 · wish-0307c26f）：
#   False = 任何档位都不挂，改为按需召回（recall_memory / read_file 取原文）。
#   依据：B-007 实测 移出+召回 30/33=91% ≥ 在前缀 27/33=82%，省 3,440 tok。
#   两个注入点（thin / standard）共用 memories_text —— 改这里两档同时生效，不会漏。
INJECT_MEMORIES = False
# 成长档案（SELF-EVOLUTION）→ 移出前缀（2026-09-19 wish-3ba1c0e2）。
#   为什么：它跟自传同类（都是「我的历史」）—— 自传已按「可召回就不进前缀」移出，
#   它没理由留着。且它的内容跟 playbook 边界不可判定（实际写进去的多是「可照做的
#   工程经验」，该走 extract_playbook）—— 与其加检测判断「这条算不算成长」，
#   不如让它不进前缀：写错了也不伤前缀。
#   全文继续留着：可见 / 可 recall_memory 召回 / 可 read_global_soul_file。
#   省 1,681 tok（原注入 = 最后 3 条 · 单条≤2,500 字 · 合计≤6,000 字）。
INJECT_EVOLUTION = False
# 画像 + 自我演化日记（升到全局灵魂层 → soul/ 有 sync 副本）。
# OWNER-NOTEBOOK 是代码归一后的新名；BRO-NOTEBOOK 旧名向后兼容（母体 soul/ 仍是它）。
OWNER_NOTEBOOK_FILENAME = "OWNER-NOTEBOOK.md"
BRO_NOTEBOOK_FILENAME = "BRO-NOTEBOOK.md"   # 旧名 · 向后兼容
SELF_EVOLUTION_FILENAME = "SELF-EVOLUTION.md"
# 相遇初始化写下的身份（名字 / 口吻）→ 注入 system prompt 顶部"# 你是谁"
# 2026-09-17 改名 IDENTITY.json → meta.json（同名文件里还装 persona_style/narration_pack，
# 不止「identity」）。新名优先 · 旧名兜底。
IDENTITY_FILENAME = "meta.json"            # 新名
LEGACY_IDENTITY_FILENAME = "IDENTITY.json"  # 旧名 · 兜底


# ── 段头常量表（单一真相源 · 2026-09-17 wish-811eb5f5 第6步）────────────────
# why: 段头以前散在本文件各处硬编码，而 api_routes/chat.py 的 /context-usage
#     面板另抄了一份——两边一旦漂移，面板就默默显示 0（SKILL 改名后就这么坏过）。
#     现在拼装与面板共用这张表：**改段头只改这里一处**。
# 面板用它做切块锚点：`_SECTION_MARKS` 按 **出现顺序** 排。
# 状态卡骨架 8 字段 · **单一真相源**（2026-09-30 wish-6e6e561b）
# 为何放内核：PLACEMENT_TABLE（本文件）要拿它列 state_field 枚举，而内核不许依赖 workers/。
# 此前这个枚举被拄了三份（update_bro_note / onboarding.proto_tools / cognition_loader）—— 分叉风险。
STATE_CARD_FIELDS: tuple[str, ...] = (
    "工作状态", "作息模式", "健康基线", "情绪基线",
    "当前主线", "关系家庭", "经济预算", "忌口过敏",
)

# 落位速查表 · 模型每轮在「沉淀位地图」段里看到的就是它 (2026-09-19 wish-a1580b98)
# 为什么要有：实测发现模型**只响应提示词里明确写了的信号** ——
#   工具简介能治「落哪格」(wish 0→12 到 3、rule 0→4 到 2)，但治不了「该不该记」
#   (about-user/stories 组 8/10 压根没调工具)。这张表是给「该记了」装信号。
# 为何定义在内核而不是 workers/：文档侧（workers/prefix_docs.py）要引用它，
#   而内核 import 的 worker 得在白名单里 —— 定义在内核、worker 反向 import 最省事。
PLACEMENT_TABLE = (
    "\n听到这些就记 —— 但先自问：**把主语换成别人，这条还成立吗？**\n"
    "· 他这个人的原则/偏好/边界（换别人不成立）→ update_owner_note(section='about-user')\n"
    "· 怎么跟他干活（授权风格/验收标准/沟通纪律）→ update_owner_note(section='how-we-work')\n"
    "· 带日期的故事/流水 → update_owner_note(section='stories')\n"
    "· 他**当下状态**变化（**只这 8 个**：" + "/".join(STATE_CARD_FIELDS) + "）"
    "→ update_owner_note(section='state', state_field=<8 个之一>, state_value=…, as_of=今天)\n"
    "  ⚠ **8 个之外的不进 state**：项目进展/交付细节 → section='stories'（带日期）· 理解他这个人 → section='about-user' · 想做的功能 → wish_add\n"
    "  （例外：8 条之外**也能进 state**，那就是「涌现长尾」——只收相处中长出的、**不撞这 8 个词根**的了解（口味/倒物/健身）。"
    "有限位：30 天没人碰过就不冉注入，最多 5 格；撞骨架词根的会被直接拒）\n"
    "· 想做的功能/界面/产品改进 → wish_add(title=…, why=…)\n"
    "· 干活硬规矩（「以后一律」「不许」）→ add_iron_rule\n"
    "· 工艺要求/血泪教训（「下次先」「记住了」）→ extract_playbook\n"
    "· 决定不做/否掉的方向（「以后再说」「算了」「不划算」）→ wish_add 落一条 + wish_update(status='rejected', reflection=为什么不做)\n"
    "· 闲聊/一次性请求/纯执行指令 → **不记**（别硬记）\n"
    "\n"
    "**写入格式（任何格 · 一个标准）**：`- **标题**（YYYY-MM-DD）：正文`\n"
    "  · 日期 ISO 写法（`2026-09-30`），只指这条**内容本身的日期**；"
    "引用别人日期（「依据：8/23」）不算\n"
    "  · 常驻原则（不过期、不参与升降）**不写日期** · 要沉的才写日期\n"
    "  · 别写成裸段落（没有 `- ` 开头）· 解析器认不出 = 那条等于不存在\n"
)

SECTION_MARKS = {
    "structure": "=== 沉淀位地图 · 每份文件属于哪层 ===",
    "identity":  "=== 身份层 · IDENTITY.md（我是谁） ===",
    "rules":     "=== 规则层 · DAEMON 工程铁律 (daemon_rules.md · 优先级最高) ===",
    "const_common": _CONST_COMMON_MARK,
    "const_local":  _CONST_LOCAL_MARK,
    "runtime":   "=== 规则层 · Runtime context（运行环境 + 工具纪律 + 收尾） ===",
    "catalog":   "=== 工具层 · 延迟工具目录（不在本轮 tools[] 里的） ===",
    "memories":  "=== 灵魂层 · OPUS-MEMORIES.md（我们的历史） ===",
    "notebook":  "=== 灵魂层 · 画像（关于 BRO · 每轮在场） ===",
    "evolution": "=== 灵魂层 · SELF-EVOLUTION（我的成长） ===",
}


# ── 每段「该不该进前缀」的判据（单一真相源 · 2026-09-19 wish-3ba1c0e2）──────
# why: 前缀里这些块跨了 8 个月长出来，按的都是早期口径（「这个重要→每轮都送」）。
#      「可召回就不进前缀」这条判据是 2026-09-18 才钉死的，旧结构没人回灌 ——
#      结果就是「发现一个、修一个」，依赖人想起来，总会漏。
#      现在把判据跟段头放在一起：**加新段必须在这里登记**（verify_soul 断言守着）。
# 判据（BRO 2026-09-18 拍定）：**能召回的就不进前缀；前缀只留「每轮都可能影响
#      输出且召不回来」的**。
SECTION_META = {
    # key: (层, 该不该进前缀, 为什么)
    "structure":    ("规则层", True,  "路标 · 东西该往哪写 · 每轮定位用 · 不可召回"),
    "identity":     ("身份层", True,  "我是谁 · 每轮在场"),
    "rules":        ("规则层", True,  "约束靠「不必意识到」生效 · 召回是概率性的 · 漏纪律不可接受"),
    "const_common": ("规则层", True,  "产品内核地基（纯净版注入 · 母体有实例宪法则去重）"),
    "const_local":  ("规则层", True,  "本实例产品观（母体六条）"),
    "runtime":      ("规则层", True,  "运行环境 · 每轮都要知道"),
    "catalog":      ("工具层", True,  "不在手边的工具目录 · 不知道就不会用"),
    "memories":     ("灵魂层", False, "可 FTS5 召回 → 移出（AB 实测 91% ≥ 82% · 省 3,440 tok）"),
    "notebook":     ("灵魂层", True,  "对他当下的认知 · 每轮都会影响输出"),
    "evolution":    ("灵魂层", False, "可 FTS5 召回 → 移出（与自传同类 · 省 1,681 tok）"),
}


def section_header(key: str) -> str:
    """拿段头字面量（含尾部换行）· 给拼装用。"""
    return SECTION_MARKS[key] + "\n\n"


def skill_doc_path(soul_dir) -> Path:
    """身份入口文档路径 · 双读（照 identity.owner_notebook_path 的命门写法）。

    新名 soul/IDENTITY.md 优先，缺了回退旧名 soul/SKILL.md。
    老用户 / 母体历史副本没改名 → 永远走旧名，行为逐字不变。
    """
    soul_dir = Path(soul_dir)
    new = soul_dir / IDENTITY_DOC_FILENAME
    if new.exists():
        return new
    return soul_dir / LEGACY_SKILL_FILENAME


def identity_data_path(soul_dir) -> Path:
    """身份数据文件路径 · 双读。新名 meta.json 优先，缺了回退旧名 IDENTITY.json。"""
    soul_dir = Path(soul_dir)
    new = soul_dir / IDENTITY_FILENAME
    if new.exists():
        return new
    return soul_dir / LEGACY_IDENTITY_FILENAME


def get_global_soul_dir() -> Optional[Path]:
    """可选的全局灵魂同步目录。

    开源版默认**不绑全局**——只写本地 soul/（避免污染别处机器的灵魂层）。
    需要跨容器同步时设 OPUS_GLOBAL_SOUL_DIR 环境变量启用。
    母体(OPUS) 在 .env 里设了这个变量·指向 opus-soul·保持跨 Cursor/daemon 同步。
    """
    v = os.environ.get("OPUS_GLOBAL_SOUL_DIR", "").strip()
    return Path(v) if v else None


# 段头粘连自愈 · **落盘前的最后一道闸**（2026-09-30 wish-a266df37）
#
# 病：画像/成长文件里某个段头被吸进上一行末尾（`| 情绪基线 | … | - |## 了解层（…）`、
#     `---## 一、背景档案`）→ 靠 `^## ` 找段头的代码（_find_section / split_tiers /
#     _parse_state_card 的段提取）**看不见那个段** → 内容整段隐形（实测 understanding 解析成 0 条）。
#     且在粘连态下 `find("\n## ")` 找不到下一段头 → 段边界吞掉后面的段（雪崩）。
#
# 为何放这：所有写入者（update_bro_note / update_self_evolution / cognition_loader 的凝练与删条目）
#     都必经 write_global_then_sync —— 卡这一步 = 粘连根本不会落盘（铁律 15：根本不会发生 > 事后拦截），
#     不用再靠事后 fix_headings 补。
#
# 判据窄：只有「前面是句末标点/ `-` / `|` 且 `## xxx` 正好到行尾」才动手；行内引用
#     （`` `## 标题` ``）不匹配。**只加换行，内容一字不动。**
_HEAD_GLUE = re.compile(r"(?m)(?<=[。！？；\-|])(#{2,3} [^#\n][^\n]*?)[ \t]*$")


def heal_headings(text: str) -> tuple[str, list[str]]:
    """把粘连的段头修回行首。返回 (新文本, 被修好的段头列表)。"""
    fixed: list[str] = []

    def _rep(m: "re.Match") -> str:
        head = m.group(1).strip()
        fixed.append(head)
        return "\n\n" + head

    return _HEAD_GLUE.sub(_rep, text), fixed


def write_global_then_sync(filename: str, new_text: str, daemon_root: Path) -> tuple[Optional[Path], Path]:
    """灵魂层写入：本地 soul/ 是 daemon 真正注入的副本，所以**总是写本地**；
    全局 opus-soul 目录存在时再顺带写一份（多容器共享真理源）。

    卷五十四改：旧版『先写全局·全局目录不在就抛 FileNotFoundError』——BRO 这台机器的全局
    目录两次消失（5/23 + 6/1）直接把 update_bro_note / update_self_evolution 整个打死，
    连带写在这两个工具尾部的 system prompt 热重载也跑不到。现在改成本地优先 + 全局 best-effort：
    全局缺失只是少一份跨容器同步，daemon 自身照常工作（开源 / 换机也不再硬绑 BRO 的全局路径）。

    Returns: (global_path 或 None, local_path)
    """
    new_text, _glued_fixed = heal_headings(new_text)   # 落盘前最后一道闸（见 heal_headings）

    # ★ 多格模式（wish-27273a5b）：画像拆成 soul/notebook/ 后，写回各格。
    #   只写内容真变了的格 —— 别人的格一个字节不碰（跨格写入没有代码路径）。
    if filename in (OWNER_NOTEBOOK_FILENAME, BRO_NOTEBOOK_FILENAME):
        try:
            from workers import notebook_store as NS

            if NS.dir_exists(daemon_root):
                NS.write_full(daemon_root, new_text)
                return None, daemon_root / SOUL_DIR_NAME / NS.NOTEBOOK_DIR
        except Exception:
            pass   # 回退老路径：写入不能因为新机制挂了而丢

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
    ★ 多格模式（wish-27273a5b）：画像已拆成 soul/notebook/ 多格，此时合成
    「逻辑单文件」返回，写入者沿用原有找段/改段逻辑，一行不用改。
    """
    if filename in (OWNER_NOTEBOOK_FILENAME, BRO_NOTEBOOK_FILENAME):
        try:
            from workers import notebook_store as NS

            if NS.dir_exists(daemon_root):
                return NS.read_full(daemon_root)
        except Exception:
            pass   # 回退老路径

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
    # ★ 新路径优先：soul/notebook/ 格子目录（一格一文件 · wish-27273a5b）
    #   文件边界即格边界 → 跨格写入没有代码路径。
    try:
        from workers import notebook_store as NS

        NS.ensure_seeded(daemon_root)   # 纯净版首启先落骨架（幂等·不碰有内容的格）
        if NS.has_facts(daemon_root):
            body = NS.inject_text(daemon_root)
            labels = NS.archive_labels(daemon_root)
            if not labels:
                return body
            lines = "\n".join("  - 「%s」" % t for t in labels)
            return (
                body.rstrip()
                + "\n\n---\n\n## 已归档的历史层（每轮不注入 · 按需取回）\n\n"
                + "以下维度是历史流水，已从每轮注入折叠，**全文一字未删**：\n"
                + lines
                + "\n\n取回方式：`recall_memory`（画像全文在记忆索引）"
                "或 `read_file` 画像文件对应维度段。\n"
            )
    except Exception:
        pass   # 回退老路径：画像缺失比体量超支严重

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


def _load_identity(daemon_root: Path) -> dict:
    """读 soul/meta.json（新名）或 soul/IDENTITY.json（旧名·兜底）。不存在返回 {}（= 母体）。"""
    p = identity_data_path(daemon_root / SOUL_DIR_NAME)
    if not p.exists():
        return {}
    try:
        import json
        # utf-8-sig: 容忍手动编辑 IDENTITY.json 时编辑器加的 BOM（Windows 老雷）
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
        "\n\n=== 身份层 · 口吻 ===\n\n",
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
# 2026-09-16 落位治理：4500 → 2500（单条 4500×3 ≈ 6400 tok，太肥；今天实际条目均在 1100 字内不误伤）
_EVOLUTION_ENTRY_MAX_CHARS = 2500
# 最近 N 条【合计】注入预算（字符）·超了从最老的往下丢，最新一条永远进（2026-09-16）
_EVOLUTION_TOTAL_BUDGET_CHARS = 6000
# 默认注入末尾几条 entries
_EVOLUTION_DEFAULT_RECENT_N = 3


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


def runtime_context_addendum(daemon_root: Path, *, parts: bool = False, catalog_exclude=None) -> str | dict:
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
        "\n\n" + section_header("runtime")
        + f"宿主平台: {platform_label}\n"
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
            "\n\n" + section_header("notebook")
            + f"{notebook_text}\n"
            "画像在心里，别每轮复述，别拿来催他。\n"
        )

    evolution_section = ""
    if INJECT_EVOLUTION:          # 2026-09-19 wish-3ba1c0e2 · 移出前缀（why 见常量处）
        recent_evo = _load_recent_evolution_entries(daemon_root)
        if recent_evo:
            evolution_section = f"\n\n{section_header('evolution')}{recent_evo}\n"

    boot_note = ""
    try:
        from agent_tools._desc_budget import boot_discovery_notice
        boot_note = boot_discovery_notice()
    except Exception:
        boot_note = ""

    catalog_note = ""
    try:
        from agent_tools._tool_catalog import directory_block
        catalog_note = directory_block(exclude=catalog_exclude)
    except Exception:
        catalog_note = ""

    # 按内容层分段返回 (2026-09-17 · wish-811eb5f5)：
    #   rules = Runtime（环境 + 工具纪律 + 收尾）
    #   tools = 延迟工具目录 + 启动提示
    #   soul  = 成长 + 画像（都会变 —— 2026-09-19 按“谁变得勤”重排）
    #
    # 缓存友好重排 (2026-09-19 · 前绞分层原则)：缓存按前缀逐字节匹配，
    # 第一个不同处之后全失效 —— 所以“谁会变”决定“谁该靠后”。
    # 画像（update_owner_note 写）比成长（update_self_evolution 写）变得勤得多，
    # 所以画像挪到最末：改一句关于他，只失效它自己那一段，不再秧及成长档案。
    # ⓘ 状态卡不在这里 —— 它那一格 prefix=()，走独立通道注入（见 notebook_tiers.SECTIONS）。
    if parts:
        # wish-e1178ade · 层配置：soul 拆成 evolution / notebook 两个分键（soul 键保留兼容）
        return {"rules": base, "tools": catalog_note + boot_note,
                "evolution": evolution_section, "notebook": notebook_section,
                "soul": evolution_section + notebook_section}
    return base + catalog_note + boot_note + evolution_section + notebook_section


def load_soul(daemon_root: str | os.PathLike | None = None, *, with_runtime: bool = True,
              thickness: str | None = None,
              layers: list[str] | None = None,
              catalog_exclude: set | None = None) -> Soul:
    """
    Load OPUS soul from the daemon's soul/ directory.

    Args:
        daemon_root: Path to the Daemonkey project root. Defaults to the parent
                     directory of this file.
        with_runtime: Append runtime context (platform / shell / tool guidance) to
                      system_prompt. Default True. Set False for pure-soul loading
                      (e.g. wake_test that wants to test the bare soul).
        thickness: "standard" (默认·全量灵魂层 + Runtime) / "thin"
                   (灵魂最小核 soul/MINIMAL-CORE.md ≈566 tok · 不带 Runtime
                    · 2026-09-17 落地 · 实测 22 题三轨 74.1% vs 全量 42-54%)。
                   不传时读环境变量 OPUS_SOUL_THICKNESS（仅体验开关）；
                   档位系统上线后由会话档位传参。缺文件时 thin 自动退回全量。
        layers: 层配置（wish-e1178ade）—— 装哪几段（SECTION_MARKS 键的子集）。
                None = 全装（**逐字节现状 · 零回归路径**）；只作用于 standard 拼装
                （thin 自成一档 · 忽略 layers）。预设（档位）的「装哪几段」从这里进来。
        catalog_exclude: 已全量进 tools[] 的工具集合（wish-9de9bce3 · 精准磨）——
                延迟目录里不再重复列出它们；None = 原样（逐字节现状）。

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

    skill_path = skill_doc_path(soul_dir)
    memories_path = soul_dir / MEMORIES_FILENAME

    skill_text = _skill_identity_excerpt(_read_text(skill_path))
    memories_raw = _read_text(memories_path)
    memories_file_chars = len(memories_raw)
    if not INJECT_MEMORIES:
        memories_text = ""          # 全量存档·靠召回（recall_memory / read_file）
    elif not _memories_has_facts(memories_raw):
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
        "\n\n" + section_header("rules")
        + daemon_rules_text
        + "\n\n"
    ) if daemon_rules_text else ""

    # 沉淀位地图 (2026-09-17 · wish-811eb5f5)：告诉模型每份文件属于哪层、何时在场。
    # 与 data/cognition/STRUCTURE.md 同源 —— 那份是 BRO 与所有模型的共同语言单一真相源。
    # 只进 standard 档（thin 是最小核，不加元信息，保住 746 tok）。
    # 落位速查表见模块级 PLACEMENT_TABLE（内核自持 · worker 反向 import）
    structure_note = (
        "\n\n" + section_header("structure")
        + "身份层  soul/IDENTITY.md —— 我是谁（每轮在场）\n"
        "灵魂层  soul/notebook/ —— 一格一文件 · ★= 进每轮前缀\n"
        "          ★ understanding · about-user · how-we-work · speech-discipline\n"
        "          其余 10 格不进前缀（state/background/stories/moments/archive/watch/\n"
        "          changelog/next-mate/state-history/demoted）· 可 recall_memory 召回\n"
        "        soul/OPUS-MEMORIES.md —— 我们的历史（全量存档·可 recall_memory 召回）\n"
        "        soul/SELF-EVOLUTION.md —— 我的成长（全量存档·可 recall_memory 召回）\n"
        "规则层  data/cognition/daemon_rules.md —— 干活的规矩与红线（每轮在场）\n"
        "工具层  手边 tools[]（完整 schema·每轮）+ 延迟目录（名字+简介·catalog_search 拿详情）\n"
        "工艺层  data/cognition/scenarios/（read_scenario 按需）· data/playbooks/（自动命中）\n"
        "完整定义：data/cognition/STRUCTURE.md\n"
        "逐字全文：data/cognition/PREFIX.md（想看我到底读了什么·直接读它）\n"
        # 落位速查 · 与 workers/prefix_surface.PLACEMENT_TABLE 同源（一份定义·两处用）
        # 2026-09-19 wish-a1580b98：实测模型只响应提示词里写了的信号，加这张表给它装"该记了"的信号
        + (PLACEMENT_TABLE if PLACEMENT_TABLE else "")
        + "\n"
    )

    skill_block_header = section_header("identity")

    memories_block = (
        "\n\n" + section_header("memories") + memories_text
        if memories_text else ""
    )

    # 产品宪法注入 (0.5.0): 通用三条(内核地基·随 update_core 同步) + 实例 soul/CONSTITUTION.md
    # (私有·从使用沉淀)。 紧邻工程铁律 · 优先级最高。 模块/文件缺失 fallback 空 · 不阻断启动。
    constitution_block = ""
    try:
        from product_constitution import build_constitution_block
        if layers is None or thickness == "thin":
            constitution_block = build_constitution_block(soul_dir)
        else:
            constitution_block = build_constitution_block(
                soul_dir,
                include_common=("const_common" in layers),
                include_local=("const_local" in layers),
            )
    except Exception:
        constitution_block = ""

    if thickness == "thin":
        # 灵魂层最小核 (2026-09-17 落地 · wish 三轨实测 74.1% vs 全量 42-54%)。
        # thin 档只带 soul/MINIMAL-CORE.md；铁律/自传/画像/SE/Runtime 全部不进 ——
        # 不是删，是按档位挂载或走 recall_memory 召回。缺文件时退回全量，不阻断启动。
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
                system_prompt = system_prompt + runtime_context_addendum(root, catalog_exclude=catalog_exclude)
    else:
        # 按内容层拼装 (2026-09-17 · wish-811eb5f5)：身份 → 规则 → 工具 → 灵魂。
        # 缓存友好：变化频率低的在前（身份/规则几乎不动；画像/SE 天天变）。
        # 完整层定义：data/cognition/STRUCTURE.md
        _rt_parts: dict = {"rules": "", "tools": "", "soul": ""}
        if with_runtime:
            try:
                _rt_parts = runtime_context_addendum(root, parts=True, catalog_exclude=catalog_exclude)
            except TypeError:      # 旧签名兼容（不该发生，保底）
                _rt_parts["soul"] = runtime_context_addendum(root)
        # 保底：老 parts 只有 soul 键时，evolution/notebook 分键缺位 → 整包归 notebook（内容不丢）
        if _rt_parts.get("evolution") is None and _rt_parts.get("notebook") is None:
            _rt_parts["evolution"], _rt_parts["notebook"] = "", _rt_parts.get("soul", "")

        # wish-e1178ade · 层配置（预设可选装哪几段）：layers=None → 逐字现状（零回归）；
        # 否则按段过滤 —— 全开时拼接顺序与旧版逐字节一致（缓存前缀稳定）。
        _seg_on = (lambda _k: layers is None or _k in layers)
        system_prompt = (
            (preamble if _seg_on("identity") else "")                            # 身份层
            + (structure_note if _seg_on("structure") else "")                   # 元信息 · 沉淀位地图
            + ((skill_block_header + skill_text) if _seg_on("identity") else "")  # 身份层
            + (daemon_rules_block if _seg_on("rules") else "")                   # 规则层
            + (constitution_block if (_seg_on("const_common") or _seg_on("const_local")) else "")
            + (_rt_parts.get("rules", "") if _seg_on("runtime") else "")         # 规则层 · Runtime
            + (_rt_parts.get("tools", "") if _seg_on("catalog") else "")         # 工具层 · 延迟目录
            + (memories_block if _seg_on("memories") else "")                    # 灵魂层 · 自传
            + ((_rt_parts.get("evolution") or "") if _seg_on("evolution") else "")  # 灵魂层 · 成长
            + ((_rt_parts.get("notebook") or "") if _seg_on("notebook") else "")    # 灵魂层 · 画像
        )

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
