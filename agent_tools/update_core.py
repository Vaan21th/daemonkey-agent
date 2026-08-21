"""
agent_tools/update_core.py
==========================
Daemonkey 通过对话拉取"内核(L1)升级" · 卷六十四续六 · 2026-06-08

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
    from workers import core_fingerprint as cf
    from workers import core_update as cu
    from workers import kernel_takeover as kt

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
            # 版本号对比 (卷七十四续二十) · fetch 之后远程 ref 已就位 · 拿两边 core_version 比
            lv = cu.local_core_version(manifest)
            rv = cu.remote_core_version(remote, branch)
            ver_line = f"内核版本 · 本地 {lv or '?'} · 远程 {rv or '?'}"
            if lv and rv and lv != rv:
                ver_line += "  ← 有新版本可升级!"
            d = cu.diff_kernel(remote, branch)
            if d.get("error"):
                return ToolResult(ok=False, output="", error=d["error"])
            changed, added, deleted = d["changed"], d["added"], d["deleted"]
            total = len(changed) + len(added)
            if total == 0 and not deleted:
                return ToolResult(ok=True, output=(
                    f"{ver_line}\n"
                    f"✅ 内核已是最新 ({why} · 分支 {branch}) · 没有白名单文件需要更新。\n"
                    f"你的应用 / 工作流 / soul 灵魂记忆本来也不在更新范围内。"))
            lines = [ver_line, f"内核更新预览 · 源={why} · 分支 {branch}", ""]
            if changed:
                lines.append(f"  改动 {len(changed)} 个内核文件:")
                lines += [f"    ~ {f}" for f in changed]
            if added:
                lines.append(f"  新增 {len(added)} 个内核文件:")
                lines += [f"    + {f}" for f in added]
            if deleted:
                lines.append(f"  中心库已删 {len(deleted)} 个 (update_core 不会删你本地 · 仅提示):")
                lines += [f"    - {f}" for f in deleted]
            taken = kt.load()
            taken_in_update = [f for f in (changed + added) if f in taken]
            if taken_in_update:
                lines.append("")
                lines.append("🔒 这些文件你已接管 · 官方有新版但升级【物理上不会碰它们】:")
                lines += [f"    = {f}" for f in taken_in_update]
                lines.append("  想交还给官方管 → 对我说「取消接管 <文件>」")
            dirty = cu.dirty_kernel_files(manifest)
            # 已接管的不会被覆盖 → 不该再警告"你改过会被覆盖"(那是虚惊)
            dirty_in_update = [f for f in (changed + added) if f in dirty and f not in taken]
            if dirty_in_update:
                lines.append("")
                # 0.9.6 起判定走基线指纹 · 所以是"跟官方版不一样"而不是"未提交改动"——
                #   改动 commit 过也照样认得出
                lines.append("⚠ 这些待更新的内核文件 · 你改过 (内容跟官方版不一样):")
                lines += [f"    ! {f}" for f in dirty_in_update]
                lines.append("  升级会先备份你的版本 + checkpoint 存档 · 覆盖后可对我说「合并我的改动」拿回来。")
                lines.append("  不想让官方碰某个文件 → 对我说「这文件我自己管」(接管后永不被覆盖)。")

            # ── 整机漂移总览 ──
            # 出问题时第一句要能回答:「你这台机器跟官方差多少」。 差异是排查的起点 ——
            # 官方版跑得好好的功能在用户那儿坏了·先看是不是他自己改过那块。
            if not cf.has_baseline():
                lines.append("")
                lines.append("ℹ 这台还没有官方基线指纹 (0.9.6 之前装的) · 本次升级会补上。"
                             "之后「哪些内核文件你改过」就能精确认出 —— 不再受 commit 影响。")
            else:
                drift_other = [f for f in dirty if f not in (changed + added)]
                lines.append("")
                if not dirty:
                    lines.append(f"✓ 内核与官方 {cf.baseline_version()} 完全一致 · 没有本地改动")
                else:
                    n_taken = len([f for f in dirty if f in taken])
                    tail = f" · 其中 {n_taken} 个是你接管的" if n_taken else ""
                    lines.append(f"ℹ 全机内核有 {len(dirty)} 个文件跟官方 "
                                 f"{cf.baseline_version()} 不一样{tail}")
                    if drift_other:
                        lines.append("  (本次不更新它们·仅告知你改过:)")
                        lines += [f"    · {f}" for f in drift_other[:8]]
                        if len(drift_other) > 8:
                            lines.append(f"    · ... 另 {len(drift_other) - 8} 个")
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
            if res.get("passes", 1) >= 2:
                lines.append("  (清单本身有更新 · 已自动按新清单补拉了一轮新增内核文件)")
            elif "core_manifest.json" in (up + add):
                # 本地跑的是旧版 apply(无自动补轮):新清单已就位但新增文件这轮没进来
                lines.append("  ⚠ 本次更新了内核清单本身 · 请【再执行一次升级】把新增内核文件补齐。")
            if res["skipped_deleted"]:
                lines.append("  跳过(中心库已删·没动你的): " + ", ".join(res["skipped_deleted"]))
            lines.append(f"\n  落袋: {res['checkpoint']}")
            if res["commit_sha"]:
                lines.append(f"  本次更新已 commit · {res['commit_sha']} (想回退: git revert {res['commit_sha']})")
            # 0.8.4 · 升级保护层 · 用户魔改备份报告
            uos = res.get("user_overrides") or []
            if uos:
                lines.append("")
                lines.append("⚠ 以下文件你本地改过 · 官方这版也更新了它们 · 你的版本已物理备份:")
                for uo in uos:
                    bak = uo.get("backup") or "(备份失败·但 git checkpoint 里有)"
                    lines.append(f"    ! {uo['file']}  → 备份: {bak}")
                lines.append("  需要把你的改动合并回来 · 对我说「合并我的改动」即可。")
                lines.append("  不想让官方以后再碰它 → 「这文件我自己管」(接管后永不被覆盖)。")
            # 0.9.6 · 用户接管 · 官方有新版但物理没覆盖
            skipped_take = res.get("skipped_takeover") or []
            if skipped_take:
                lines.append("")
                lines.append("🔒 这些文件你已接管 · 官方这版更新了它们 · 但一个字节都没覆盖:")
                lines += [f"    = {f}" for f in skipped_take]
                lines.append("  想看官方改了什么 → action=preview · 想交还官方管 → 「取消接管 <文件>」")
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
