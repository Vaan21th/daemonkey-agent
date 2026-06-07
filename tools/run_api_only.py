"""
tools/run_api_only.py
=====================

只跑 API（不进交互终端）·便于 background 启动·让 BRO 在另一个终端继续聊。

用法：
  python tools/run_api_only.py
  python tools/run_api_only.py --port 7860 --host 127.0.0.1

跟 opus_daemon.py 的区别：
  - opus_daemon.py 是 BRO 在终端跟 OPUS 对话的入口 · 同时后台起 API
  - tools/run_api_only.py 只起 API · 用于无人值守 / background process / WebUI-only 模式

API 起来后会一直 block · Ctrl-C 退出。

────────────────────────────────────────────────────────────────────
卷四十四 I · wish-12946ade · 给下根毛 OPUS 看：
────────────────────────────────────────────────────────────────────
  本脚本是 daemon-only API 启动入口的 single source of truth。
  你 (下根毛) 起 daemon 时优先级:
    1. **真人模式**: 让 BRO 双击 start.bat → opus-launcher.ps1 (GUI 启动器·有
       已开进程检测 + 三选一对话框)
    2. **后台 / 调试**: python tools/run_api_only.py --port 7860
    3. **不要**自己写 daemon_api_only.py / start_daemon.py — 已经有这一个
       (上根毛 2026-05-25 凌晨 1:55 干过这事·错的反面教材)

  铁律 5 配套: 改完 .py 之后 daemon 不会自动 reload·必须杀旧起新 ·
  详见 data/cognition/daemon_rules.md。
────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# 跟 opus_daemon.py 同根目录
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── 卷四十六续二 · wish-503f93e0 · 启动时立刻隐藏 console 窗口 ──
# belt-and-suspenders 最后一道防线: 即使用 python.exe 启动 (console subsystem) ·
# 内核在 CreateProcess 时分配了 console → 立刻 FreeConsole + ShowWindow(SW_HIDE)
if sys.platform.startswith("win"):
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass  # 不要因为藏窗口失败就崩 daemon


def _load_env():
    """读 .env 文件 · 不依赖 python-dotenv（保持依赖轻）"""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _init_runtime():
    """初始化 RUNTIME · 卷三十三补丁修：之前漏初始化导致 /chat → 500
    "daemon RUNTIME not initialized; API called too early?"

    卷三十七 · 优先从 data/provider_configs.json 拿 active config · 没文件就从 .env 迁移
    (workers/provider_configs._migrate_from_env 自动建第一条 cfg)·让多 config UI 直接可用。
    """
    from daemon_runtime import RUNTIME
    from daemon_provider import detect_provider, setup_client, write_env_kv
    from soul_loader import load_soul
    from workers.provider_configs import get_active_config, apply_config_to_env

    # 卷三十七 · 先把 active config 同步进 env · 再走旧 setup_client 路径
    active = get_active_config(include_key=True)
    if active:
        apply_config_to_env(active)
        print(f"[opus-api] active provider config: {active.get('name')} · "
              f"{active.get('provider_kind')} / {active.get('model')}")

    soul = load_soul()
    RUNTIME.system_prompt = soul.system_prompt
    RUNTIME.persist_callback = lambda new_model: write_env_kv("OPUS_MODEL", new_model)

    provider = detect_provider()

    # 形态 Z · 全新状态（相遇前还没配 key）：不建 client·daemon 照常起，
    # /ui 进相遇页配 key·相遇 save-key 时热建 RUNTIME.client·相遇完进 chat 即可对话。
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPUS_API_KEY"))
    if not has_key:
        RUNTIME.provider = provider
        RUNTIME.model = os.environ.get("OPUS_MODEL", "")
        RUNTIME.base_url = os.environ.get("OPUS_BASE_URL") or None
        RUNTIME.client = None
        print("[opus-api] 还没配置 API key · daemon 以『相遇』模式启动 · "
              "在 /ui 完成相遇后即可对话")
        return

    client, model, base_url = setup_client(provider)
    RUNTIME.model = model
    RUNTIME.base_url = base_url
    RUNTIME.client = client
    RUNTIME.provider = provider
    print(f"[opus-api] RUNTIME 已就绪 · provider={provider} model={model}")


def _maybe_start_scheduler():
    """跟 opus_daemon._maybe_start_scheduler 一样 · 后台跑信息雷达"""
    try:
        from workers.scheduler import start_radar_scheduler_in_background
        thread = start_radar_scheduler_in_background()
        if thread is not None and thread.is_alive():
            interval = (os.environ.get("OPUS_RADAR_INTERVAL_MIN") or "30").strip()
            print(f"[opus-api] radar scheduler 已起 · 每 {interval} min")
    except Exception as e:
        print(f"[opus-api] scheduler 起不来（不影响 API）: {e}")


def _maybe_start_capability_mirror():
    """卷四十五 · capability_mirror 自驱 · 默认禁用 · 需 OPUS_CAPABILITY_MIRROR_INTERVAL_DAYS>0"""
    try:
        from workers.scheduler import start_capability_mirror_scheduler_in_background
        thread = start_capability_mirror_scheduler_in_background()
        if thread is not None and thread.is_alive():
            interval = (os.environ.get("OPUS_CAPABILITY_MIRROR_INTERVAL_DAYS") or "0").strip()
            print(f"[opus-api] capability_mirror scheduler 已起 · 每 {interval} 天 · 跑完桌宠切 surprised")
        else:
            print(
                "[opus-api] capability_mirror scheduler 禁用 · "
                "设 OPUS_CAPABILITY_MIRROR_INTERVAL_DAYS=7 启用周次自动跑"
            )
    except Exception as e:
        print(f"[opus-api] capability_mirror scheduler 起不来（不影响 API）: {e}")


def _maybe_start_proactive():
    """卷六十 · 主动 CALL BRO 自驱 · 总开关 OPUS_PROACTIVE_CALL (默认开)"""
    try:
        from workers.scheduler import start_proactive_scheduler_in_background
        thread = start_proactive_scheduler_in_background()
        if thread is not None and thread.is_alive():
            interval = (os.environ.get("OPUS_PROACTIVE_INTERVAL_MIN") or "60").strip()
            print(f"[opus-api] proactive scheduler 已起 · 每 {interval} min 查一次该不该 CALL（OPUS_PROACTIVE_CALL=0 禁用）")
        else:
            print("[opus-api] proactive scheduler 禁用 (OPUS_PROACTIVE_INTERVAL_MIN<=0)")
    except Exception as e:
        print(f"[opus-api] proactive scheduler 起不来（不影响 API）: {e}")


def _maybe_start_wechat():
    """卷六十一 · iLink 微信收消息监听 · 扫过码 (有 ilink_token.json) 且 OPUS_WECHAT_ILINK!=0 才起"""
    try:
        from workers.wechat_listener import start_listener_in_background
        thread = start_listener_in_background()
        if thread is not None and thread.is_alive():
            print("[opus-api] wechat listener 已起 · BRO 在微信发消息→OPUS 大脑→回复（发 'opus stop' 静默）")
        else:
            print("[opus-api] wechat listener 禁用 · 未扫码 (data/runtime/ilink_token.json 缺) 或 OPUS_WECHAT_ILINK=0")
    except Exception as e:
        print(f"[opus-api] wechat listener 起不来（不影响 API）: {e}")


def main():
    # 卷四十六 IV (2026-05-26 第二十二根毛): stdout/stderr line-buffered
    # daemon 被 spawn 时 stdout 重定向到 data/daemon.out · 默认 block-buffered ·
    # 排查 [opus-resume] / [opus-api] log 看不见。 reconfigure 让它跟 TTY 一样
    # 每 \n flush · 调试期 daemon.out 实时可读 · 生产无感知。
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    _load_env()

    # Daemonkey · 本机用户永不手填 token：daemon 启动若 .env 没 OPUS_API_TOKEN 就自动生成 ·
    # loopback 中间件 (api_routes/_deps.py) 给同机 127.0.0.1 请求覆盖注入它 → 前端 chat 无需碰 token。
    # (没这一步·loopback 豁免因 env_token 为空而失效·chat.js 会弹『第一次需要填 token』框)
    if not (os.environ.get("OPUS_API_TOKEN") or "").strip():
        try:
            import secrets
            from daemon_provider import write_env_kv
            _tok = secrets.token_urlsafe(32)
            write_env_kv("OPUS_API_TOKEN", _tok)
            os.environ["OPUS_API_TOKEN"] = _tok
            print("[opus-api] 自动生成 OPUS_API_TOKEN · 本机 loopback 免手填")
        except Exception as e:
            print(f"[opus-api] WARN · 自动生成 OPUS_API_TOKEN 失败: {type(e).__name__}: {e}")

    # 卷四十六 III 补丁 5 · R1 · 统一 logging (RotatingFile + trace_id)
    # daemon 全生命周期前装好 · 让后续所有 logger.info 都落到 data/runtime/daemon.log
    # print() 兼容保留 (写 stdout / _daemon_7860.log) · 两套并行
    try:
        from workers.opus_logging import init_logging
        init_logging()
    except Exception as e:
        print(f"[opus-api] WARN · opus_logging init 出错 (不阻塞启动): {type(e).__name__}: {e}")

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("OPUS_API_PORT") or 7860))
    ap.add_argument("--log-level", default="warning")
    ap.add_argument("--no-scheduler", action="store_true", help="跳过后台 radar scheduler")
    args = ap.parse_args()

    # 卷四十六 III · wish-ed5553d5 · daemon lifecycle init (pid 锁 + 重启续场 + crash 检测)
    # 卷四十七 · safe_mode: 崩溃循环熔断 (见 workers/daemon_lifecycle.detect_crash_loop)
    lc = None
    safe_mode = False
    try:
        from workers.daemon_lifecycle import init_lifecycle
        lc = init_lifecycle(args.host, args.port)
        if not lc["ok"]:
            print(f"[opus-api] FATAL · pid lock 拿不到 (daemon 已经在跑?):\n  {lc['lock_message']}")
            sys.exit(2)
        safe_mode = bool(lc.get("safe_mode"))
        if safe_mode:
            cl = lc.get("crash_loop") or {}
            print("=" * 64)
            print("[opus-api] ⚠️  SAFE MODE · 检测到崩溃循环")
            print(f"[opus-api]     最近 {cl.get('window_sec')}s 内崩了 {cl.get('crashes')} 次 (阈值 {cl.get('threshold')})")
            print("[opus-api]     → 自动续场已隔离 (restart_request.quarantined.json)")
            print("[opus-api]     → 后台调度 (radar / capability_mirror) 已跳过")
            print("[opus-api]     → daemon 本体照常起 · /ui /chat 可用 · 请先排查再重启")
            print("[opus-api]     修好后干净重启 (不再崩) 会自动退出安全模式")
            print("=" * 64)
        if lc.get("restart_request"):
            req = lc["restart_request"]
            print(f"[opus-api] 检测到 restart_request · reason='{(req.get('reason') or '')[:80]}' · "
                  f"session={req.get('session_id')} · 已注续场 system message")
        if lc.get("crash_marker"):
            cm = lc["crash_marker"]
            print(f"[opus-api] 上次 daemon (pid={cm.get('old_pid')}) 异常退出 · "
                  f"已给 {lc['resume_stats'].get('crash_resumed', 0)} 个活跃 session 注 crash 通知")
    except Exception as e:
        print(f"[opus-api] WARN · daemon_lifecycle init 出错 (不阻塞启动): {type(e).__name__}: {e}")

    # 卷五十四 · A 柱 · 启动前端自检闸 (build_app 之前能跑的部分)
    # 前端 JS 语法坏 (如卷五十四砍断的 chat.js) · 且有可信 last-good → 自动回退 + spawn 新 daemon。
    # 只对"明确的代码坏了"自愈 · 不碰 provider/key 这类环境问题 (那种回退也没用)。
    try:
        from workers.boot_health import preflight_health, try_auto_revert
        fe_ok, fe_msg = preflight_health()
        if not fe_ok:
            print(f"[opus-api] ⚠️  启动前端自检未过:\n{fe_msg}", flush=True)
            if try_auto_revert(reason=f"preflight frontend unhealthy: {fe_msg[:160]}"):
                return  # 已 reset 到 last-good + spawn 新 daemon · 本进程即将退出
    except Exception as e:
        print(f"[opus-api] WARN · boot_health 前端自检跳过 (不阻塞启动): {type(e).__name__}: {e}")

    # 卷三十三补丁 · 关键修复：必须先初始化 RUNTIME · 否则 /chat 端点直接 500
    try:
        _init_runtime()
    except SystemExit as e:
        print(f"[opus-api] FATAL · provider 初始化失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[opus-api] FATAL · RUNTIME 初始化失败: {type(e).__name__}: {e}")
        sys.exit(1)

    # 卷四十六 III 补丁 3 · 自动续场 turn (有 follow_up_message 时触发 background LLM)
    if lc and lc.get("restart_request"):
        try:
            from workers.resume_runner import schedule_resume_turn
            if schedule_resume_turn(lc["restart_request"]):
                fu = (lc["restart_request"].get("follow_up_message") or "")[:80]
                print(f"[opus-api] 自动续场 turn 已 schedule · follow_up='{fu}...'")
        except Exception as e:
            print(f"[opus-api] WARN · 自动续场 schedule 失败 (不阻塞): {type(e).__name__}: {e}")

    # safe_mode 下不起后台调度 (radar / capability_mirror) · 减少崩溃面 · 让 daemon 先稳住
    if not args.no_scheduler and not safe_mode:
        _maybe_start_scheduler()
        _maybe_start_capability_mirror()
        _maybe_start_proactive()
        _maybe_start_wechat()
    elif safe_mode:
        print("[opus-api] SAFE MODE · 跳过后台调度启动")

    # 卷四十六 III 补丁 5 · Y6 · .env hot reload watcher
    # 后台 thread · 默认每 5s poll .env mtime · 改了自动 reload 白名单字段
    try:
        from workers.env_reloader import start_in_background as start_env_watcher
        t = start_env_watcher(poll_interval_sec=5.0)
        if t and t.is_alive():
            print("[opus-api] env reloader watcher 已起 · .env 改动自动热切 (白名单字段)")
    except Exception as e:
        print(f"[opus-api] env reloader 起不来 (不影响 API): {type(e).__name__}: {e}")

    from daemon_api import build_app
    import uvicorn

    # 卷五十四 · A 柱 · build_app 抛错 = Python 级起不来 (import/语法/路由雷) → 尝试自动回退 last-good
    try:
        app = build_app()
    except Exception as e:
        import traceback
        print(f"[opus-api] FATAL · build_app 失败: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        try:
            from workers.boot_health import try_auto_revert
            if try_auto_revert(reason=f"build_app failed: {type(e).__name__}: {e}"):
                return  # 已回退 + spawn 新 daemon
        except Exception as re:
            print(f"[opus-api] auto_revert 也失败了: {type(re).__name__}: {re}", flush=True)
        sys.exit(1)

    # 卷五十四 · A 柱 · 健康存活后才前移 last-good (撑过 grace window + 自检健康 = 配当回退点)
    try:
        from workers.boot_health import schedule_last_good_advance
        schedule_last_good_advance(safe_mode=safe_mode)
    except Exception as e:
        print(f"[opus-api] WARN · last-good 前移调度失败 (不阻塞): {type(e).__name__}: {e}")

    print(f"[opus-api] starting on http://{args.host}:{args.port} ...")
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        access_log=False,
    )


if __name__ == "__main__":
    main()
