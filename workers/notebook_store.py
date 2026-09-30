"""沉淀位「格子文件」读写单一真源（wish-27273a5b · 2026-09-30）。

一格一文件：`soul/notebook/<section>.md`
文件头声明 section / label / inject / budget_tok。

**所有写入者都走这里** —— 一格一个入口，没有第二条路能写格子文件。
（参照手册 `pb-验写入闸拦住没-先数它装了几道门` 的教训：闸只装一个入口 != 拦住，
  必须确认没有第二入口。）

样板：`data/playbooks/`（一条一文件）+ `soul/IDENTITY.md` / `CONSTITUTION.md`。
目标：**文件边界即格边界** -> 跨格写入没有代码路径（铁律 15「根本不会发生」）。
"""
from __future__ import annotations

import re
from pathlib import Path

NOTEBOOK_DIR = "notebook"

# 装配顺序：进前缀的在前 + 固定字节序，归档的在后（改了只赔自己）
SECTION_ORDER = [
    "understanding",   # ★ 了解层（变动率 0%）
    "about-user",      # ★ 本体约束（变动率 0%）
    "how-we-work",     # ★ 怎么跟他干活（变动率 100% —— 故意排最后）
    "speech-discipline",  # ★ 出声纪律（变动率 0% · 原挂在「我留意的信号」下的子段）
    # ---- 以下不进前缀，只列归档指引 ----
    "state",           # 状态卡（走独立通道注入，不在这里拼）
    "background",
    "stories",
    "moments",
    "archive",
    "watch",
    "changelog",
    "next-mate",
    "state-history",
    "demoted",
]

INJECT_SECTIONS = ("understanding", "about-user", "how-we-work", "speech-discipline")

_HEAD_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def _dir(root) -> Path:
    """接受「工程根」或「soul 目录」两种入参（identity.OwnerNotebook 那条路传的是后者）。"""
    x = Path(root)
    if x.name == "soul":
        return x / NOTEBOOK_DIR
    return x / "soul" / NOTEBOOK_DIR


def parse_header(text: str) -> dict:
    """读文件头 YAML（极简：key: value 单行，不引入 yaml 依赖）。"""
    m = _HEAD_RE.match(text or "")
    if not m:
        return {}
    out: dict = {}
    for line in m.group(1).split("\n"):
        if ":" not in line or line.strip().startswith("#"):
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


def strip_header(text: str) -> str:
    """去掉文件头，只留正文。"""
    m = _HEAD_RE.match(text or "")
    return (text[m.end():] if m else (text or "")).lstrip("\n")


def exists(root: Path, section: str) -> bool:
    return (_dir(root) / (section + ".md")).exists()


def read_section(root: Path, section: str) -> str:
    p = _dir(root) / (section + ".md")
    if not p.exists():
        return ""
    return strip_header(p.read_text(encoding="utf-8"))


def read_header(root: Path, section: str) -> dict:
    p = _dir(root) / (section + ".md")
    if not p.exists():
        return {}
    return parse_header(p.read_text(encoding="utf-8"))


def _normalize_body(body: str, label: str) -> str:
    """归一：去掉正文里所有本级段头 + 开头的格式说明注释。

    write_section 写盘前调它，write_full 比较前也调它 —— **同一把尺**。
    两处用不同尺子时幂等必破（比的是归一后，写的是归一时，永远不等）。
    """
    t = (body or "").strip()
    if label:
        t = re.sub(r"(?m)^##\s+" + re.escape(label) + r"\s*$", "", t)
    return _clean_body(t)


def write_section(root: Path, section: str, body: str, *, header: dict | None = None) -> Path:
    """写一个格。头保留（或按 header 覆盖）。**这是唯一写盘口。**

    写盘前归一（_clean_body）：正文里不该有段头 / 格式说明注释 —— 那些是
    read_full / 文件头的事。存了就会在 read_full 时变双头（历史踩过）。
    """
    d = _dir(root)
    d.mkdir(parents=True, exist_ok=True)
    p = d / (section + ".md")
    if header is None:
        header = parse_header(p.read_text(encoding="utf-8")) if p.exists() else {}
    header.setdefault("section", section)
    if "inject" not in header:
        header["inject"] = "true" if section in INJECT_SECTIONS else "false"
    label = str(header.get("label") or section)
    text = _normalize_body(body, label)
    head = "---\n" + "".join("%s: %s\n" % (k, v) for k, v in header.items()) + "---\n\n"
    p.write_text(head + text.rstrip() + "\n", encoding="utf-8")
    return p


