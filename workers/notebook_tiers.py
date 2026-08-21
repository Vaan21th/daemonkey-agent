"""workers/notebook_tiers.py
========================
画像分层 (2026-08-20 · 0.9.6 知识体系三件套之一)。

why: 画像涨到 57.8K 字符后全量注入 = 每轮白烧 2-3 万 token, 占 128K 窗口约四成。
实测画像 66% 体量是历史流水 (事件流 27.4K + 更新流水 11.1K) —— 它们的价值是可追溯,
不是每轮在场。 画像全文已在 memory_chunks(source=BRO-NOTEBOOK) 有索引, 历史层折叠后
recall_memory / read_file 都能取回, 可追溯性不丢。

切分方向的安全选择: 核心层走白名单 (已知当下维度), 未命中的一律进历史层 ——
未来画像新增维度默认不推高每轮注入体量 (体量安全), 要进核心层必须在此显式登记。
"""

from __future__ import annotations

import re

CORE_SECTION_KEYS = (
    "当下画像",
    "人生规则",
    "对话图鉴",
    "压缩段",
    "风险与弱点",
    "给下一根毛",
)

_SECTION_RE = re.compile(r"(?m)^(?=## )")


def split_tiers(text: str) -> tuple[str, list[tuple[str, int]]]:
    """把画像按二级标题切成 (核心层文本, [(历史层标题, 字符数)])。

    无 `## ` 维度标题的画像 (新装实例/极简画像) 整体视为核心层, 原样返回。
    """
    if not text or not text.strip():
        return text or "", []
    parts = _SECTION_RE.split(text)
    head, sections = parts[0], parts[1:]
    if not sections:
        return text, []
    core, archived = [], []
    for seg in sections:
        title = seg.split("\n", 1)[0].lstrip("# ").strip()
        if any(k in title for k in CORE_SECTION_KEYS):
            core.append(seg)
        else:
            archived.append((title, len(seg)))
    return head + "".join(core), archived


def render_tiered(text: str) -> str:
    """分层渲染: 核心层原文 + 历史层折叠成归档指引 (全文一字未删, 取回方式写清)。

    归档指引只列标题不带字符数 —— 历史层每天追加事件流, 字符数每轮变,
    挂在指引里会冲掉 system 前缀缓存 (0.8x 缓存前缀稳定化: 字节不变才命中)。
    """
    core, archived = split_tiers(text)
    if not archived:
        return text
    lines = "\n".join(f"  - 「{t}」" for t, _n in archived)
    return (
        core.rstrip()
        + "\n\n---\n\n## 已归档的历史层（每轮不注入 · 按需取回）\n\n"
        + "以下维度是历史流水，已从每轮注入折叠，**全文一字未删**：\n"
        + lines
        + "\n\n取回方式：`recall_memory`（画像全文在记忆索引 source=BRO-NOTEBOOK）"
        "或 `read_file` 画像文件对应维度段。\n"
    )
