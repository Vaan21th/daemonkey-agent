"""
agent_tools/request_restart.py
==============================

OPUS 让 daemon 重启的『正确姿势』( III · 2026-05-26 · wish-ed5553d5)

----------------------------------------------------------------------
为什么有这个工具
----------------------------------------------------------------------

 II 反面: session api-...063247_e404f8 出过事 ——
  OPUS 想"装上新代码" · 调 `shell_exec Stop-Process python`
  → daemon 进程被杀
  → 当前 tool_call 没 result
  → session jsonl 残一条 dangling assistant.tool_calls
  → 下次加载该 session 直接 HTTP 500

这工具是『官方重启路径』·让 OPUS 想重启时:
  1. 调 request_restart(reason="...") — TIER_CONFIRM · 用户 'y' 才走
  2. daemon 立刻写 data/runtime/restart_request.json
  3. 当前 tool 立刻同步返 result · session 状态机干净
  4. 然后 daemon 自己做 graceful shutdown
  5. 用户 / launcher 重启 daemon
  6. 新 daemon 启动时 consume restart_request · 自动给 session 注 system message
     告诉 OPUS『刚才申请的重启完成 · 继续上次的任务』

----------------------------------------------------------------------
工具是怎么真重启的 ( IV · 2026-05-26 改自原版『只自爆不自救』)
----------------------------------------------------------------------

**这工具会 spawn 替代子进程**·跟 `/restart-daemon` endpoint 同一套路径:
  1. 用 `subprocess.Popen` 起一个新 Python 进程·跑同样的 argv
  2. 子进程 env 带 `OPUS_DAEMON_TAKEOVER_PID=<parent_pid>` · acquire_pid_lock 看到
     这个 env 就**等 parent 死再 acquire** (workers/daemon_lifecycle.py:197) ·
     不撞双 daemon 的拒启动
  3. parent (老 daemon) 等子进程 1.5s 绑端口窗口 · `mark_graceful_shutdown` · `os._exit(0)`
  4. 子进程 consume restart_request.json · inject system notice + `schedule_resume_turn`
     spawn follow_up turn

**为什么改**: 原版 (2026-05-26 早 06:00 写) 假设有 launcher 监听 restart_request.json
自动重启 · 当时还没 takeover 模式 · 怕 spawn 撞 pid_lock chicken-and-egg。 但实际
launcher 没有这个 watcher · OPUS 调 request_restart → daemon 真死 → 没人接 ·
用户 必须手动 start.bat (用户 2026-05-26 14:56 实测踩坑)。

takeover 模式已经 ready · /restart-daemon endpoint 跑通过 N 次·复制过来即可。

**对比 /restart-daemon endpoint**: 同一个 spawn 逻辑 · 同一个 takeover env · 唯一
区别是这边 _trigger_shutdown_async 加了 `time.sleep(delay_sec)` 给当前 tool result
走完 LLM → 写回 session 的时间窗。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool
from ._subprocess_helper import detached_kwargs, pythonw_path

ROOT = Path(__file__).resolve().parent.parent


def _summarize(args: dict) -> str:
    reason = (args.get("reason") or "").strip()
    style = (args.get("style") or "graceful").strip()
    return f"request_restart  reason='{reason[:80]}'  style={style}"


def _trigger_shutdown_async(delay_sec: float = 2.0, reason: str = "request_restart_tool") -> None:
    """延迟几秒后让 daemon 自杀·**并 spawn 替代子进程接管端口** ( IV · wish-后续 · 2026-05-26)

     III 补丁 · 自杀前显式 mark_graceful_shutdown · 否则下次启动会误判 crash

     IV · 2026-05-26 用户 测真实场景发现 GAP:
      原版只 mark_graceful + os._exit(0) · 假设有 launcher 监听 restart_request.json
      自动重启 (源码注释 line 31-41)。 但实际 launcher 没有这个 watcher · OPUS 调
      request_restart → daemon 真死 → 没人 spawn 子进程 → restart_request.json 没人
      consume → follow_up turn 也跑不了 → 用户 端到端断链 12 min·必须手动 start.bat。

      解法: 跟 daemon_api.py /restart-daemon endpoint 一样 spawn 子进程 + 设
      OPUS_DAEMON_TAKEOVER_PID env · 子进程 acquire_pid_lock 自动等 parent 死 ·
      重启完全自包含 · 不依赖外部 launcher。
    """

    def _kill():
        import subprocess
        from pathlib import Path

        time.sleep(delay_sec)

        root = Path(__file__).resolve().parent.parent
        argv = [pythonw_path()] + sys.argv
        out_path = root / "data" / "daemon.out"
        err_path = root / "data" / "daemon.err"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        parent_pid = os.getpid()
        child_env = os.environ.copy()
        child_env["OPUS_DAEMON_TAKEOVER_PID"] = str(parent_pid)

        try:
            out_f = open(out_path, "ab")
            err_f = open(err_path, "ab")
            subprocess.Popen(
                argv,
                close_fds=False,
                stdin=subprocess.DEVNULL,
                stdout=out_f, stderr=err_f, cwd=str(root),
                env=child_env,
                **detached_kwargs(),
            )
            time.sleep(1.5)
        except Exception as e:
            print(f"[request_restart] spawn 子进程失败 (用户 需手动 start.bat): "
                  f"{type(e).__name__}: {e}", flush=True)

        try:
            from workers.daemon_lifecycle import mark_graceful_shutdown
            mark_graceful_shutdown(reason)
        except Exception:
            pass

        try:
            if sys.platform.startswith("win"):
                os._exit(0)
            else:
                import signal
                os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            os._exit(1)

    t = threading.Thread(target=_kill, daemon=True, name="opus-restart-killer")
    t.start()


def _run(args: dict) -> ToolResult:
    reason = (args.get("reason") or "").strip()
    if not reason:
        return ToolResult(ok=False, output="", error="missing 'reason' (告诉 用户 为啥要重启)")
    if len(reason) > 500:
        return ToolResult(ok=False, output="", error="reason too long (max 500 chars)")

    session_id = (args.get("session_id") or "").strip() or None
    #  III hookup · 没显式传 session_id 就从 RUNTIME 拿当前 session
    if not session_id:
        try:
            from daemon_runtime import RUNTIME
            session_id = (RUNTIME.session_id or "").strip() or None
        except Exception:
            pass
    tool_call_id = (args.get("tool_call_id") or "").strip() or None
    style = (args.get("style") or "graceful").strip().lower()
    if style not in ("graceful", "dry_run"):
        return ToolResult(ok=False, output="", error="style must be 'graceful' or 'dry_run'")

    #  III 补丁 3 · 自动续场任务 (用户 反馈: 重启后不要让我手动发消息触发 OPUS 继续)
    follow_up_message = (args.get("follow_up_message") or "").strip() or None
    if follow_up_message and len(follow_up_message) > 1000:
        return ToolResult(ok=False, output="", error="follow_up_message too long (max 1000 chars)")

    try:
        from workers import daemon_lifecycle
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"daemon_lifecycle import failed: {e}")

    try:
        req = daemon_lifecycle.write_restart_request(
            reason=reason,
            session_id=session_id,
            tool_call_id=tool_call_id,
            follow_up_message=follow_up_message,
        )
    except Exception as e:
        return ToolResult(ok=False, output="", error=f"write_restart_request failed: {type(e).__name__}: {e}")

    if style == "dry_run":
        return ToolResult(
            ok=True,
            output=(
                f"DRY RUN · restart_request.json 已写 · daemon 没真重启\n"
                f"  reason: {reason}\n"
                f"  session_id: {session_id}\n"
                f"  tool_call_id: {tool_call_id}\n"
                f"  follow_up_message: {follow_up_message or '(None)'}\n"
                f"  路径: data/runtime/restart_request.json\n\n"
                f"删了这个文件就可以取消。 想真重启 · 把 style 改成 'graceful' 再调一次。"
            ),
        )

    #  · 重启前『前端 JS 语法闸』(2026-06-03 事故根治)
    # 病根: OPUS 用 python_exec 字符串切片改 chat.js · 边界算错把尾部 1660 行吞了 ·
    #   文件停在 `function loadMoreWishes() {` → JS 语法错 → 浏览器整个白屏。 而
    #   verify_daemon_endpoints 只验 Python 路由 · 坏前端顶着"82/82 全绿"被 commit + 重启 ·
    #   用户 打开 WebUI 全死。 这里在 checkpoint + 自爆之前先验前端: 语法坏就拒绝重启 ·
    #   连 checkpoint 都不做 · 逼 OPUS 先把 JS 修好。 (node 缺失会降级成启发式·绝不硬崩)
    try:
        from workers.frontend_check import check_static_js, format_report
        fe = check_static_js()
        if not fe["ok"]:
            return ToolResult(
                ok=False,
                output="",
                error=(
                    "⛔ 重启被拦下 · 前端 JS 语法坏了 · 现在重启会让 WebUI 在浏览器里整个白屏。\n\n"
                    + format_report(fe)
                    + "\n\n大概率是你刚才用 python_exec 裸字符串切片改 static/*.js 时边界算错、把文件尾部吞了。\n"
                      "→ 先把上面这个 JS 文件修好 (node --check 过了再说) · 再调 request_restart。\n"
                      "→ 教训: 别用 python_exec 切片改大前端文件 · 用 edit_file · 它不会静默丢掉尾巴。"
                ),
            )
    except ImportError:
        pass  # 校验器本身缺失不阻塞重启 · 降级放行

    #  · ①号机制 · 重启前自动 checkpoint commit
    # 病根 (): 写完代码 request_restart · 改动是裸的工作区改动 · 一旦后续
    # crash → rollback (stash) 就灰飞烟灭 (日历功能就是这么没的)。 这里在自爆前先把
    # 工作区落成一个 commit · 物理上保证"写完的活儿不会被任何重启/回退抹掉"。
    checkpoint_note = ""
    try:
        from workers.git_ops import checkpoint_commit
        cp = checkpoint_commit(f"request_restart · {reason[:80]}")
        checkpoint_note = f"\n  checkpoint: {cp.get('note', '')}"
    except Exception as e:
        checkpoint_note = f"\n  checkpoint: 跳过 (异常 {type(e).__name__}: {e})"

    _trigger_shutdown_async(delay_sec=2.0, reason=f"request_restart_tool: {reason[:120]}")

    auto_resume_note = ""
    if follow_up_message:
        auto_resume_note = (
            f"\n  5. **自动续场**: 新 daemon 起来后会以 '{follow_up_message[:80]}...' 作为 user message\n"
            f"     触发一次 background LLM turn · 你在 background 跑完落档到 session jsonl\n"
            f"     用户 不用手动发消息 · 进 WebUI 直接看你的验证结果\n"
            f"     (后台 turn auto_confirm='confirm' · 跟主对话同级 · AUTO+CONFIRM 自动 go·\n"
            f"      能跑 read_file/curl/python_exec/write_file/git commit 等验证类 · 只 GUARD 会被后台 skip/deny)"
        )

    return ToolResult(
        ok=True,
        output=(
            f"重启请求已落档 · daemon 将在 ~2 秒后自爆 (graceful)\n"
            f"  reason: {reason}\n"
            f"  session_id: {session_id}\n"
            f"  follow_up_message: {follow_up_message or '(None · 不会自动续场)'}\n"
            f"  pid: {os.getpid()}"
            f"{checkpoint_note}\n\n"
            f"接下来:\n"
            f"  1. daemon 自爆 · 用户 的下一个请求会撞 connection refused\n"
            f"  2. WebUI 自动重连新 daemon · 或 用户 点 🔄 重启按钮 · 或双击 start.bat\n"
            f"  3. 新 daemon 启动时 consume 这条 request · 给你这条 session 注 system message\n"
            f"  4. 你看到那条 system message · 继续之前的任务"
            f"{auto_resume_note}\n\n"
            f"判断成功的硬证据: 重启后 用户 截图里看到灰色 `[SYSTEM · 重启续场 · ...]` 那条 = 成功"
        ),
    )


SPEC = ToolSpec(
    name="request_restart",
    description=(
        "Request a graceful daemon restart. **Use this INSTEAD of `shell_exec Stop-Process python`** "
        "or `shell_exec taskkill python.exe` — those kill your own process and leave the session "
        "jsonl with dangling tool_calls (next session load → HTTP 500).\n\n"
        "**⚡ 强烈推荐: 总是带上 `follow_up_message`** ( IV · 2026-05-26 用户 强调):\n"
        "  你调 request_restart 一定是为了『装新代码 / 装新工具 / 清状态』来达成某个目标。\n"
        "  这个目标 = follow_up_message。 不填 = 重启完只 inject system notice · 用户 必须手动\n"
        "  发消息触发你继续 · 多一步操作 + 中断节奏。 填了 = 重启完新 daemon 自动 spawn\n"
        "  background turn · 你在后台跑 follow_up 任务 · 落档到 session · 用户 进 WebUI 直接看结果。\n"
        "  **规则**: 99% 场景都该填 · 留空只在『单纯清进程内存 · 没后续验证任务』时合理。\n\n"
        "  **填什么**: 用第一人称写给『重启后的自己』· 告诉它要干啥。 例子:\n"
        "    - 改了 daemon_api.py 加新 endpoint /foo → follow_up='跑 curl http://127.0.0.1:7860/foo 验证返回 200 + 字段对'\n"
        "    - 改了 workers/scheduler.py 调度间隔 → follow_up='调 read_file data/runtime/scheduler.log 看最近 1 min 是否按新间隔触发'\n"
        "    - 改了 agent_tools/X.py 注册新工具 → follow_up='调一次 X 工具用最小参数 · 验证它真在工具列表里 + 能 run'\n\n"
        "**How it works**:\n"
        "  - Writes data/runtime/restart_request.json with reason + session_id + tool_call_id + follow_up_message\n"
        "  - Triggers a delayed (~2s) graceful shutdown so this tool result reaches LLM and persists\n"
        "  - Next daemon start consumes the request and injects a system message into your session\n"
        "  - If follow_up_message 非空 · 新 daemon 自动以这条作为 user message 触发 background LLM turn · 你跑完落档 session\n"
        "  - You'll see '[SYSTEM · 重启续场]' on next message and know to continue\n\n"
        "**重要 · 重启后你怎么判断成功 ( III 反面教材 2026-05-26)**:\n"
        "  - 上根毛在端到端测试时 · daemon 真重启了 · 用户 看到了续场 system message · "
        "但 OPUS 复盘说『但你现在还能跟我说话 · 说明 daemon 没炸』 — **诊断完全反了**。\n"
        "  - 真相: 你能继续对话 · **恰恰是因为旧 daemon 真自爆 · 新 daemon 起来接力**。 session "
        "jsonl 持久化 · 新 daemon 读它 · 你的 context 看起来连续 · 但物理 daemon 已经换底座。\n"
        "  - 判断成功的硬证据 (任选其一):\n"
        "    (a) 用户 截图里能看到灰色 `[SYSTEM · 重启续场 · ...] 你之前调 request_restart 申请...` "
        "—— 这条只可能由新 daemon 注入 · 看到 = 端到端成功 · 不用再 grep 文件验证。\n"
        "    (b) 调 read_file('data/runtime/restart_history.jsonl') 看最近 1 min 内有没有 "
        "`daemon_stopped_graceful` + `daemon_started` + `restart_request_consumed` 三件套。\n"
        "    (c) 不要靠『我还能说话』反推 daemon 状态 · 这个推理是错的。\n\n"
        "**When to use**:\n"
        "  - You changed daemon-side .py code and need the running daemon to pick it up\n"
        "  - A new tool / app was registered and you want the LLM-side tool list refreshed\n"
        "  - You suspect daemon state corruption and want a clean restart\n\n"
        "**When NOT to use**:\n"
        "  - You only changed static files (static/*.js, *.css, *.md) — those don't need restart, 用户 can refresh browser\n"
        "  - You're not sure if the change needs restart — try without first; daemon_rules 铁律 5 says verify\n\n"
        "**Style**:\n"
        "  - graceful (default) — write request + trigger shutdown\n"
        "  - dry_run — write request, don't shut down (for testing the file format)"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Why restart is needed (用户 sees this before saying yes). Required.",
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Current session id (e.g. 'api-2026-05-26_063247_e404f8'). "
                    "Used to target the resume system-message injection. "
                    "If you don't know it, leave empty — RUNTIME.session_id 自动 fallback。"
                ),
            },
            "tool_call_id": {
                "type": "string",
                "description": "Current tool_call_id (helps debug · optional).",
            },
            "style": {
                "type": "string",
                "enum": ["graceful", "dry_run"],
                "description": "graceful = real restart · dry_run = write request file only · don't actually shut down. Default graceful.",
            },
            "follow_up_message": {
                "type": "string",
                "description": (
                    "**自动续场任务** ( III 补丁 3 · 2026-05-26 用户 反馈加的)。 "
                    "重启完成后 · 新 daemon 自动以这条作为 user message 触发 background LLM turn。 "
                    "用于『重启完成后请你帮我验证 X / 跑一遍 Y / 检查 Z 是否生效』这种场景。 "
                    "用户 不用手动发消息触发 · 进 WebUI 直接看你的验证结果。\n\n"
                    "**注意**: \n"
                    "  - 后台 turn auto_confirm='confirm' (跟主对话 WebUI 同级) · AUTO + CONFIRM 自动 go·\n"
                    "    能跑 read_file / grep / curl / python_exec / write_file / git commit 等 (够你验证自己刚写的代码)\n"
                    "  - 只有 GUARD 工具 (rm / git push --force / 大改文件) 会被后台 skip/deny (没 SSE 接收方)·\n"
                    "    那时把结论讲给 用户 由 用户 来确认下一步\n"
                    "  - max 1000 chars\n"
                    "  - 留空 = 不自动续场 · 只注 system message · 用户 手动发消息触发"
                ),
            },
        },
        "required": ["reason"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