def iter_sections(root: Path):
    """按 SECTION_ORDER 遍历存在的格 -> (section, header, body)。"""
    seen = set()
    for sec in SECTION_ORDER:
        if exists(root, sec):
            seen.add(sec)
            yield sec, read_header(root, sec), read_section(root, sec)
    # 兜底：目录里有 ORDER 没列到的（别丢内容）
    d = _dir(root)
    if d.is_dir():
        for p in sorted(d.glob("*.md")):
            sec = p.stem
            if sec not in seen:
                yield sec, read_header(root, sec), read_section(root, sec)


def inject_text(root) -> str:
    """拼进每轮前缀的部分 = inject=true 的格，按 SECTION_ORDER 顺序。

    带 label 作段头 —— 模型看到「## 了解层（稳定下来的）」才知道这段是什么；
    裸内容没有归属信号（写盘归一剥了 body 里的头，这里补回来）。

    空骨架（只有格式说明注释）不算内容 —— 纯净版首启那 14 个空文件不该被
    当成「画像有东西」而进前缀。
    """
    parts = []
    for sec, hdr, body in iter_sections(root):
        if str(hdr.get("inject", "")).lower() not in ("true", "1", "yes"):
            continue
        b = _clean_body(body)
        if b.strip():
            parts.append("## %s\n\n%s" % (hdr.get("label") or sec, b))
    return "\n\n".join(parts)


def archive_labels(root: Path) -> list[str]:
    """归档格的 label 列表（只列标题，不带字符数 —— 挂在指引里会冲掉前缀缓存）。"""
    out = []
    for sec, hdr, body in iter_sections(root):
        if str(hdr.get("inject", "")).lower() in ("true", "1", "yes"):
            continue
        if not (body or "").strip():
            continue
        label = hdr.get("label") or sec
        out.append(str(label))
    return out


def has_facts(root: Path) -> bool:
    """目录里有没有真内容（空文件不算）。"""
    return bool(inject_text(root).strip())


# --------------------------------------------------------------------------
# 空文件基线（纯净版首启 / 新格上线 · 2026-09-30）
#
# 「纯净版打包时也要有这些基础空文件作为内容落位标准」——
# 保证「一格一文件」从第一天就成立，而不是等第一次写入才凭空长出目录
# （那样长出来的目录是随机的，不是标准的）。
# --------------------------------------------------------------------------

SEED_LABELS = {
    "understanding": "了解层（稳定下来的 · 只有凝练或他明说才写）",
    "about-user": "本体约束 · 关于他 / 怎么相处",
    "how-we-work": "怎么跟他干活",
    "speech-discipline": "出声纪律",
    "state": "状态卡",
    "background": "背景档案（已成背景 · 不再更新）",
    "stories": "他经历的事（日期开头的故事/流水）",
    "moments": "口头记号（称呼、说话习惯、心情图）",
    "archive": "月度长档（长期沉淀）",
    "watch": "我留意的信号（该关照他的地方）",
    "changelog": "改动记录（机器写的操作流水）",
    "next-mate": "给下一个我",
    "state-history": "状态卡变更史",
    "demoted": "已下沉（自动 · 不注入 · 可召回）",
}

_SEED_BODY = """<!-- 条目格式标准：- **标题**（YYYY-MM-DD）：正文
     常驻原则（不过期·不参与升降）不写日期 -->

"""

