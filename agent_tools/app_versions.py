"""agent_tools/app_versions.py
===============================

沉淀闭环 v2 · 刀④ · app 版本查询 / diff / 回滚预览 (2026-06-10)

为什么有这个
------------
刀①给 save_app 加了 version + changelog (元数据)·刀④给 update 加了内容快照 ·
但光有快照用户没法用——这个工具让 AI 在对话里说"上次那版怎么写的"时·能 list /
读 / diff / 回滚出来给用户看。

action:
    list     · 列某 app 的历史版本 (摘要)
    show     · 读某历史版本完整内容 (system_prompt 全文 etc.)
    diff     · 两版关键字段 diff 摘要
    rollback · 回滚到某版 (调 save_app 复写当前 · 自动+1 新 version · 留 change_note)
"""

from __future__ import annotations

from . import TIER_AUTO, TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _classify(args: dict) -> str:
    return TIER_CONFIRM if (args.get("action") or "") == "rollback" else TIER_AUTO


def _summarize(args: dict) -> str:
    a = args.get("action") or "?"
    aid = args.get("app_id") or "?"
    v = args.get("version")
    extra = f" · v{v}" if v else ""
    return f"app 版本 {a} · {aid}{extra}"


def _run(args: dict) -> ToolResult:
    from workers.workshop_app_versions import diff_summary, list_versions, load_version
    from workers.workshop_assets import load_app, save_app

    action = (args.get("action") or "").strip()
    aid = (args.get("app_id") or "").strip()
    if not aid.startswith("app-"):
        return ToolResult(ok=False, output="", error="app_id 必须是 app-xxxxxxxx 格式")

    if action == "list":
        versions = list_versions(aid)
        if not versions:
            cur = load_app(aid)
            cur_v = (cur or {}).get("version") or "?"
            return ToolResult(ok=True, output=(
                f"app `{aid}` 没有历史版本快照 (当前 v{cur_v} · 它是初版或还没被 update 过)。"
            ))
        lines = [f"# app `{aid}` 历史版本 · 共 {len(versions)} 版"]
        for v in versions:
            lines.append(
                f"- v{v['version']} · {v['updated_at']} · spec_v{v['spec_version']} · "
                f"prompt {v['prompt_len']} 字 · tools {v['tools_count']}"
            )
        lines.append("")
        lines.append("→ 看某版完整内容 `app_versions(action=show, app_id=..., version=N)`")
        lines.append("→ 比对两版 `app_versions(action=diff, app_id=..., version=N, version_b=M)`")
        return ToolResult(ok=True, output="\n".join(lines))

    if action == "show":
        version = args.get("version")
        if version is None:
            return ToolResult(ok=False, output="", error="show 需要 version 参数")
        data = load_version(aid, int(version))
        if not data:
            return ToolResult(ok=False, output="", error=f"v{version} 不存在")
        lines = [
            f"# app `{aid}` · v{data.get('version')}",
            f"  - name: {data.get('name')}",
            f"  - updated_at: {data.get('updated_at')}",
            f"  - spec_version: {data.get('spec_version')}",
            f"  - tools: {data.get('tools')}",
            f"  - asset_slots: {data.get('asset_slots')}",
            "",
            "## system_prompt",
            data.get("system_prompt") or "(空)",
        ]
        return ToolResult(ok=True, output="\n".join(lines))

    if action == "diff":
        va = args.get("version")
        vb = args.get("version_b")
        if va is None or vb is None:
            return ToolResult(ok=False, output="", error="diff 需要 version + version_b")
        d = diff_summary(aid, int(va), int(vb))
        lines = [f"# diff v{d['a']} → v{d['b']} · 变更 {len(d['changes'])} 处"]
        for ch in d["changes"]:
            field = ch["field"]
            if "preview_a" in ch:
                lines.append(f"\n## {field} (v{d['a']} {ch['a_len']} 字 → v{d['b']} {ch['b_len']} 字)")
                lines.append(f"  - v{d['a']}: {ch['preview_a']}")
                lines.append(f"  - v{d['b']}: {ch['preview_b']}")
            else:
                lines.append(f"\n## {field}")
                lines.append(f"  - v{d['a']}: {ch.get('a')}")
                lines.append(f"  - v{d['b']}: {ch.get('b')}")
        return ToolResult(ok=True, output="\n".join(lines))

    if action == "rollback":
        version = args.get("version")
        if version is None:
            return ToolResult(ok=False, output="", error="rollback 需要 version 参数 (回滚到第几版)")
        data = load_version(aid, int(version))
        if not data:
            return ToolResult(ok=False, output="", error=f"v{version} 不存在")
        cur = load_app(aid)
        cur_v = (cur or {}).get("version") or "?"
        # 走 save_app 路径 · 自动 version+1 · 留 change_note · 当前内容也会被快照
        try:
            payload = dict(data)
            payload["id"] = aid  # 保险 · 不让回滚换 id
            payload["change_note"] = f"rollback from v{cur_v} → v{version}"
            # 移除会让 save_app 重算的字段
            for k in ("version", "updated_at", "spec_version", "changelog", "runs", "created_at"):
                payload.pop(k, None)
            result = save_app(payload)
        except ValueError as e:
            return ToolResult(ok=False, output="", error=f"回滚失败 (校验拒): {e}")
        return ToolResult(
            ok=True,
            output=(
                f"# ✓ app `{aid}` 回滚 v{cur_v} → v{version}\n"
                f"  - 新 version: v{result.get('version')} (rollback 也是一次 update)\n"
                f"  - 旧 v{cur_v} 已自动快照 · 后悔了再 rollback 回去"
            ),
        )

    return ToolResult(ok=False, output="", error=f"未知 action: {action!r} · 可用 list/show/diff/rollback")


SPEC = ToolSpec(
    name="app_versions",
    description=(
        "查工坊 app 的历史版本快照 · 可读 / diff / 回滚 (沉淀闭环 v2 刀④)\n\n"
        "**什么时候用**:\n"
        "  - 用户说『上次那版 prompt 是怎么写的』 → list + show\n"
        "  - 调坏了想知道改了啥 → diff 当前 vs 上一版\n"
        "  - update_app 改坏了要回滚 → rollback (会自动+1 新 version · 不毁现版)\n\n"
        "**机制**:\n"
        "  - save_app 每次 update 时·会把覆盖前的状态快照到 data/workshop/apps/_versions/<aid>/v<N>.json\n"
        "  - 保留最近 30 版 · 创建新 app 不快照 (没东西可快照)\n"
        "  - rollback 走 save_app 路径 · 同样会过结构校验 · 老版本不合规也能拒\n\n"
        "**红线**: 不直接覆盖当前 · 永远走 save_app · 留全程留痕。"
    ),
    tier=TIER_AUTO,
    classify=_classify,
    input_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "show", "diff", "rollback"]},
            "app_id": {"type": "string", "description": "app-xxxxxxxx"},
            "version": {"type": "integer", "description": "show/diff/rollback 用 · 第几版"},
            "version_b": {"type": "integer", "description": "diff 用 · 对比的另一版"},
        },
        "required": ["action", "app_id"],
    },
    run=_run,
    summarize=_summarize,
)
register_tool(SPEC)
