"""
agent_tools/update_core.py
==========================
OPUS 通过对话拉取"内核(L1)升级" · 卷六十四续六 · 2026-06-08

为什么有这个工具 (BRO 2026-06-08 拍板):
  Daemonkey 开源版没法做整包官方更新——每个用户的实例会随对话长出自己的功能(L2)和
  灵魂记忆(L3)。 但写代码安全 / 编辑锁 / git 纪律 / daemon 救命这些【内核基础设施】
  是所有人共享的 · 必须能统一升级。 这个工具让用户的 Daemonkey **只用一句对话**就能
  从中心库 (gitee/github) 把内核升到最新 · 而且【物理上只碰 core_manifest.json 白名单
  里的文件】· 用户自己造的 app / 工作流 / soul 记忆 一个字节都不会被覆盖。

  → "和 AI 的初见不该这么消失" —— 升级只换骨架 · 不动灵魂。

档位:
  list / remotes / check / preview · 只读 · AUTO
  apply · 真覆盖白名单文件 · CONFIRM (BRO/用户确认后才动手 · 覆盖前自动 checkpoint 可回退)

NLP 触发示例:
  - "看看内核有没有更新"           → action=check
  - "内核更新都改了啥 · 给我看 diff" → action=preview
  - "升级内核 / 同步最新内核"        → action=apply
  - "我能从哪几个源拉更新"          → action=remotes
  - "内核清单里都有哪些文件"        → action=list
"""
from __future__ import annotations

from . import TIER_AUTO, TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    action = (args.get("action") or "check").strip()
    remote = (args.get("remote") or "").strip()
    return f"update_core {action}{(' from ' + remote) if remote else ''}".strip()


def _classify(args: dict) -> str:
    return TIER_CONFIRM if (args.get("action") or "check").strip() == "apply" else TIER_AUTO


def _run(args: dict) -> ToolResult:
    from workers import core_update as cu

    action = (args.get("action") or "check").strip().lower()
    branch = (args.get("branch") or "master").strip() or "master"
    manifest = cu.load_manifest()

    try:
        if action == "list":
            files = cu.kernel_files(manifest)
            lines = [f"内核(L1)白名单 · 共 {len(files)} 个文件 · 只有这些会被 update_core 同步:"]
            for group, items in (manifest.get("kernel") or {}).items():
                lines.append(f"\n  ▸ {group} ({len(items)})")
                for f in items:
                    lines.append(f"      {f}")
            never = manifest.get("never_sync") or []
            lines.append("\n清单外【永不同步】(你的灵魂/数据/应用):")
            for n in never:
                lines.append(f"      {n}")
            return ToolResult(ok=True, output="\n".join(lines))

        if action == "remotes":
            configured = cu.list_configured_remotes()
            if not configured:
                return ToolResult(ok=True, output=(
                    "本机没配置任何 git remote(升级源)。\n"
                    "加中心库源: git remote add gitee <中心库URL>\n"
                    "(支持多源 · 可同时加 gitee + github · update_core 时用 remote 参数选)"))
            lines = ["已配置的升级源 (remote):"]
            primary = ((manifest.get("sources") or {}).get("primary") or "").strip()
            for name, url in configured.items():
                mark = "  ← manifest 主源" if name == primary else ""
                lines.append(f"  {name}\t{url}{mark}")
            return ToolResult(ok=True, output="\n".join(lines))

        # 以下 action 都要先定 remote
        remote, why = cu.resolve_remote(args.get("remote"), manifest)
        if not remote:
            return ToolResult(ok=False, output="", error=why)

        if action in ("check", "preview"):
            ok, msg = cu.fetch(remote)
            if not ok:
                return ToolResult(ok=False, output="", error=f"fetch 失败 · {msg}")
            d = cu.diff_kernel(remote, branch)
            if d.get("error"):
                return ToolResult(ok=False, output="", error=d["error"])
            changed, added, deleted = d["changed"], d["added"], d["deleted"]
            total = len(changed) + len(added)
            if total == 0 and not deleted:
                return ToolResult(ok=True, output=(
                    f"✅ 内核已是最新 ({why} · 分支 {branch}) · 没有白名单文件需要更新。\n"
                    f"你的应用 / 工作流 / soul 灵魂记忆本来也不在更新范围内。"))
            lines = [f"内核更新预览 · 源={why} · 分支 {branch}", ""]
            if changed:
                lines.append(f"  改动 {len(changed)} 个内核文件:")
                lines += [f"    ~ {f}" for f in changed]
            if added:
                lines.append(f"  新增 {len(added)} 个内核文件:")
                lines += [f"    + {f}" for f in added]
            if deleted:
                lines.append(f"  中心库已删 {len(deleted)} 个 (update_core 不会删你本地 · 仅提示):")
                lines += [f"    - {f}" for f in deleted]
            lines.append("")
            lines.append("⛑  只会覆盖上面列出的白名单文件 · 你的 soul/ data/ 应用 物理不碰。")
            if action == "preview" and total:
                diff_text = cu.preview_diff(remote, changed + added, branch)
                lines.append("\n──── 具体 diff ────\n" + diff_text)
            else:
                lines.append("想看具体改了什么 → action=preview · 确认升级 → action=apply")
            return ToolResult(ok=True, output="\n".join(lines))

        if action == "apply":
            res = cu.apply_update(remote, branch)
            if not res["ok"]:
                return ToolResult(ok=False, output="",
                                  error=f"{res['note']}\n(覆盖前 checkpoint: {res['checkpoint']})")
            up, add = res["updated"], res["added"]
            if not up and not add:
                return ToolResult(ok=True, output=(
                    f"✅ {res['note']}\n源={why} · 分支 {branch}\n"
                    f"checkpoint: {res['checkpoint']}"))
            lines = [f"✅ 内核已升级 · 源={why} · 分支 {branch}", ""]
            if up:
                lines.append(f"  覆盖 {len(up)} 个: " + ", ".join(up))
            if add:
                lines.append(f"  新增 {len(add)} 个: " + ", ".join(add))
            if res["skipped_deleted"]:
                lines.append(f"  跳过(中心库已删·没动你的): " + ", ".join(res["skipped_deleted"]))
            lines.append(f"\n  落袋: {res['checkpoint']}")
            if res["commit_sha"]:
                lines.append(f"  本次更新已 commit · {res['commit_sha']} (想回退: git revert {res['commit_sha']})")
            lines.append("\n⚠ 内核是 daemon 代码 · 改完需要【重启 daemon】才生效。")
            lines.append("  你的应用 / 工作流 / soul 灵魂记忆一个字节都没动。")
            return ToolResult(ok=True, output="\n".join(lines))

        return ToolResult(ok=False, output="",
                          error=f"未知 action: {action} · 可选: list / remotes / check / preview / apply")

    except Exception as e:
        return ToolResult(ok=False, output="", error=f"tool internal error: {type(e).__name__}: {e}")