# 每格的出厂引导（写进新建的格 · 用户/AI 首启即看到「这格装什么、判据是什么」）。
# 全部中性：不出现任何具体的人名 / 项目名 / 母体叙事 —— 发布闸闸 [16] 守这条。
_SEED_BODIES = {
    "understanding": """> 长期模式：跨周稳定的了解（如「作息偏夜型」「对 token 成本敏感」）。
> 唯一写入者：周度凝练 worker（每周最多一次）或用户显式说「记住这个」。
> 判据：这条**跨周还成立吗**？只今天成立 → 去 state / stories，别放这。

""",
    "about-user": """> **这一格只装两样东西**：① **他是谁**（稳定的认知）② **我怎么对他**（相处准则）。
> **工程纪律不装这** —— 「怎么干活」去 `data/cognition/daemon_rules.md`（铁律）或 `scenarios/`（工艺）；「某次任务的临时要求」不要写进来（过期就是垃圾）。
> 判据：**这条会不会改我对「这个人 / 怎么相处」的判断？** 会 → 这里；不会 → 别处。
> 自问一句：**把主语换成别人，这条还成立吗？** 换成别人也成立（例：「用户希望收藏能分类」）→ 那是个产品需求，**不是他这个人** → 走 `wish_add` 或代码注释。

""",
    "how-we-work": """> 这格装「我该怎么开工」—— 授权风格 / 验收标准 / 沟通纪律。
> **不装**：「他是谁、怎么陪他」（→ about-user）·「界面怎么做」（→ wish_add）·「怎么改 daemon」（→ 铁律 / playbook）。
> 判据：这条是在说**他这个人**（→ about-user），还是在说**我干活的方式**（→ 这里）？

""",
    "speech-discipline": """> 这格装「我该什么时候主动开口」—— 出声的信号 / 分寸。
> 判据：这条是「何时该说 / 何时不该说 / 怎么说」，而不是「说什么内容」→ 前者在这，后者去别处。

""",
    "state": """> 8 个骨架字段 · 值=当前状态 · as_of=最后确认日期 · evidence=一句话证据
> 更新走 `update_owner_note(section='state', ...)` · **永不 append 新值，只替换**
> 8 个字段：工作状态 / 作息模式 / 健康基线 / 情绪基线 / 当前主线 / 关系家庭 / 经济预算 / 忌口过敏

""",
    "background": """> 已成背景、不再更新的档案（作息节律 / 协作史 / 性格底色这类**长期稳定**的底面）。
> 判据：**它还会变吗**？会变 → 去 state / stories；基本定型了 → 放这。

""",
    "stories": """> 日期开头的故事 / 流水（含重要度 critical / high / medium / low）。
> 每条格式：`- **标题**（YYYY-MM-DD）：正文`
> 越写越长会拖累预算 —— 旧的交给凝练下沉。

""",
    "moments": """> 听到这些信号，AI 应该立刻「懂」—— 称呼习惯 / 口头记号 / 表达偏好。
> 判据：这条是「听到它就知道该怎么做」的信号吗？会 → 这里。

""",
    "archive": """> 每一段是一段时间的状态压缩。新月份从顶部插入。
> 由凝练定期从 stories / changelog 沉淀过来 —— 保持流水轻量。

""",
    "watch": """> AI 作为伙伴的**预警雷达**：看见这些模式时，该出声时出声，而不是沉默地配合燃烧。
> **这不是给用户贴标签** —— 是长期观察到的、值得关照的结构性模式。
> 判据：这条是「我留意到的、该在关键时刻提一句的信号」吗？是 → 这里。

""",
    "changelog": """> 每次 `update_owner_note` 工具调用 / 用户手动编辑后，在这里加一行。

| 时间 | 谁更新了 | 改了什么 |
|---|---|---|

""",
    "next-mate": """> 给「下一个我」的话：接手时的注意项 / 承诺 / 别踩的坑。
> 判据：这条是「下一个我接手时也该知道」的吗？是 → 这里。

""",
    "state-history": """> 状态字段的变更流水（只记 8 个骨架字段的旧值 → 新值）。

| 字段 | 旧值 → 新值 | as_of | evidence |
|---|---|---|---|

""",
    "demoted": """> 从其它格自动下沉下来的旧条目（不注入 · 可召回）。
> 机器维护，不必手写。

""",
}


def ensure_seeded(root) -> list[str]:
    """把缺的格用出厂骨架补上。**已有内容的格一个字节不碰。**返回新建的格名。

    骨架 = yaml 头 + 该格的引导（_SEED_BODIES）· 不含任何具体人名/项目名 ——
    让首启的 AI 立刻看到「这格装什么、判据是什么」，而不是拿到一堆空白文件靠猜。
    """
    d = _dir(root)
    d.mkdir(parents=True, exist_ok=True)
    created = []
    for sec in SECTION_ORDER:
        p = d / (sec + ".md")
        if p.exists():
            continue
        head = (
            "---\n"
            "section: %s\nlabel: %s\ninject: %s\n"
            "---\n\n" % (sec, SEED_LABELS.get(sec, sec),
                          "true" if sec in INJECT_SECTIONS else "false")
        )
        p.write_text(head + _SEED_BODIES.get(sec, _SEED_BODY), encoding="utf-8")
        created.append(sec)
    return created


