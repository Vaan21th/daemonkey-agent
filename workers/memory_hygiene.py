"""记忆库卫生闸 —— 拦掉不该进召回索引的东西 + 清掉历史上已经进去的。

2026-08-19 · 起因: 记忆体系体检 (data/learnings/2026-08-19-memory-scale-audit.md)
实测发现 2.5 万条 chunk 里真问题不是"量大"(FTS5 查 0.1ms·再翻 100 倍也不慢)·
而是信噪比 —— 三类垃圾把有用内容挤出了 top-k:

  1. 同一句 system 模板(重启续场)在几十个会话里重复 → 词频拉满 → bm25 排最前
  2. 端到端验证造的假会话(e2e-verify / e2e-audit) 被当真实偏好召回
  3. playbook 按标题分块产生的空壳(整块只有 "## 步骤" 没正文) 稳定占位

为什么规则写得这么保守
-----------------------
这份代码会随 update_core 下发到用户机器·**我们看不见他们的数据**。
所以每条规则都必须"闭着眼也知道是垃圾"·宁可漏删不可误删:
删错一条真实记忆的代价·远大于留着十条垃圾。 因此这里没有任何
模糊判断、没有 LLM 参与、没有"看起来不重要"这种主观规则 —— 全是确定性比对。

为什么不走全量 rebuild
-----------------------
2026-08-12 出过事故: 全量重建 2 万条 + 逐条 embedding → 300s+ 卡死 → 用户强杀
→ DROP 后留空表。 修复后明确规定 rebuild 只在 db 不存在时 fallback·不碰 session。
所以存量清理走**定向 DELETE**(秒级·不重读 jsonl·不调一次 embedding·幂等)。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# 清理规则版本 · 升一位 = 下次启动重跑一遍清理 (见 needs_migration)
# v2 (2026-08-20): 新增 retired_playbook 规则
HYGIENE_VERSION = 2

_ROOT = Path(__file__).resolve().parent.parent

# 搭档自治规则 (0.9.6 · BRO 拍板 "你可以判断你要记哪些东西")。
# 内置规则是母体保底 · 这份是每个搭档自己长出来的本地层 —— OPUS 反刍自己的库
# 发现噪音时经 add_hygiene_rule 写入 · 用户也可手改。 两层并行 · 互不覆盖。
# 判错可恢复 (jsonl 原文永远在 · 全量 rebuild 可重建) · 所以本地层允许比内置层激进。
_CUSTOM_RULES_PATH = _ROOT / "data" / "my_hygiene_rules.json"

# 只有这两种角色是"对话实质" · 跟 index_session_turn 的既定语义对齐。
# rebuild() 那条路历史上不做角色过滤 → system/tool 全进索引 → 这就是垃圾 1 的产地。
_REAL_ROLES = ("user", "assistant")

# 系统注入的固定模板 · 命中即噪音。 兜底用: 万一模板以别的角色进来。
# 只放"整句独一无二、不可能出现在真实对话里"的串。
_NOISE_TEMPLATES = (
    "[SYSTEM · 重启续场",
    "你之前调 request_restart 申请重启 daemon",
)

# 【故意不做"按 session id 前缀删测试会话"】(2026-08-19 · dry_run 拦下的误判)
#
# 体检报告里把 e2e-verify / e2e-audit-c 判成"端到端验证造的假会话·该删"。
# dry_run 一拆才看清: 这三个会话里有 227 条真人发言·内容全是真实需求
# ("你能帮我写一个 daemonkey 的网页吗?"、"我要开始做视频的脚本了...")——
# 只是当年跑测试时借了带 e2e 前缀的 session id·**内容是真的**。
#
# 按前缀删: 收益 6 条 (test-mech 5 + smoke-test-001 1·零真人发言) ·
# 代价 613 条真实对话。 完全不成比例 —— 所以这条规则整个去掉。
# 这也正是"宁可漏删不可误删"的意思: 判不准 session 是真是假·就别按 id 猜。


def _sid_and_role(section: str) -> tuple[str, str]:
    """session 类的 section 格式是 "{session_id}:{role}" · 拆出来。

    session_id 自己带下划线和连字符·但不带冒号·所以按最后一个冒号切。
    """
    s = section or ""
    if ":" not in s:
        return s, ""
    sid, _, role = s.rpartition(":")
    return sid, role


_custom_cache: tuple[float, list[dict]] | None = None


def _load_custom_rules() -> list[dict]:
    """读本地自治规则 · 文件不存在/格式坏都当空 (自治层绝不能让清理崩掉)。

    mtime 缓存: is_noise 每条 chunk 调一次 · 全库扫描 2 万+ 次 · 不能次次读盘。
    """
    global _custom_cache
    try:
        if not _CUSTOM_RULES_PATH.exists():
            return []
        mtime = _CUSTOM_RULES_PATH.stat().st_mtime
        if _custom_cache and _custom_cache[0] == mtime:
            return _custom_cache[1]
        data = json.loads(_CUSTOM_RULES_PATH.read_text(encoding="utf-8"))
        rules = data.get("rules") if isinstance(data, dict) else None
        if not isinstance(rules, list):
            return []
        # 只收有 name + match 的 · match 空串会匹配一切 · 直接拒
        out = [r for r in rules
               if isinstance(r, dict) and r.get("name") and str(r.get("match") or "").strip()]
        _custom_cache = (mtime, out)
        return out
    except Exception as e:
        logger.warning("my_hygiene_rules.json 读取失败 · 当空处理: %s", e)
        return []


def is_noise(source: str, section: str, content: str) -> str:
    """这条 chunk 该不该进索引 · 返回命中的规则名(空字符串 = 干净·该收)。

    返回规则名而不是 bool·是为了让 dry_run 报告能按类分组给人看。
    """
    text = (content or "").strip()
    if not text:
        return "blank"

    for tpl in _NOISE_TEMPLATES:
        if tpl in text:
            return "template"

    # 只对对话原文做角色过滤 · 摘要(role 位是 "summary#N")不参与
    if (source or "") == "session":
        _, role = _sid_and_role(section)
        if role and role not in _REAL_ROLES:
            return "non_dialogue_role"

    # retired playbook 的语义就是"退休了不该再被召回"——但历史上照样进索引
    # (本机实测 1 条 · 还参与向量判重抬高重复簇)。 文件名约定 <title>.retired.md
    # → section 里带 ".retired" · 确定性比对 · 不存在误伤面。
    if (source or "") == "skill" and ".retired" in (section or ""):
        return "retired_playbook"

    # 只有标题没正文的空壳 (markdown 标题分块的产物)。
    # 要求"去掉所有 # 开头的行后什么都不剩"—— 有一个字正文就不算空壳·
    # 所以 "## 结论\n可行" 这种短但有内容的段落不会被误伤。
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines and all(ln.startswith("#") for ln in lines):
        return "empty_section"

    # 搭档自治层 · 内置规则全没命中才走这里。 substring 确定性匹配
    # (不开正则: LLM/用户写错正则的误伤面不可控)。 source 限定可选。
    for r in _load_custom_rules():
        if r.get("source") and r["source"] != (source or ""):
            continue
        if str(r["match"]) in text:
            return f"custom:{r['name']}"

    return ""


def _scan(conn: sqlite3.Connection) -> tuple[dict[str, list[int]], dict[str, list[str]]]:
    """全库过一遍规则 · 返回 (规则名→id 列表, 规则名→样本正文)。"""
    hits: dict[str, list[int]] = {}
    samples: dict[str, list[str]] = {}
    for cid, source, section, content in conn.execute(
        "SELECT id, source, section, content FROM memory_chunks"
    ):
        rule = is_noise(source or "", section or "", content or "")
        if not rule:
            continue
        hits.setdefault(rule, []).append(cid)
        if len(samples.setdefault(rule, [])) < 3:
            one = " ".join((content or "").split())[:110]
            samples[rule].append(f"[{source}] {section} · {one}")
    return hits, samples


def purge_noise(conn: sqlite3.Connection, dry_run: bool = True) -> dict:
    """按 is_noise 规则清掉存量垃圾 · 默认只报不删。

    conn 由调用方给 (复用 memory_index 那边配好 WAL/busy_timeout 的连接)。
    返回 {"total": n, "by_rule": {...}, "samples": {...}, "dry_run": bool}。
    """
    hits, samples = _scan(conn)
    total = sum(len(v) for v in hits.values())
    report = {
        "total": total,
        "by_rule": {k: len(v) for k, v in sorted(hits.items())},
        "samples": samples,
        "dry_run": dry_run,
    }
    # 孤儿: fts 里有 rowid 但 chunks 里没对应行 (本机实测 37 条历史遗留 —— 某次
    # incremental_update 删了 chunks 没删干净 fts)。 search 走 inner join · 孤儿召不出来
    # → 无害 · 但清掉能让两张表严格一致: 以后再对不上就一定是真 bug。
    #
    # 用 SELECT 出 rowid 再按 IN 批量删 · 不写 "DELETE ... WHERE rowid NOT IN (子查询)":
    # memory_fts 是 FTS5 虚拟表 · 只有等值/IN 形式的 rowid 条件是可靠的。
    orphan_ids = [
        r[0] for r in conn.execute(
            "SELECT f.rowid FROM memory_fts f "
            "LEFT JOIN memory_chunks c ON c.id = f.rowid WHERE c.id IS NULL"
        )
    ]
    report["orphans"] = len(orphan_ids)

    if dry_run:
        return report

    # 噪音和孤儿是两件独立的事 —— 早期版本把孤儿清理写在 "没噪音就 return" 之后 ·
    # 结果库已经干净时孤儿永远清不掉 (验证第 5 项抓出来的)。
    ids = [i for v in hits.values() for i in v]
    # standalone fts 不跟着 chunks 走 · 得自己按 rowid 删 (跟 purge_session 同一写法)。
    # 分批: sqlite 变量上限 999 · 2 万条一次塞进去会炸。
    for chunk_ids in (ids, orphan_ids):
        for i in range(0, len(chunk_ids), 500):
            batch = chunk_ids[i:i + 500]
            ph = ",".join("?" * len(batch))
            conn.execute(f"DELETE FROM memory_fts WHERE rowid IN ({ph})", batch)
            conn.execute(f"DELETE FROM memory_chunks WHERE id IN ({ph})", batch)
    if ids or orphan_ids:
        conn.commit()
        logger.info("记忆库清理: 噪音 %d 条 + fts 孤儿 %d 条 %s",
                    total, len(orphan_ids), report["by_rule"])
    return report


# ---------------------------------------------------------------------------
# 版本标记 · 让用户升级完自动受益一次 (不用他懂、不用他动手)
# ---------------------------------------------------------------------------

def _get_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def _set_version(conn: sqlite3.Connection, v: int) -> None:
    # PRAGMA 不接受参数绑定 · v 是本模块常量(int)·不是外部输入
    conn.execute(f"PRAGMA user_version = {int(v)}")
    conn.commit()


def _custom_fingerprint() -> int:
    """自治规则内容指纹 (application_id 是有符号 int32 · 取 md5 前 8 位)。

    为什么单独存: needs_migration 原来只看内置 HYGIENE_VERSION —— 搭档往
    my_hygiene_rules.json 加了规则·内置版本号不动·存量里被新规则命中的
    chunk 就永远没人清 (2026-08-20 BRO 问"残余噪音什么时候自己处理"发现的洞)。
    """
    try:
        if not _CUSTOM_RULES_PATH.exists():
            return 0
        import hashlib
        h = hashlib.md5(_CUSTOM_RULES_PATH.read_bytes()).hexdigest()
        return int(h[:8], 16) & 0x7FFFFFFF
    except Exception:
        return 0


def _get_custom_fp(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("PRAGMA application_id").fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def _set_custom_fp(conn: sqlite3.Connection, v: int) -> None:
    conn.execute(f"PRAGMA application_id = {int(v)}")
    conn.commit()


def needs_migration(conn: sqlite3.Connection) -> bool:
    """这个库还没按当前规则清过吗。

    两个触发源: ① 内置规则版本升了 (user_version < HYGIENE_VERSION)
    ② 自治规则文件内容变了 (application_id ≠ 当前指纹) —— 搭档加了本地
    规则·下次启动自动按新规则重扫存量。
    用 sqlite 自带的 pragma 而不是新建 meta 表 —— 不动 schema。
    """
    if _get_version(conn) < HYGIENE_VERSION:
        return True
    return _get_custom_fp(conn) != _custom_fingerprint()


def migrate(conn: sqlite3.Connection) -> dict:
    """升级后跑一次: 清存量 + 记版本 + 记自治指纹。 已经清过就直接跳过。

    幂等 —— 跑十遍跟跑一遍结果一样。
    """
    if not needs_migration(conn):
        return {"skipped": True, "version": _get_version(conn)}
    report = purge_noise(conn, dry_run=False)
    _set_version(conn, HYGIENE_VERSION)
    _set_custom_fp(conn, _custom_fingerprint())
    report["version"] = HYGIENE_VERSION
    report["skipped"] = False
    return report
