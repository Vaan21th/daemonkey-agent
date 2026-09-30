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

import re
from datetime import datetime, timezone
from pathlib import Path

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
        #   只收「第一列能解出日期」的行，表头/分隔行自然被挡在外。
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            d = _parse_date(cells[0]) if cells else None
            if d and len(cells) >= 2:
                out.append({"title": (cells[1] or cells[0])[:60],
                            "body": " ".join(cells), "line": s, "date": d})
            continue
        m = _BULLET_RE.match(raw)
        if not m:
            continue
        title = (m.group("title") or m.group("title2") or "").strip()
        if not title or title.startswith("**"):     # 排除「**日期**」这种纯标题行
            continue
        body = (m.group("body") or "").strip()
        out.append({"title": title, "body": body, "line": s,
                    "date": _parse_date(body) or cur})
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
                max_n: int = DEMOTE_MAX_N) -> list[dict]:
    """格子满了 → 挑该沉下去的条目（**只挑不删**）。返回 [{title, line, chars, age_days}]。"""
    if SECTION_POLICY.get(section_key, {}).get("kind") == "skip":
        return []
    now = now or datetime.now(timezone.utc)
    cands: list[dict] = []
    for e in parse_entries(section_text):
        line = (e.get("line") or "").strip()
        if not line:
            continue
        m = _IMPORTANCE_RE.search(line)
        if m and _IMPORTANCE_KEEP.get(m.group(1).lower(), 1.0) <= 0.0:
            continue                                  # critical · 永不参与
        dt = e.get("date") or _parse_date(e.get("body", "")) or _parse_date(line)
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
                  now: datetime | None = None) -> tuple[str, list[dict]]:
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
                             now=now, max_n=max_n - len(removed_all))
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


def _chunk_hits(lines: list[str], source: str = "BRO-NOTEBOOK") -> dict[str, int]:
    """查这些条目行在 memory_index 里各自的 hit_count (查不到 = 0)。"""
    import sqlite3
    from workers.memory_index import DB_PATH

    out: dict[str, int] = {}
    if not lines or not DB_PATH.exists():
        return out
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("PRAGMA busy_timeout=30000")
        for ln in lines:
            key = _match_key(ln)
            if not key:
                continue
            esc = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            row = conn.execute(
                "SELECT MAX(COALESCE(hit_count, 0)) FROM memory_chunks "
                "WHERE source = ? AND content LIKE ? ESCAPE '\\'",
                (source, f"%{esc}%"),
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

    seg_left, removed = demote_strip(seg, [{"line": p["line"]} for p in picked])
    if not removed:
        return notebook_text, []

    new_text = notebook_text[:idx + len(PROMOTE_SECTION_HEAD)] + seg_left + tail

    # 了解层自己也满了 → 这轮先别捞 (让它的下沉先跑 · 免得两个动作打架)
    try:
        from workers.notebook_tiers import section_budget_estimate
        used, cap = section_budget_estimate(new_text, "understanding")
        if cap and used + sum(r["chars"] for r in removed) / 1.2 > cap:
            return notebook_text, []
    except Exception:
        pass

    block = "\n".join(r["line"] for r in removed)
    new_text = _append_to_section(new_text, "了解层", block)
    return new_text, removed
