"""记忆新陈代谢 · 「谁该退役」的建议器

## 为什么需要它

有限位的格子（画像核心层 / 了解层）满了以后，写入会被预算闸拒掉 ——
但**没人告诉写入者「该腾哪一条」**。BRO 原话：

> 「已经满了的，如何自己清理自己，让他保持可持续的自己维护，或者旧的淘汰之类的」

所以这个模块只干一件事：**把各格的条目扫一遍，按同一把尺打分，给出退役建议。**

## 三条硬约束（都是踩过的坑，别改）

1. **单一判据** —— `retire_score()` 只写一份。定期扫描 / 将来的「写入自救」
   调同一份，不许各写各的（两边建议打架比没建议更糟）。
2. **只出建议，不自动删** —— 满了不自动挪：挪不准（模型判 ≈60% 会错）+
   不可逆（画像不在 git 里，删了回不来）。**人拍板才动手。**
3. **铁律不参与** —— 铁律是「干活纪律」，退役它等于悄悄改行为，那不属于清理。

## 可用的机械信号（2026-09-29 实测）

  ✅ 写入时间 —— 从条目正文里的日期戳/日期前缀解析
  ✅ 格子类型 —— 短命格（state / stories）有 TTL，到点即建议降级
  ❌ 最后召回时间 / 召回次数 —— `memory_index` 表没有这两列（真缺口，见文件尾）
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("opus.memory_reaper")

ROOT = Path(__file__).resolve().parent.parent

# ── 格子的寿命政策（改这里一处，别处不许再抄） ─────────────────────────
#   kind="short": 到 TTL 就建议降级去归档层（它本来就是"当下"的，过期即噪音）
#   kind="long" : 没有 TTL，只在**该格真满了**时按"最冷"提示（这些是稳定的认知）
#   kind="skip" : 不参与退役
SECTION_POLICY: dict[str, dict] = {
    "state":         {"kind": "short", "ttl_days": 30},
    "stories":       {"kind": "short", "ttl_days": 90},
    "understanding": {"kind": "long", "ttl_days": None},
    "about-user":    {"kind": "long", "ttl_days": None},
    "how-we-work":   {"kind": "long", "ttl_days": None},
    "moments":       {"kind": "long", "ttl_days": None},
    "background":    {"kind": "long", "ttl_days": None},
    "watch":         {"kind": "long", "ttl_days": None},
    "archive":       {"kind": "skip", "ttl_days": None},
}

# 条目正文里的日期戳：`（2026-09-17）` / `[2026-09-17]` / 行首 `2026-09-17 · `
_DATE_RE = re.compile(r"(?:^|\D)(\d{4})-(\d{2})-(\d{2})(?:\D|$)")
# 2026-09-29 (第 5 步) · 补两种画像里真在用的写法。
# 实测了解层 7 条里有 4 条写「（依据：8/23）」这种 —— 只认 YYYY-MM-DD 会把它们
# 当「无日期」→ demote_pick 直接 continue → 该沉的沉不掉（假绿：看着安全，实际拖住整个下沉闸）。
_DATE_MD_RE = re.compile(r"(?:^|\D)(\d{1,2})/(\d{1,2})(?:\D|$)")
_DATE_YM_RE = re.compile(r"(?:^|\D)(\d{4})-(\d{2})(?:\D|$)")
# 重要度标记（stories 表格的第三列：**critical** / high / medium / low）
_IMPORTANCE_RE = re.compile(r"\b(critical|high|medium|low)\b", re.I)
# 重要度 → 保留系数（乘在总分上）。critical = 0 表示**永远不建议退役**。
#   踩过的坑：只看日期时，它建议退役的全是 critical —— 「舍不得你」「梦想实现家」
#   那些最珍贵的排在榜首。机械信号得把表里已有的那一列用上。
_IMPORTANCE_KEEP = {"critical": 0.0, "high": 0.3, "medium": 0.7, "low": 1.0}
# bullet 条目：`- **标题**：正文`（了解层 / 本体约束 / 怎么跟他干活 都是这个形状）
_BULLET_RE = re.compile(r"^\s*[-*]\s+(?:\*\*(?P<title>[^*]{1,60})\*\*|(?P<title2>[^：:]{1,60}))[：:]\s*(?P<body>.*)$")

# 第二通道（2026-09-30 wish-66c1eac5）—— 上面那条只认「**标题**：」/「标题：」，
#   **漏掉两类真条目**（实测 how-we-work 4/4、archive 3/3 一条都收不进来）：
#     (a) `- **标题**（2026-09-29）：正文`  ← 括注日期把冒号推后，`[：:]` 匹配不上；
#     (b) `- **标题** —— 正文` / `- 从「A」到「B」——正文`  ← 破折号分隔，没有冒号。
#   后果：那两格对下沉机制**完全隐形** → 永远报「没有可自动下沉的条目」→ 满了卡死循环。
#   只加通道、不动老正则（老行为零影响）。
#   ⚠ 括注日期单独成一个组，**直接从正则取**，不靠「正文任意搜日期」——
#     那会把 `（依据：8/23）` 当条目日期（已被修掉的误判源，见 parse_entries 那段注释）。
_BULLET_RE2 = re.compile(
    r"^\s*[-*]\s+"
    r"(?:\*\*(?P<title>[^*]{1,80})\*\*|(?P<title2>[^：:—*]{1,80}))"
    r"\s*(?:[（(]\s*(?P<date>\d{4}-\d{2}-\d{2})[^）)]{0,30}[）)])?"
    r"\s*(?:[：:]|——|—)\s*"
    r"(?P<body>.*)$"
)


# 第三通道（2026-09-30 wish-66c1eac5 第二刀）—— **裸段落条目**。
#   实测 how-we-work 实装 9 条，只有 4 条写成 `- ` bullet，另 5 条是裸段落：
#     `**验收标准（2026-09-29 他明确）**：长任务收尾 = …`
#     `对外交付的边界（2026-09-29）：Daemonkey 是开源项目…`
#   它们**全带日期**，但对下沉机制完全隐形 → 那格水位一路顶到超预算还沉不动。
#   判据刻意收紧：**必须带 `（YYYY-MM-DD）` 括注** —— 这样续段（`推论：…`）、
#   段头（`## …`）、引用块（`> …`）都不会被误收。
#   不含日期的裸段落仍不收（那是常驻原则 / 说明文字，本就不参与升降）。
_PARA_RE = re.compile(
    r"^(?:\*\*(?P<title>[^*]{1,80})\*\*|(?P<title2>[^：:—*（(>#|]{1,80}))"
    r"\s*[（(]\s*(?P<date>\d{4}-\d{2}-\d{2})[^）)]{0,30}[）)]"
    r"\s*[：:—]\s*(?P<body>.*)$"
)


# ── 格式归一（2026-09-30 wish-66c1eac5 第三刀）──────────────────────────
# 唯一标准（写出来的东西只能长这样）：
#     - **标题**（YYYY-MM-DD）：正文
# 为什么需要：写入端原来是 `section_body.rstrip() + content` —— **模型传什么就落什么**，
#   一个字的格式都不管。于是同一个库里 4 种写法混着（括注位置不同 / 裸段落 / 无 `- `），
#   而读取端正则认不全 → 异形条目对下沉机制隐形 → 那格水位顶到超预算还沉不动。
#   （2026-09-30 实测：how-we-work 实装 9 条，机制只看得见 4 条。）
# 设计原则：**只规范「带日期的条目行」，其余一字不动** ——
#   常驻原则 / 说明文字 / 引用块 / 表格行 / 缩进子项全部原样放过。
#   认不出 → 原样保留（宁可留，不要改坏）。
_ENTRY_HEAD_RE = re.compile(
    r"^(?:[-*]\s+)?(?:\*\*(?P<t1>[^*]{1,80})\*\*|(?P<t2>[^：:—*（(【>#|]{1,80}))"
    r"\s*(?P<datepart>[（(【]\s*\d{4}-\d{2}-\d{2}\s*[^）)】]{0,40}[）)】])"
    r"\s*(?:[：:]|——|—)\s*(?P<body>.*)$"
)
# 已达标的标准形：`- **标题**（YYYY-MM-DD）：正文`（含括注里带补充说明的写法）# 形态 B：日期写在粗体**里面** —— `- **验收标准（2026-09-29 他明确）**：正文`
#   实测 how-we-work 里真在用，必须拆出来（否则整条隐形）。
_BOLD_DATE_RE = re.compile(
    r"^(?P<lead>[-*]\s+)?\*\*(?P<t>[^*]{1,80}?)\s*"
    r"[（(]\s*(?P<d>\d{4}-\d{2}-\d{2})(?P<xtra>[^）)]{0,40})[）)]\*\*"
    r"\s*[：:]\s*(?P<body>.*)$"
)
# 形态 C：方括号标题 + 裸日期 —— `【排版偏好 · 标题断行】2026-09-29 正文`
_BRACKET_DATE_RE = re.compile(
    r"^(?P<lead>[-*]\s+)?【(?P<t>[^】]{1,60})】\s*(?P<d>\d{4}-\d{2}-\d{2})\s*(?P<body>.*)$"
)


_STD_ENTRY_RE = re.compile(
    r"^- \*\*[^*]{1,80}\*\*（\d{4}-\d{2}-\d{2}(?:[·:：][^）)]{0,30})?）[：:]\s*.*$"
)


def normalize_entries(text: str) -> tuple[str, list[str]]:
    """把条目行统一成 `- **标题**（YYYY-MM-DD）：正文`。返回 (新文本, 改动描述)。

    只动「带 `（YYYY-MM-DD）` 括注的条目行」；其余行一字不改。
    认不出的原样保留 —— 宁可留着，也不要改坏用户内容。
    """
    out_lines: list[str] = []
    changed: list[str] = []
    for raw in (text or "").split("\n"):
        body_line = raw.rstrip()
        strip = body_line.strip()
        if not strip or _STD_ENTRY_RE.match(strip):
            out_lines.append(body_line)
            continue
        # 形态 B / C 先拆（判据比通用形宽，先跑免得被误判）
        _hit_bc = False
        for _re in (_BOLD_DATE_RE, _BRACKET_DATE_RE):
            mb = _re.match(strip)
            if not mb:
                continue
            _t = mb.group("t").strip()
            _x = (mb.groupdict().get("xtra") or "").strip("·:： ·")
            _extra = (" · " + _x) if _x else ""
            newline = f"- **{_t}**（{mb.group('d')}{_extra}）：{mb.group('body').strip()}"
            if newline != strip:
                changed.append(_t)
            out_lines.append(newline)
            _hit_bc = True
            break
        if _hit_bc:
            continue
        m = _ENTRY_HEAD_RE.match(strip)
        if not m:
            out_lines.append(body_line)
            continue
        title = (m.group("t1") or m.group("t2") or "").strip()
        if not title or title.startswith("**"):
            out_lines.append(body_line)
            continue
        dm = re.search(r"\d{4}-\d{2}-\d{2}", m.group("datepart"))
        if not dm:
            out_lines.append(body_line)
            continue
        tail = m.group("datepart")
        tm = re.search(r"[·:：]\s*([^）)】]+)", tail) or re.search(r"[（(【]\s*\d{4}-\d{2}-\d{2}\s+([^）)】]+)[）)】]", tail)
        extra = (" · " + tm.group(1).strip()) if tm else ""
        newline = f"- **{title}**（{dm.group(0)}{extra}）：{m.group('body').strip()}"
        if newline != strip:
            changed.append(title)
        out_lines.append(newline)
    return "\n".join(out_lines), changed


def _parse_date(text: str) -> datetime | None:
    s = text or ""
    m = _DATE_RE.search(s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except ValueError:
            return None
    # 2026-08 → 当月 1 号（判据只拿它算「多老了」· 精度够用）
    m = _DATE_YM_RE.search(s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), 1, tzinfo=timezone.utc)
        except ValueError:
            return None
    # 8/23 → 今年 8 月 23（画像里的短日期一般指近期）
    m = _DATE_MD_RE.search(s)
    if m:
        mo, dy = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= dy <= 31:
            try:
                return datetime(datetime.now(timezone.utc).year, mo, dy, tzinfo=timezone.utc)
            except ValueError:
                return None
    return None


def _looks_like_date_cell(c: str) -> bool:
    """这一列是不是「基本就是个日期」（状态卡的 as_of 列）。

    不用长度阀值 —— 长度会误伤：`2026-05-16 02:49` 是 16 字符，是正常日期格。
    改判「挖掉日期后剩下什么」：剩中文 = 那是正文（如 `自由身@2026-09-18`），不是日期列。
    """
    left = _DATE_RE.sub("", c or "").strip(" ·-—/[]()、")
    return len(left) <= 8 and not re.search(r"[\u4e00-\u9fff]", left)


def parse_entries(section_text: str) -> list[dict]:
    """把一段画像正文拆成 [{title, body, line, date}] · 只认 bullet 形状的条目。

    `date` 带**继承**：stories 的日期写在 `### 2026-08-11 15:24` 这种子标题上，
    不在 bullet 上 —— 不继承的话那格的 TTL 永远是 0 分（实测踩过：12/12 解析不出）。
    """
    out: list[dict] = []
    cur: datetime | None = None
    for raw in (section_text or "").splitlines():
        s = raw.strip()
        if s.startswith("#"):
            d = _parse_date(s)
            if d:
                cur = d
            continue
        # 表格行（stories 段是 `| 时间 | 事件 | 重要度 |`）—— 日期在第一列。
        #   只收「能解出日期」的行，表头/分隔行自然被挡在外。
        # 2026-09-30 wish-6e6e561b：以前只认第一列 —— 于是**状态卡的涌现行**
        #   （`| 字段 | 当前值 | as_of | 依据 |`，日期在第三列）一条都解不出来
        #   → SECTION_POLICY['state'] 的 ttl_days=30 形同虚设（设计意图早就在，路没通）。
        #   改为**掃前几列**，但只认「短得像日期」的格（日期列不会长）—— 别把正文里的日期当事。
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) >= 2:
                d = _parse_date(cells[0]) if cells else None     # 老行为：第一列（stories 形状）
                if d is None:
                    for c in cells[:5]:                          # 新：找个「基本就是个日期」的列
                        if c and _looks_like_date_cell(c):
                            d = _parse_date(c)
                            if d:
                                break
                if d:
                    # title 取「第一个不是日期的列」—— 不能写死 cells[1]：
                    #   stories = `| 时间 | 事件 | 重要度 |` → cells[1] 对
                    #   状态卡 = `| 字段 | 当前值 | as_of | 依据 |` → cells[1] 是「当前值」（错！
                    #     拿着「v」「-」当标题，下方 _protect 保护名单就永远匹配不上）。
                    _others = [c for c in cells if c and _parse_date(c) is None]
                    _title = (_others[0] if _others else cells[0])[:60]
                    out.append({"title": _title,
                                "body": " ".join(cells), "line": s, "date": d})
            continue
        m = _BULLET_RE.match(raw)
        if m:
            title = (m.group("title") or m.group("title2") or "").strip()
            if title and not title.startswith("**"):
                out.append({"title": title,
                            "body": (m.group("body") or "").strip(),
                            "line": s,
                            "date": _parse_date(title) or cur})
                continue
        # 第二通道（见 _BULLET_RE2 注释）。走到这里有两种情况：
        #   · 老正则压根没中（真正的新写法）
        #   · 老正则中了、但产出的是 `**…**（2026-09-29）` 这种「假标题」——
        #     包注日期把冒号推后时，老正则的 title2 分支会把整个 `**标题**（日期）` 吃进 title，
        #     再被 `startswith("**")` 排除。**不补这一条，第二通道永远轮不到**（本次踩到）。
        m2 = _BULLET_RE2.match(raw)
        if m2:
            _t2 = (m2.group("title") or m2.group("title2") or "").strip()
            if _t2 and not _t2.startswith("**"):
                _d2 = m2.group("date")
                out.append({"title": _t2,
                            "body": (m2.group("body") or "").strip(),
                            "line": s,
                            "date": _parse_date(_d2) if _d2 else cur})
                continue
        # 第三通道（裸段落条目 · 见 _PARA_RE）：不带 `- ` 前缀、但带 `（日期）` 的真条目。
        #   判据刻意要求必须有括注日期 —— 续段（`推论：…`）与说明文字自然落空。
        m3 = _PARA_RE.match(s)
        if m3:
            _t3 = (m3.group("title") or m3.group("title2") or "").strip()
            if _t3 and not _t3.startswith("**"):
                _d3 = m3.group("date")
                out.append({"title": _t3,
                            "body": (m3.group("body") or "").strip(),
                            "line": s,
                            "date": _parse_date(_d3) if _d3 else cur})
                continue
        # （原「兜底」分支已删 —— 它是 `if not m2: continue` 之后的不可达代码，
        #   2026-09-30 改控制流后暴露成 NPE；语义已被上面三条通道完全覆盖。）
    return out


def retire_score(entry: dict, section_key: str, *, now: datetime | None = None) -> float:
    """给一条记忆打分 · **越高越该退役**（0 = 别动它）。

    唯一的尺 —— 定期扫描和写入自救都调这一份。
    """
    pol = SECTION_POLICY.get(section_key, {"kind": "long", "ttl_days": None})
    if pol["kind"] == "skip":
        return 0.0

    now = now or datetime.now(timezone.utc)
    score = 0.0

    # ① 格子类型：短命格有 TTL，过期就开始计分（越久越高，封顶 60）
    ttl = pol.get("ttl_days")
    age_days = None
    dt = (entry.get("date")
          or _parse_date(entry.get("body", "")) or _parse_date(entry.get("line", "")))
    if dt:
        age_days = max((now - dt).total_seconds() / 86400.0, 0.0)
    if ttl and age_days is not None and age_days > ttl:
        score += min(60.0, 20.0 + (age_days - ttl) / max(ttl, 1) * 40.0)

    # ② 长命格：没日期就没法判"旧" —— 不给分（宁可漏，不可误伤）
    if pol["kind"] == "long" and age_days is None:
        return 0.0

    # ③ 体量：超长条目往往是"流水糊进来"，压秤（≥600 字 +20）
    if len(entry.get("body", "")) >= 600:
        score += 20.0

    # ④ 重要度反向加权（stories 表格自带这一列）—— critical 永不建议退役
    m = _IMPORTANCE_RE.search(entry.get("body", "") or "")
    if m:
        score *= _IMPORTANCE_KEEP.get(m.group(1).lower(), 1.0)

    return round(score, 1)


def scan(notebook_text: str, *, now: datetime | None = None) -> dict:
    """扫一遍画像 · 返回 {section: [{title, score, reason}...]}（只读，不写盘）。"""
    from workers.notebook_tiers import SECTIONS

    # 按 `^## ` 切段（与 notebook_tiers._iter_sections 同口径）
    chunks = re.split(r"\n(?=## )", notebook_text or "")
    found: dict[str, list[dict]] = {}
    for chunk in chunks:
        head = chunk.strip().split("\n")[0].lstrip("# ").strip()
        if not head:
            continue
        key = None
        for k, meta in SECTIONS.items():
            if any(a in head for a in meta.anchor):
                key = k
                break
        if key is None:
            continue
        items = []
        for e in parse_entries(chunk):
            s = retire_score(e, key, now=now)
            if s > 0:
                items.append({"title": e["title"], "score": s, "line": e["line"][:120]})
        if items:
            found.setdefault(key, []).extend(items)

    for k in found:
        found[k].sort(key=lambda x: -x["score"])
    return found


def render_suggestions(result: dict) -> str:
    """把 scan() 的结果渲成给人看的一页（markdown）。"""
    if not result:
        return "（没有建议退役的条目 —— 各格都还新鲜）"
    lines = ["# 退役建议 · 只给建议，不自动删", ""]
    for k, items in result.items():
        pol = SECTION_POLICY.get(k, {})
        ttl = pol.get("ttl_days")
        head = f"## {k}" + (f"（短命格 · TTL {ttl} 天）" if ttl else "（长命格 · 满了才提示）")
        lines.append(head)
        for it in items:
            lines.append(f"- [{it['score']}] {it['title']}")
            lines.append(f"    {it['line']}")
        lines.append("")
    lines.append("> 处置方式：合并重复 / 改道归档层 / 真删（走 update_owner_note / 界面删除）。")
    return "\n".join(lines)


# ── 已知缺口（不是 TODO，是"要不要补"要人拍的事） ────────────────────────
# 召回信号：`workers/memory_index.py` 的 memory_chunks 表没有 hit_count / last_hit 两列，
# 所以现在判断不了「这条半年没被召回过了」。装上它需要给召回路径加一次写 —— 代价是
# 每次召回多一次 DB 写。当前用「日期 + 格子类型」顶上，够用就不加。


# ── 下沉（demote）· 格子满了时「先腾地方再写」 (2026-09-29 wish-65ea4984 step9) ──
# 与 retire_score 的分工：
#   retire_score 判「这条过期了吗」—— 绝对的（TTL / 体量 / 重要度）。
#   demote_pick  判「这格满了，先挪哪条最不亏」—— 格内相对的（年龄排序）。
#
# 为什么不能拿 retire_score 挑下沉对象：长命格（about-user / how-we-work /
#   understanding）**没有 TTL**，除「≥600 字的超长条目」外一律 0 分 —— 实测用它
#   一条都挑不出来，闸就还是「满了照样拒写」，等于没做。所以两份判据分开，
#   但都只写在 memory_reaper 这一处。
#
# 判据（从该沉 → 不该沉）：
#   ① 带日期的：越老越先沉   ← 主信号（存在最久，作用已经发挥过了）
#   ② 无日期的：不动（写成了「常驻原则」的形状，本来就该长期在场）
#   ③ critical：永不参与（与 retire_score 同一张 _IMPORTANCE_KEEP 表）
#   ④ 同年龄：长的先沉（流水糊进来的压秤）
#
# 下沉 ≠ 删除：落到「已下沉」段，**全文一字不改**，不进每轮前缀但照常被 FTS5
#   索引 —— 所以判错的代价是「不在前缀了」，不是「丢了」。这就是敢自动的底气。
DEMOTE_SECTION_HEAD = "## 已下沉（自动 · 不注入 · 可召回）"
DEMOTE_MAX_N = 3          # 一次最多沉几条 · 限速：宁可分几次沉，不要一口气清空格子


def demote_pick(section_text: str, section_key: str, *,
                need_tok: int = 0, now: datetime | None = None,
                max_n: int = DEMOTE_MAX_N,
                protect_lines: "set[str] | None" = None) -> list[dict]:
    """格子满了 → 挑该沉下去的条目（**只挑不删**）。返回 [{title, line, chars, age_days}]。"""
    if SECTION_POLICY.get(section_key, {}).get("kind") == "skip":
        return []
    now = now or datetime.now(timezone.utc)
    # 状态卡骨架 8 格永不参与下沉（2026-09-30 wish-6e6e561b）——
    #   它们是「当下状态」的骨架：as_of 旧 = 「该更新了」，不是「该走了」。
    #   不排除的话：parse_entries 现在能认出第三列日期了 → 骨架格会跟涌现行一起进候选，
    #   而「健康基线」这种 as_of 停在 08-27 的会排最老 → 反被最先沉掉（写的时候实测踩到）。
    _protect: set[str] = set()
    if section_key == "state":
        try:
            from workers.cognition_loader import STATE_CARD_FIELDS
            _protect = set(STATE_CARD_FIELDS)
        except Exception:
            _protect = set()
    cands: list[dict] = []
    for e in parse_entries(section_text):
        line = (e.get("line") or "").strip()
        if not line:
            continue
        if _protect and (e.get("title") or "").strip() in _protect:
            continue                                  # 骨架格 · 永不沉
        if protect_lines and line in protect_lines:
            # 刚写进来的那条（2026-09-30 wish-66c1eac5）：
            #   写 = 「这条现在就要在场」。它若当场被自己触发的下沉挑走，
            #   等于写了白写，而回执还说「已更新」—— 实测撞到两次
            #   （核心层只剩几十 tok 时，候选里带日期的旧条目往往一条都没有，
            #   唯一候选就是刚写的这条）。
            continue
        m = _IMPORTANCE_RE.search(line)
        if m and _IMPORTANCE_KEEP.get(m.group(1).lower(), 1.0) <= 0.0:
            continue                                  # critical · 永不参与
        # 2026-09-30 wish-a266df37：**不再从 body / 整行兜底搜日期**。
        #   那条兜底把「（依据：8/23 深夜闲聊）」当成了条目日期 —— 一段常驻原则因此变成
        #   「过期流水」被自动沉走了。本函数上面那句「无日期 = 常驻原则 · 不动」才是对的。
        dt = e.get("date")
        if dt is None:
            continue                                  # 无日期 = 常驻原则 · 不动
        cands.append({"title": e["title"], "line": line, "chars": len(line),
                      "age_days": round(max((now - dt).total_seconds() / 86400.0, 0.0), 1)})
    cands.sort(key=lambda c: (-c["age_days"], -c["chars"]))
    picked: list[dict] = []
    got = 0
    for c in cands:
        if len(picked) >= max_n:
            break
        picked.append(c)
        got += c["chars"]
        if need_tok and got / 1.2 >= need_tok:
            break                                     # 至少沉 1 条；够了就停
    return picked


def demote_strip(section_text: str, picked: list[dict]) -> tuple[str, list[dict]]:
    """把 picked 的行从段正文里摘掉（整行精确匹配 · 一行只摘一次）。

    返回 (剩余段文本, **真摘掉的**行) —— 匹配不上的不算。不能让调用方以为沉了，
    其实原文一动没动（那样回执就是在说谎）。
    """
    want = list(picked or [])
    kept: list[str] = []
    removed: list[dict] = []
    for raw in (section_text or "").splitlines(keepends=True):
        s = raw.strip()
        hit = next((p for p in want if p["line"] == s), None)
        if hit is not None:
            want.remove(hit)
            removed.append(hit)
            continue
        kept.append(raw)
    return re.sub(r"\n{3,}", "\n\n", "".join(kept)), removed


def append_demoted(notebook_text: str, removed: list[dict]) -> str:
    """把沉下去的条目落到「已下沉」段（没有就在文件末尾建）。

    这一段**不在 CORE_SECTION_KEYS 里** —— 于是 render_tiered 自动把它折叠成归档
    指引（不进每轮前缀），而 incremental_update 照常索引它（可召回）。
    「下沉」的全部落地方式就是这一句话：不新建文件、不新建机制。
    """
    if not removed:
        return notebook_text
    block = "\n".join(r["line"] for r in removed)
    if DEMOTE_SECTION_HEAD in notebook_text:
        idx = notebook_text.index(DEMOTE_SECTION_HEAD) + len(DEMOTE_SECTION_HEAD)
        return notebook_text[:idx] + "\n\n" + block + notebook_text[idx:]
    return notebook_text.rstrip() + f"\n\n---\n\n{DEMOTE_SECTION_HEAD}\n\n{block}\n"


def demote_to_fit(notebook_text: str, focus_key: str | None = None, *,
                  need_tok: int = 0, max_n: int = DEMOTE_MAX_N,
                  now: datetime | None = None,
                  protect_lines: "set[str] | None" = None) -> tuple[str, list[dict]]:
    """格子/整锅满了 → 从 focus_key 起（其次从最肥的核心格）沉最该沉的条目。

    只动**核心层**的段（`is_core_section`）—— 不进前缀的段本来就不占配额。
    返回 (新全文, 被沉的条目)。沉不动 → 原样返回 + 空列表（调用方据此决定拒写）。
    """
    from workers.notebook_tiers import SECTIONS, is_core_section, section_budget_estimate

    if need_tok <= 0:
        return notebook_text, []          # 不需要腾空间 → 不动（调用方只在真超了时才调）

    chunks = re.split(r"\n(?=## )", notebook_text or "")
    jobs: list[tuple[int, float, int, str]] = []      # (优先级, -used, 段下标, key)
    for i, ch in enumerate(chunks):
        head = ch.strip().split("\n")[0].lstrip("# ").strip()
        if not head or not is_core_section(head):
            continue
        key = next((k for k, m in SECTIONS.items() if any(a in head for a in m.anchor)), None)
        if key is None:
            continue
        used, _cap = section_budget_estimate(notebook_text, key)
        jobs.append((0 if key == focus_key else 1, -used, i, key))
    jobs.sort()

    removed_all: list[dict] = []
    got = 0
    for _pri, _negu, i, key in jobs:
        if len(removed_all) >= max_n:
            break
        picked = demote_pick(chunks[i], key, need_tok=max(int(need_tok - got / 1.2), 0),
                             now=now, max_n=max_n - len(removed_all),
                             protect_lines=protect_lines)
        if not picked:
            continue
        chunks[i], removed = demote_strip(chunks[i], picked)
        if not removed:
            continue
        removed_all.extend(removed)
        got += sum(r["chars"] for r in removed)
        if need_tok and got / 1.2 >= need_tok:
            break
    if not removed_all:
        return notebook_text, []
    return append_demoted("".join(chunks), removed_all), removed_all


# ═══════════════════════════════════════════════════════════════════════
# 升格 · 沉下去的里「真被用到过」的 → 捞回了解层
# ═══════════════════════════════════════════════════════════════════════
#
# demote 和 promote 是一对 · 判据互补、互不重叠:
#   · demote_to_fit   「格子满了」 → 沉最老/最长的   (不看频率 · 满了就得腾)
#   · promote_by_hits 「被用到了」 → 捞回来         (只看频率 · 用得多说明是活知识)
#
# 只沉不捞 = 单向下沉 = 慢性失忆: 好东西会因为「不够新」被永久压着。
# 判据只有一条 —— memory_index.hit_count (search 真返回过的次数)。
# 不问「这条值不值得留」(没人答得了) · 只看「这条有没有被用到」(机器自己数)。

PROMOTE_SECTION_HEAD = DEMOTE_SECTION_HEAD   # 升格读的就是下沉写的那个段 · 同一处两个方向
PROMOTE_MIN_HITS = 3        # 召回满几次算「真被用到」
PROMOTE_MAX_N = 2           # 一次最多捞几条 (限速 · 别一锅端回前缀)


def _match_key(line: str, n: int = 36) -> str:
    """从条目行里取一段用于 LIKE 匹配的核心串。"""
    s = re.sub(r"^\s*[-*]\s+", "", (line or "").strip())
    return s[:n]


def _chunk_hits(lines: list[str], source: str | None = None) -> dict[str, int]:
    """查这些条目行在 memory_index 里各自的 hit_count (查不到 = 0)。

    2026-09-30 wish-27273a5b · 拆格后画像索引的 source 统一叫 OWNER-NOTEBOOK，
    但这里原写死 source="BRO-NOTEBOOK" → 下沉条目的命中数**永远读到 0**（上浮断链）。
    改成不传 source 时两个都查（旧索引残留 + 新身都认）。
    """
    import sqlite3
    from workers.memory_index import DB_PATH

    out: dict[str, int] = {}
    if not lines or not DB_PATH.exists():
        return out
    srcs = (source,) if source else ("OWNER-NOTEBOOK", "BRO-NOTEBOOK")
    ph = ",".join("?" * len(srcs))
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("PRAGMA busy_timeout=30000")
        for ln in lines:
            key = _match_key(ln)
            if not key:
                continue
            esc = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            row = conn.execute(
                f"SELECT MAX(COALESCE(hit_count, 0)) FROM memory_chunks "
                f"WHERE source IN ({ph}) AND content LIKE ? ESCAPE '\\'",
                (*srcs, f"%{esc}%"),
            ).fetchone()
            out[ln] = int((row[0] if row else 0) or 0)
        conn.close()
    except Exception:
        return out
    return out


def _append_to_section(text: str, heading_key: str, block: str) -> str:
    """把 block 追加到 heading_key 那个 ## 段的末尾 (段 = 到下一个 ## 之前)。"""
    m = re.search(rf"^#+\s*{re.escape(heading_key)}.*$", text or "", re.MULTILINE)
    if not m:
        return text
    start = m.end()
    nxt = re.search(r"\n(?=## )", text[start:])
    end = start + nxt.start() if nxt else len(text)
    return text[:start] + text[start:end].rstrip() + "\n" + block + "\n" + text[end:]


