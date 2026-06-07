# -*- coding: utf-8 -*-
"""workers/schema_guard.py · 关键 JSON 写盘前结构闸 (卷五十四 · B3)

只拦【结构性破损】—— 那种会让 daemon 起不来 / wish 列表 UI 崩 / 状态机错乱的坏结构。
不碰内容 / 取值美学 (那不是闸该管的·也不限制 OPUS 想写什么)。 校验不过 → raise · 拒绝写盘。

为什么需要:
  OPUS 用 add_wish/update_wish 或 LLM hallucinate 可能写出 "wishes 不是 list / wish 缺 id /
  status 非法值" → 落盘后下次 load 崩或 UI 错乱。 写前挡一道·把坏结构摁在门外·不让坏的落地。

设计纪律 (硬闸契约):
  - 只校验"会让东西崩"的结构性必需项 · 老值/历史数据一律放行 (绝不误伤正常保存)
  - 覆盖面: 守的是【程序 API 写盘路径】(save_wishlist/save_configs)。 OPUS 用
    write_file/python_exec 直接裸写 JSON 会绕过它 —— 那条旁路归 B4 收口。
"""
from __future__ import annotations


class SchemaError(ValueError):
    """结构闸不过 · 拒绝写盘。"""


# wish 合法 status: 新四态+rejected · 外加老值 (load 时会 normalize · 放行免得误伤历史数据)
_VALID_WISH_STATUS = {
    "pending", "active", "review", "live", "rejected",
    "drafted", "approved", "in_progress", "done", "ready_for_merge",
}
_VALID_PROVIDER_KIND = {"openai", "anthropic"}


def validate_wishlist(data) -> None:
    if not isinstance(data, dict):
        raise SchemaError("wishlist 顶层必须是 dict")
    wishes = data.get("wishes")
    if not isinstance(wishes, list):
        raise SchemaError("wishlist.wishes 必须是 list")
    seen = set()
    for i, w in enumerate(wishes):
        if not isinstance(w, dict):
            raise SchemaError(f"wishes[{i}] 不是 dict")
        wid = w.get("id")
        if not isinstance(wid, str) or not wid.strip():
            raise SchemaError(f"wishes[{i}] 缺合法 id (空或非字符串)")
        if wid in seen:
            raise SchemaError(f"wish id 重复: {wid}")
        seen.add(wid)
        st = w.get("status")
        if st is not None and st not in _VALID_WISH_STATUS:
            raise SchemaError(f"wish {wid} status 非法: {st!r}")


def validate_provider_configs(data) -> None:
    if not isinstance(data, dict):
        raise SchemaError("provider_configs 顶层必须是 dict")
    cfgs = data.get("configs")
    if not isinstance(cfgs, list):
        raise SchemaError("provider_configs.configs 必须是 list")
    for i, c in enumerate(cfgs):
        if not isinstance(c, dict):
            raise SchemaError(f"configs[{i}] 不是 dict")
        cid = c.get("id")
        if not isinstance(cid, str) or not cid.strip():
            raise SchemaError(f"configs[{i}] 缺合法 id")
        kind = c.get("provider_kind")
        if kind not in _VALID_PROVIDER_KIND:
            raise SchemaError(f"config {cid} provider_kind 非法: {kind!r} (只支持 {_VALID_PROVIDER_KIND})")
