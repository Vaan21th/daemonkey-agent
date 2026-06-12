"""agent_tools/manage_app_asset.py
==================================

沉淀闭环 v2 · 刀① · LLM 读写 app 资产登记表 · 2026-06-10

什么是 app 资产:
    用户的个性化沉淀 · 例: TTS app 的声音克隆 voice_id (active+versions) ·
    内容制作 app 的 IP 形象图路径 / 画面风格参考 / 文本风格参考 ·
    写代码 app 的代码规范。
    跟 secret 的区别: secret 是凭证(敏感·LLM 只见 placeholder) · asset 是业务资产(LLM 可直接读写)。

为什么必须用它 (而不是记在对话里):
    2026-06-09 事故 · 用户打磨三版声音克隆 · "选定第三版"只活在对话上下文 ·
    换个对话 AI 拿废版配音。资产登记表在工程层 · 任何新对话都先读它 · 永不蒸发。
"""

from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    action = args.get("action") or "?"
    aid = args.get("app_id") or "?"
    name = args.get("name") or ""
    return f"资产登记 · {action} · {aid}" + (f" · {name}" if name else "")


def _run(args: dict) -> ToolResult:
    from workers import workshop_registry as reg

    action = (args.get("action") or "").strip().lower()
    aid = (args.get("app_id") or "").strip()
    name = (args.get("name") or "").strip()

    try:
        if action == "set":
            if "value" not in args:
                return ToolResult(ok=False, output="", error="set 需要 value 字段")
            note = (args.get("note") or "").strip()
            if not note:
                return ToolResult(
                    ok=False, output="",
                    error=(
                        "set 必须带 note (一句话说明这次写入·例 '第三版克隆·用户试听满意')。"
                        "没有 note 的资产以后没人知道哪版能用——这正是要根治的痛。"
                    ),
                )
            r = reg.set_asset(
                aid, name, args["value"],
                asset_type=args.get("type") or "text",
                label=args.get("label") or "",
                note=note,
            )
            return ToolResult(ok=True, output=(
                f"# ✓ 资产已登记 · {aid} / {name}\n"
                f"  - 时间: {r['updated_at']} · 说明: {note}\n"
                f"  - 历史版本: {r['history_count']} 条 (旧值已自动留痕·不会丢)\n"
                f"  - 读取方式: manage_app_asset(action='get', app_id='{aid}', name='{name}') "
                f"或 read_file data/workshop/assets/{aid}.json"
            ))

        if action == "get":
            entry = reg.get_asset(aid, name)
            if entry is None:
                return ToolResult(ok=False, output="", error=f"资产不存在: {aid} / {name}")
            import json as _json
            hist = entry.pop("history", [])
            lines = [
                f"# 资产 · {aid} / {name}",
                _json.dumps(entry, ensure_ascii=False, indent=2),
            ]
            if hist:
                lines.append(f"\n(另有 {len(hist)} 条历史版本 · action='history' 可看)")
            return ToolResult(ok=True, output="\n".join(lines))

        if action == "list":
            items = reg.list_assets(aid)
            if not items:
                return ToolResult(ok=True, output=f"# {aid} 还没有登记任何资产")
            lines = [f"# {aid} 的资产登记表 ({len(items)} 项)"]
            for it in items:
                lines.append(
                    f"  - **{it['name']}** ({it['type']}) · {it['label']} · "
                    f"更新 {it['updated_at']} · {it['note'] or '(无说明)'}\n"
                    f"    值: {it['value_preview']}"
                )
            return ToolResult(ok=True, output="\n".join(lines))

        if action == "history":
            entry = reg.get_asset(aid, name)
            if entry is None:
                return ToolResult(ok=False, output="", error=f"资产不存在: {aid} / {name}")
            import json as _json
            hist = entry.get("history") or []
            lines = [
                f"# 资产历史 · {aid} / {name}",
                f"当前值 (updated {entry.get('updated_at')}): "
                f"{_json.dumps(entry.get('value'), ensure_ascii=False)[:300]}",
            ]
            if not hist:
                lines.append("(没有历史版本)")
            for i, h in enumerate(reversed(hist), 1):
                lines.append(
                    f"  ~{i}. 被替换于 {h.get('replaced_at')} · 原写于 {h.get('was_set_at')} · "
                    f"{h.get('note') or '(无说明)'}\n"
                    f"     值: {_json.dumps(h.get('value'), ensure_ascii=False)[:200]}"
                )
            return ToolResult(ok=True, output="\n".join(lines))

        if action == "delete":
            ok = reg.delete_asset(aid, name)
            if not ok:
                return ToolResult(ok=False, output="", error=f"资产不存在: {aid} / {name}")
            return ToolResult(ok=True, output=f"# ✓ 已删除资产 {aid} / {name} (含历史·不可恢复)")

        return ToolResult(
            ok=False, output="",
            error=f"action 必须是 set/get/list/history/delete · 收到: {action!r}",
        )
    except ValueError as e:
        return ToolResult(ok=False, output="", error=str(e))
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"registry 操作失败: {e}")


