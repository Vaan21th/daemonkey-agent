"""agent_tools/service_start.py
================================

 K stage 2c++ · wish-8d6b76a6 · OPUS 启长跑后台服务的正确姿势

**为什么有这个工具**:
    shell_exec 设计来跑短任务 (默认 30s · 最长 300s)。 OPUS 启 GPT-SoVITS api.py
    这种长跑 server (永不退出) 时·shell_exec 等 subprocess exit · timeout 后
    Windows 下子进程成孤儿 (PID 17720 真实事故)。

    service_start 真正 detach 子进程 · 立刻返回 PID + healthcheck 结果 · 不阻塞 daemon。

**调用时机** (跟 shell_exec 区分):
    - 跑 git status / cat / ls / 短脚本 → shell_exec
    - 启动本地 server / api / scheduler / 长跑后台进程 → **service_start**
    - 起完后用 service_status 查活 / service_stop 停 / service_list 列总览

**典型场景**:
    - 用户 装了一个 API 应用 (例如 GPT-SoVITS / Stable Diffusion / 自己造的 API)
      OPUS 调 service_start 起服务 + 给 healthcheck_url 验通
    - daemon 重启不影响在跑的 service · services.json 持久化 · 重启后仍能 list/stop

**tier**:
    TIER_CONFIRM —— 起后台服务有副作用 (端口占用 / 资源占用 / 跨进程残留) · 用户 ✓ 才跑

**返回**:
    成功: pid + 启动时间 + healthcheck status + log_path
    失败: 看 log_path 排错的提示
"""
from __future__ import annotations

from . import TIER_CONFIRM, ToolResult, ToolSpec, register_tool


def _summarize(args: dict) -> str:
    name = (args.get("name") or "?").strip()
    cmd = (args.get("command") or "?").strip()
    cmd_short = cmd if len(cmd) <= 60 else cmd[:57] + "..."
    wd = (args.get("working_dir") or ".").strip()
    port = args.get("port")
    parts = [f"启动后台服务 `{name}`", f"command: `{cmd_short}`", f"工作目录: `{wd}`"]
    if port:
        parts.append(f"端口: {port}")
    return " · ".join(parts)


def _run(args: dict) -> ToolResult:
    from workers.service_runner import start_service

    name = (args.get("name") or "").strip()
    command = (args.get("command") or "").strip()
    working_dir = (args.get("working_dir") or "").strip()
    env = args.get("env") or {}
    if env and not isinstance(env, dict):
        return ToolResult(ok=False, output="", error="env 必须是 object {key: value} (得到非 dict)")
    port = args.get("port")
    if port is not None:
        try:
            port = int(port)
            if not (1 <= port <= 65535):
                return ToolResult(ok=False, output="", error=f"port 越界: {port}")
        except (TypeError, ValueError):
            return ToolResult(ok=False, output="", error=f"port 不是整数: {port!r}")

    healthcheck_url = (args.get("healthcheck_url") or "").strip() or None
    healthcheck_after_sec = float(args.get("healthcheck_after_sec") or 5.0)

    if not name:
        return ToolResult(ok=False, output="", error="name 必填")
    if not command:
        return ToolResult(ok=False, output="", error="command 必填")
    if not working_dir:
        return ToolResult(ok=False, output="", error="working_dir 必填 (例: 'C:/GPT-SoVITS' 或 '/opt/myservice')")

    result = start_service(
        name=name,
        command=command,
        working_dir=working_dir,
        env=env,
        port=port,
        healthcheck_url=healthcheck_url,
        healthcheck_after_sec=healthcheck_after_sec,
    )

    if not result.get("ok"):
        return ToolResult(
            ok=False,
            output="",
            error=result.get("message") or "service_start 失败 · 没 message",
        )

    lines = [
        f"service_start ok · `{name}` 已起",
        f"  pid: {result.get('pid')}",
        f"  started_at: {result.get('started_at')}",
        f"  log_path: {result.get('log_path')}",
    ]
    hc = result.get("healthcheck_status")
    if hc is True:
        lines.append(f"  healthcheck: ok ({result.get('healthcheck_msg')})")
    elif hc is False:
        lines.append(f"  healthcheck: FAIL ({result.get('healthcheck_msg')}) — 服务起来了但 endpoint 不通 · 看 log 排错")
    else:
        lines.append("  healthcheck: 跳过 (没给 healthcheck_url)")
    lines.append("")
    lines.append(f"💡 后续操作:")
    lines.append(f"  - service_status name={name}  · 看是否还活")
    lines.append(f"  - service_stop name={name}    · 停服务")
    lines.append(f"  - read_file path={result.get('log_path')}  · 看输出 / 排错")
    return ToolResult(ok=True, output="\n".join(lines))