def dir_exists(root: Path) -> bool:
    """格子目录在不在（写入方据此决定走不走多格模式）。"""
    return _dir(root).is_dir()


# --------------------------------------------------------------------------
# 兼容层：把多格拼成 / 拆回「逻辑单文件」
#
# 为什么需要：三个写入者（update_bro_note / cognition_loader / update_self_evolution）
# 的全部逻辑（找段·改段·预算·下沉）都围绕「一个文件」写成。拆格后不改它们，
# 只在**读写边界**做一次转换 —— 收益是「一格一个写入入口」自动成立，
# 不用把同一套逻辑在三处各改一遍（改了必然长歪）。
# --------------------------------------------------------------------------

_SECTION_RE = re.compile(r"\n(?=## )")
_LEAD_COMMENT_RE = re.compile(r"\A(?:<!--.*?-->\s*)+", re.S)
_LEAD_HEAD_RE = re.compile(r"\A## [^\n]*\n+")


def _label_map(root: Path) -> dict:
    """label -> section 反查。**不靠猜段头** —— 文件头里的 label 是唯一真源。"""
    m = {}
    for sec, hdr, _ in iter_sections(root):
        m[str(hdr.get("label") or sec)] = sec
        m[sec] = sec
    return m


def _classify(head: str) -> str | None:
    """段头 -> 格 key。锚点表只此一份（notebook_tiers.SECTIONS）。"""
    try:
        from workers.notebook_tiers import SECTIONS
    except Exception:
        return None
    for k, m in SECTIONS.items():
        anchor = getattr(m, "anchor", ()) or ()
        if any(a in head for a in anchor):
            return k
    if "已下沉" in head:
        return "demoted"
    if "状态卡变更史" in head:
        return "state-history"
    return None


def _clean_body(b: str) -> str:
    """剥掉正文开头的「段头」和「格式说明注释」—— 顺序不定，循环剥干净。

    read/write 必须对称：read 剥多少，write 就原样写回多少，否则幂等破掉，
    每次写都 touch 到所有格（跨格隔离就白做了）。
    """
    b = (b or "").strip()
    for _ in range(4):
        b2 = _LEAD_HEAD_RE.sub("", b).strip()
        b2 = _LEAD_COMMENT_RE.sub("", b2).strip()
        if b2 == b:
            break
        b = b2
    return b


def read_full(root: Path) -> str:
    """多格 -> 「逻辑单文件」。

    段头统一用文件头里的 label（read/write 对称，靠 label_map 反查不靠猜）。
    正文里原有的 ## 段头和格式说明注释都剥掉 —— 否则回来时会双头。
    """
    parts = []
    for sec, hdr, body in iter_sections(root):
        b = _clean_body(body)
        if not b:
            continue
        parts.append("## %s\n\n%s" % (hdr.get("label") or sec, b))
    return "\n\n".join(parts) + "\n"


def write_full(root: Path, text: str) -> list[str]:
    """「逻辑单文件」-> 多格。**只写内容真变了的格** —— 别人的格一个字节不碰。"""
    chunks = _SECTION_RE.split(text or "")
    lmap = _label_map(root)
    buckets: dict[str, list[str]] = {}
    order: list[str] = []
    for ch in chunks:
        head = ch.strip().split("\n")[0].lstrip("# ").strip()
        if not head:
            continue
        sec = lmap.get(head) or _classify(head) or "stories"
        if sec not in buckets:
            buckets[sec] = []
            order.append(sec)
        buckets[sec].append(ch)

    changed = []
    for sec in order:
        raw = "\n".join(p.rstrip() for p in buckets[sec]).strip() + "\n"
        hdr = read_header(root, sec)
        label = str(hdr.get("label") or sec)
        if _normalize_body(raw, label) != (read_section(root, sec) or "").strip():
            write_section(root, sec, raw)
            changed.append(sec)
    return changed
