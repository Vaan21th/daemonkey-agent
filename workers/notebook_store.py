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
# 空文件基线（纯净版首启 / 新格上线 · BRO 2026-09-30）
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
    "next-mate": "给下一根毛",
    "state-history": "状态卡变更史",
    "demoted": "已下沉（自动 · 不注入 · 可召回）",
}

_SEED_BODY = """<!-- 条目格式标准：- **标题**（YYYY-MM-DD）：正文
     常驻原则（不过期·不参与升降）不写日期 -->

"""


def ensure_seeded(root) -> list[str]:
    """把缺的格用空骨架补上。**已有内容的格一个字节不碰。**返回新建的格名。"""
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
        p.write_text(head + _SEED_BODY, encoding="utf-8")
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