SPEC = ToolSpec(
    name="update_core",
    description=(
        "Selectively upgrade the L1 KERNEL infrastructure of this Daemonkey from the central "
        "repo (gitee/github), touching ONLY the files whitelisted in core_manifest.json. "
        "The user's own apps, workflows, and soul/ memories are NEVER overwritten — they are "
        "not even passed to git's checkout command, so they are physically untouchable.\n\n"
        "This is how an open-source Daemonkey user pulls shared infrastructure fixes (write-file "
        "safety, edit lock, git discipline, daemon self-rescue) without losing their own evolution.\n\n"
        "Actions:\n"
        "  list     · show the kernel whitelist + the never-sync list (read-only)\n"
        "  remotes  · show configured upgrade sources / git remotes (read-only)\n"
        "  check    · fetch + report which whitelist files have updates (read-only)\n"
        "  preview  · like check, plus the actual git diff text (read-only)\n"
        "  apply    · checkpoint-commit first, then overwrite ONLY differing whitelist files "
        "from the remote, then commit the update (CONFIRM · needs restart to take effect)\n\n"
        "Safety: apply always git-commits the working tree first (checkpoint), so every change "
        "is revertable. Soul/data/apps are excluded by the manifest and never appear in the "
        "checkout command.\n\n"
        "NLP triggers:\n"
        "  - '看看内核有没有更新' → check\n"
        "  - '内核更新改了啥' → preview\n"
        "  - '升级内核 / 同步最新内核' → apply\n"
        "  - '能从哪几个源拉' → remotes"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "remotes", "check", "preview", "apply"],
                "description": "Which operation. Default 'check'.",
            },
            "remote": {
                "type": "string",
                "description": (
                    "Which upgrade source to pull from (e.g. 'gitee' or 'github'). "
                    "If omitted, uses core_manifest.json sources.primary, or the only configured "
                    "remote. Multi-source supported."),
            },
            "branch": {
                "type": "string",
                "description": "Remote branch holding the source-of-truth kernel. Default 'master'.",
            },
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
    classify=_classify,
)
register_tool(SPEC)