SPEC = ToolSpec(
    name="manage_app_asset",
    description=(
        "读写 app 资产登记表 · 用户个性化沉淀的单一事实源 (data/workshop/assets/<app_id>.json)\n\n"
        "**什么是资产**: voice 克隆(active voice_id+历史版本) / IP 形象图路径 / 画面风格参考 /\n"
        "文本风格参考 / 代码规范——『用户打磨出来的、跨对话必须记住的东西』。\n"
        "跟 app_set_secret 的区别: secret=凭证(敏感) · asset=业务资产(可读可引用)。\n\n"
        "**🔴 铁律 (2026-06-09 三版声音克隆只剩废版的教训)**:\n"
        "  1. app 运行要用到个性资产时 · **先 get/list 读登记表** · 严禁凭记忆/上下文硬编码\n"
        "  2. 用户打磨出新版本 (新 voice_id / 新风格参考) · **当场 set 登记** · 不等用户提醒\n"
        "  3. set 必须带 note 说明这版是什么·能不能用 · 旧值自动压历史·永不丢\n"
        "  4. 大文件 (图/音频) 不存值 · 存其在 outputs/ 或磁盘的路径\n\n"
        "**app_id 用 '_shared'** = 跨 app 共享资产 (IP 形象/品牌色这种不属于单一 app 的)。\n"
        "**典型用法**:\n"
        "  - 配音前: get(app_id='app-6f439831', name='voice') → 用 value.active 的 voice_id\n"
        "  - 克隆出新版: set(..., name='voice', value={active: 'voice-v2', ...}, note='第二版·试听满意')\n"
        "  - 看打磨史: history(...) → 每版何时被替换·当时的说明"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["set", "get", "list", "history", "delete"],
                "description": "set=写(覆盖留痕) get=读单个 list=列全部 history=看版本史 delete=删",
            },
            "app_id": {
                "type": "string",
                "description": "app-xxxxxxxx · 或 '_shared' (跨 app 共享资产)",
            },
            "name": {
                "type": "string",
                "description": "资产名 · [a-zA-Z_][a-zA-Z0-9_]* · 例 'voice' / 'ip_images' / 'style_ref'",
            },
            "value": {
                "description": "set 用 · str 或 dict/list (≤64KB · 大文件存路径)",
            },
            "type": {
                "type": "string",
                "enum": ["text", "json", "images", "file"],
                "description": "set 用 · 资产类型 · 默认 text",
            },
            "label": {
                "type": "string",
                "description": "set 用 · 给用户看的中文标签 · 配置页显示用",
            },
            "note": {
                "type": "string",
                "description": "set 必填 · 一句话说明这版是什么/能不能用 · 例 '第三版克隆·用户试听满意'",
            },
        },
        "required": ["action", "app_id"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