SPEC = ToolSpec(
    name="service_start",
    description=(
        "启动一个**长跑后台服务** (例如 API server / model worker / scheduler) · 真 detach "
        "子进程 · daemon 死了它仍在跑 · 状态持久化在 data/runtime/services.json。\n\n"
        "**何时用这个 vs shell_exec**:\n"
        "  - service_start: 长跑服务 (永不退出 · 监听端口 · 跑后台 worker)\n"
        "  - shell_exec: 短任务 (git status · cat · ls · 跑测试 · 短脚本)\n"
        "  - 错用例: 用 shell_exec 起 GPT-SoVITS api.py → timeout 30s 后子进程成孤儿 (真实事故)\n\n"
        "**典型调用**:\n"
        "  ```\n"
        "  service_start(\n"
        "    name='gpt-sovits',\n"
        "    command='conda activate sovits && python api.py',\n"
        "    working_dir='C:/GPT-SoVITS',\n"
        "    port=9880,\n"
        "    healthcheck_url='http://127.0.0.1:9880/health',\n"
        "    healthcheck_after_sec=8.0\n"
        "  )\n"
        "  ```\n\n"
        "**红线**:\n"
        "  - service name 必须匹配 ^[a-zA-Z0-9_-]{1,64}$ · 不允许中文 / 路径字符\n"
        "  - 一个 name 一个 service · 起新的前先 stop 旧的\n"
        "  - working_dir 必须是绝对路径或相对 daemon root 的存在目录\n"
        "  - shell=True 启用 · 可以用 conda activate / && / 管道\n\n"
        "**配套工具**:\n"
        "  - service_status(name) · 查活 + 元信息 (cpu / mem / running_time)\n"
        "  - service_stop(name) · 优雅停 (SIGTERM 5s timeout · 然后 SIGKILL 兜底)\n"
        "  - service_list() · 列所有已知 service · 含 alive/stopped 状态\n\n"
        "**tier**: TIER_CONFIRM (起后台服务有副作用 · 用户 看摘要 ✓ 才跑)"
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "service 唯一名 · ^[a-zA-Z0-9_-]{1,64}$ (例: gpt-sovits / sd-webui / my-api)",
            },
            "command": {
                "type": "string",
                "description": "shell 命令 · 支持 conda activate / && / 管道 (例: 'conda activate xxx && python api.py')",
            },
            "working_dir": {
                "type": "string",
                "description": "工作目录绝对路径 (例: 'C:/GPT-SoVITS' 或 '/opt/myservice')",
            },
            "port": {
                "type": "integer",
                "description": "服务监听的端口 (可选 · 仅作记录 · 1-65535)",
            },
            "env": {
                "type": "object",
                "description": "额外环境变量 dict · merge 进 os.environ (不替换)",
            },
            "healthcheck_url": {
                "type": "string",
                "description": "健康检查 URL · 起完后 curl 验通 (可选 · 例: 'http://127.0.0.1:9880/health')",
            },
            "healthcheck_after_sec": {
                "type": "number",
                "description": "起后等多少秒再 healthcheck (默认 5.0 · 慢服务可调高)",
            },
        },
        "required": ["name", "command", "working_dir"],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