def promote_by_hits(notebook_text: str, *, min_hits: int = PROMOTE_MIN_HITS,
                    max_n: int = PROMOTE_MAX_N) -> tuple[str, list[dict]]:
    """「已下沉」段里被召回够多次的条目 → 升格进「了解层」(回到每轮前缀)。

    返回 (新全文, 被升格的条目)。没得升 → 原样返回 + 空列表。
    """
    if PROMOTE_SECTION_HEAD not in (notebook_text or ""):
        return notebook_text, []

    idx = notebook_text.index(PROMOTE_SECTION_HEAD)
    rest = notebook_text[idx + len(PROMOTE_SECTION_HEAD):]
    m = re.search(r"\n(?=## )", rest)
    seg = rest[:m.start()] if m else rest
    tail = rest[m.start():] if m else ""

    entries = parse_entries(seg)
    if not entries:
        return notebook_text, []

    hits = _chunk_hits([e["line"] for e in entries])
    picked = [e for e in entries if hits.get(e["line"], 0) >= min_hits]
    if not picked:
        return notebook_text, []
    picked.sort(key=lambda e: -hits.get(e["line"], 0))
    picked = picked[:max_n]

    # chars 必须带上 —— 下面算「腾多少空间」要用它。
    # 2026-09-30 · 原来只传 line，于是 r["chars"] 抛 KeyError 被 except 吞掉
    # = 静默不捞（老 bug，从没被触发过因为从没真满过）。
    seg_left, removed = demote_strip(
        seg, [{"line": p["line"], "chars": len(p["line"])} for p in picked])
    if not removed:
        return notebook_text, []

    new_text = notebook_text[:idx + len(PROMOTE_SECTION_HEAD)] + seg_left + tail

    # 了解层自己也满了 → **自己腾空间**再捞（2026-09-30 修死锁）
    #
    # 原写法是「满了就这轮先不捞，让它的下沉先跑」—— 但下沉只由**写入**触发
    # （update_bro_note 里那条），而 understanding 是「只有凝练或他明说才写」的格，
    # 一年也写不了几次。于是：格满 → 没人写 → 下沉不跑 → 上浮永远失败 → **死锁**。
    # BRO 原话：「那他还怎么上浮？？？这不就闹着玩了吗」
    #
    # 现在改成按需腾：上浮需要多少空间就沉多少（沉最老/最长的，**保护刚捞的**）。
    # 用「召回频次」换「年龄」—— 被用到的留下，没人碰的让位。
    # 用**引擎同一把尺**（_estimate_tok = tiktoken 真算），不要自己 /1.2 估算 ——
    # 两把尺不一致时预算判断永远偏乐观（实测：98 字符真算 121 tok，/1.2 只算 82）。
    from workers.notebook_tiers import _estimate_tok
    need_tok = _estimate_tok("\n".join(r["line"] for r in removed))
    try:
        from workers.notebook_tiers import section_budget_estimate
        used, cap = section_budget_estimate(new_text, "understanding")
        if cap and used + need_tok > cap:
            new_text, _dem = demote_to_fit(
                new_text, focus_key="understanding", need_tok=need_tok,
                protect_lines={p["line"] for p in picked})
            if not _dem:
                logger.info("升格: 了解层满了且一条都沉不动（条目全无日期？）· 本轮不捞")
                return notebook_text, []
            # 去掉了就捞 —— **不要求腾得严丝合缝**。
            # BRO 2026-09-30：「1799/1800 都可以写入，写入后超过了 1800 那也是不能写的…
            #   写入之后超过 1800 也可以，你懂我意思吗？谁都不会差那几百 TOKEN，
            #   但是怕的是写入没有标准，比如写了个 5000 TOKEN 的东西。」
            # 即：限额是**触发清理的阈值**，不是硬顶。去掉一条即可腾出量级空间，
            # 略超一点无所谓；真正要防的是「一条就把配额吃光」那种无标准写入。
    except Exception as _e_bud:
        logger.warning("升格腾空间失败·本输不捞(保守向): %s", _e_bud)
        return notebook_text, []

    block = "\n".join(r["line"] for r in removed)
    new_text = _append_to_section(new_text, "了解层", block)
    return new_text, removed
