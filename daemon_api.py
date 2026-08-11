"""
# wish-83fe7c7b 重启续场测试
daemon_api.py
=============

OPUS Daemon · HTTP API · 远程入口
---------------------------------
让 daemon 不再只能从本机终端被找到——任何外部入口（Telegram bridge /
Web UI / curl / iOS Shortcuts / 未来的微信桥）都通过这一层和 OPUS 对话。

设计要点（卷十四 BRO 离职月省钱期立项）：

1. **session 隔离**：API 端的对话默认用独立 session（前缀 `api-`），不和
   daemon 终端主循环共享 messages。两个并发会话各跑各的——避免锁竞争 +
   防止远程消息污染 BRO 当面跟 OPUS 的对话。

2. **三档信任 → 远程版**：BRO 在外面按不了 y/n。API 端用单一 `auto_confirm`
   策略：
     - `"auto"`   · 只跑 AUTO 工具，CONFIRM/GUARD 都 skip
     - `"confirm"`(默认) · AUTO+CONFIRM 自动 go，GUARD skip
     - `"guard"`  · 三档全自动 go（**强不推荐**，等价完全 yolo）
   每次 /chat 请求可以单独覆盖；不传就走 `OPUS_API_DEFAULT_CONFIRM` env，
   再不行就 "confirm"。

3. **共享 RUNTIME**：client / provider / model / system_prompt 都从
   daemon_runtime.RUNTIME 拿——所以 daemon 主循环里 `/model deepseek` 切了模型，
   下一次 API /chat 调用也跟着切。这是"同一个意识"。

4. **鉴权**：Bearer Token。`OPUS_API_TOKEN` 不设 → API 直接拒绝服务（503）。
   这是默认安全姿态——`.env` 没配 token，API 不可用。

5. **后台线程跑 uvicorn**：opus_daemon.py 主入口检测到 `OPUS_API_PORT` 就
   起一根 daemon thread 跑 uvicorn，主循环照旧。线程跑死了也不影响主进程
   （daemon=True）。

6. **零客户端 SDK**：所有 endpoint 都是简单 JSON，curl 一行能调，任何
   bridge 30 行能写。

Endpoints:
  GET  /                       · health probe，不验证 token，只回 alive
  GET  /ui                     · 静态 HTML 聊天页（手机浏览器友好），不鉴权（token 走 JS）
  GET  /status                 · 详细状态(model/provider/active_sessions)，需 token
  POST /chat                   · {message, session_id?, auto_confirm?} → {reply, session_id, usage}
  POST /chat/stream            · SSE 流式版（卷十七加）—— 推 tool_call/tool_result/usage/done
  GET  /sessions?api_only=     · 列 session（api_only=true 只返 api- 前缀）
  GET  /sessions/{id}          · 取一个 session 的 raw jsonl 内容
  GET  /sessions/{id}/messages · 结构化 turn 列表（WebUI 拉历史用）

未来扩展（不在 v0.1 范围）：
  - /tools         · 列当前工具 + tier
  - /tools/run     · 远程直接调单个工具（绕过 LLM）
  - WebSocket       · 双向实时
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from agent_tools import TIER_AUTO, TIER_CONFIRM, TIER_GUARD, ToolSpec
from daemon_runtime import RUNTIME
from daemon_session import (
    append_turn,
    get_last_user_turn_ts,
    list_sessions,
    load_session,
    load_session_for_ui,
    new_session_id,
    session_path,
)
from tool_loop import UsageStats, run_tool_loop

# 供本文件遗留辅助函数 (_activate_provider_config / _test_provider_inner) 的
# raise HTTPException 使用 · 路由拆分重构时全局 import 被清掉 → F821 潜伏 bug
# (正常路径不触发 raise 所以没炸过 · 错误路径会 NameError 掩盖真实错误)。
from fastapi import HTTPException


def _env_float(name: str) -> Optional[float]:
    """读环境变量转 float · 不存在/非法返回 None (wish-8914f90c 墙钟熔断用)。"""
    v = os.environ.get(name)
    if not v:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


ROOT = Path(__file__).resolve().parent

# in-memory cache of API-side session messages
# key = session_id, value = messages list
# 进程级；daemon 重启就丢——但 session 的 jsonl 文件还在磁盘上，重启后用
# session_id 重新调 /chat 会自动从磁盘 load 回放
_API_SESSIONS: dict[str, list[dict]] = {}

# === 锁机制 (wish-68b0e173 phase 2a · 2026-05-25) ===
#
# v0.1 历史: 单一 _API_LOCK 全 daemon 一把锁 · 一个 chat 卡住其他全部等
# v0.2 (本次): 拆两层 ·
#   _API_LOCK         = 全局 · 只用于 RUNTIME 写入 (setup_client / setup_provider)
#   _get_session_lock = per-session · chat_impl 用 · 不同 sid 真并行
#
# 为什么这么拆:
#   - RUNTIME.client / RUNTIME.provider 是单一全局对象 · 替换时必须排队 (但极少触发)
#   - chat_impl 里写的是 _API_SESSIONS[sid] 跟磁盘 jsonl · 不同 sid 不踩车
#   - 所以 chat_impl 抢 session lock 不抢全局锁 · BRO 终端 A + 终端 B 真并行
_API_LOCK = threading.RLock()

# session_id → RLock · 让不同 session 的 chat 真并行
# 加 _SESSION_LOCKS_GUARD 保护字典自身的并发访问
# LRU 上限防止长跑 daemon 累积大量 stale session lock 把内存撑爆
_SESSION_LOCKS: dict[str, threading.RLock] = {}
_SESSION_LOCKS_GUARD = threading.Lock()
_SESSION_LOCKS_LRU: list[str] = []  # 最旧 sid 在前·最新在后
_SESSION_LOCKS_MAX = 100  # LRU 上限·超过就 evict 最旧的


def _get_session_lock(sid: str) -> threading.RLock:
    """取或建一个 session 级锁 · 带 LRU 防爆内存。

    用法:
        with _get_session_lock(sid):
            # 只有同一 sid 的另一个调用会等·其他 sid 立刻进

    跟 _API_LOCK 的边界:
        - _API_LOCK = 进程级·只用于 RUNTIME.client / RUNTIME.provider 替换
        - 此函数 = session 级·chat_impl 写 _API_SESSIONS[sid] 跟磁盘 jsonl 用
    """
    with _SESSION_LOCKS_GUARD:
        lock = _SESSION_LOCKS.get(sid)
        if lock is None:
            lock = threading.RLock()
            _SESSION_LOCKS[sid] = lock
        # LRU bookkeep
        if sid in _SESSION_LOCKS_LRU:
            _SESSION_LOCKS_LRU.remove(sid)
        _SESSION_LOCKS_LRU.append(sid)
        # evict 最旧 · 注意只 evict 字典 entry · 不 forcibly 释放 (持有者还在用)
        # 等持有者天然释放 · 字典里没引用了就完全 GC
        while len(_SESSION_LOCKS_LRU) > _SESSION_LOCKS_MAX:
            old_sid = _SESSION_LOCKS_LRU.pop(0)
            _SESSION_LOCKS.pop(old_sid, None)
        return lock


# 卷三十六 · 中断机制
# turn_id (uuid) → threading.Event
# /turns/{tid}/abort 把对应 Event.set() · 走到 tool_loop 的 confirm 回调时拦截掉
_ACTIVE_TURNS: dict[str, threading.Event] = {}
_TURNS_LOCK = threading.Lock()

# wish-3fef4bc7 follow-up · 浏览器 F5 后查"这个 session 有 active turn 吗"
# 用来让 frontend 启动 polling auto-refresh · 不让 BRO 手动 F5 第二次
# turn_id → sid · 跟 _ACTIVE_TURNS 同步生命周期 (worker 启动注册 · 退出删)
_TURN_TO_SID: dict[str, str] = {}

# 卷七十五续四 · ② 自主巡航进度 · turn_id → 最新一步进度快照
# 病根: 后台/轮询模式的 turn 没有 SSE 接收方 · tool_loop 的 tool_progress 事件全丢 →
#   前端只能显示"仍在后台跑·自动刷新中" · 长任务跑工具时看着像卡死。
# 修法: 无论 SSE 连没连 · _chat_impl 都把最新一步 (工具名/步骤/轮次) 记进这里 ·
#   /sessions/{sid}/active_turn 端点带出去 · 前端轮询显示"正在: xxx · 第N轮 · 已Xs"。
# 生命周期跟 _TURN_TO_SID 对齐 (chat.py / resume_runner 的 finally 里一起 pop) · 共用 _TURNS_LOCK。
_TURN_PROGRESS: dict[str, dict] = {}


def get_turn_progress(turn_id: str) -> Optional[dict]:
    """② · 查 turn 最新进度快照 (含服务端算好的 elapsed_s / stale_s) · 供 active_turn 端点。"""
    if not turn_id:
        return None
    with _TURNS_LOCK:
        slot = _TURN_PROGRESS.get(turn_id)
        if not slot:
            return None
        now = time.time()
        return {
            "label": slot.get("label") or "",
            "tool": slot.get("tool") or "",
            "iteration": slot.get("iteration") or 0,
            "elapsed_s": int(now - slot.get("started_at", now)),
            "stale_s": int(now - slot.get("updated_at", now)),
        }


def _make_progress_recorder(turn_id: str, inner: Optional[Callable[[str, dict], None]]):
    """② · 包一层 progress 回调 · 无论有没有 SSE 接收方 (inner) 都把最新一步记进 _TURN_PROGRESS。

    inner 存在 → 照常转发 (SSE 主对话行为一字不变);inner=None (后台/resume turn) → 只记录 ·
    让轮询也能看到进度。 turn_id 为空 → 没法记 · 原样返回 inner (不改行为)。
    """
    if not turn_id:
        return inner
    _now = time.time()
    with _TURNS_LOCK:
        _TURN_PROGRESS[turn_id] = {
            "started_at": _now, "updated_at": _now, "iteration": 0, "label": "启动中…", "tool": "",
        }

    def _rec(event_type: str, data: dict) -> None:
        try:
            now = time.time()
            d = data if isinstance(data, dict) else {}
            with _TURNS_LOCK:
                slot = _TURN_PROGRESS.get(turn_id)
                if slot is not None:
                    slot["updated_at"] = now
                    if d.get("iteration"):
                        slot["iteration"] = d["iteration"]
                    if event_type == "tool_call":
                        slot["tool"] = d.get("name") or ""
                        _s = d.get("summary")
                        slot["label"] = f"调用 {slot['tool']}" + (f" · {_s}" if _s else "")
                    elif event_type == "tool_progress":
                        _step = (d.get("step") or "").strip()
                        _msg = (d.get("msg") or "").strip()
                        _lbl = (_step + (" " + _msg if _msg else "")).strip()
                        if _lbl:
                            slot["label"] = _lbl
                    elif event_type == "tool_result":
                        _nm = d.get("name") or slot.get("tool") or ""
                        slot["label"] = f"{_nm} 完成 · 继续推理…"
                    elif event_type in ("assistant_finish", "auto_resume"):
                        slot["label"] = "思考中…"
                    elif event_type == "reasoning_delta":
                        slot["label"] = "推理中…"
        except Exception:
            pass
        if inner is not None:
            inner(event_type, data)

    return _rec


# ---------- confirm policy ----------

_TIER_RANK = {TIER_AUTO: 1, TIER_CONFIRM: 2, TIER_GUARD: 3}

# 卷五十六 · 后台续场 turn 防自爆链 (2026-06-06 · BRO 复盘「连着重启两回」)
# 这些工具会重启/关停 daemon 自身。 在「无人值守 turn」(push_event is None · 没有
# 前台 SSE 接收方 · 典型就是 resume_runner 的 follow_up 续场 turn) 里绝不允许它们跑——
# 否则「前台重启 → 续场自动验证 → 续场又调 request_restart → 再重启」无限套娃·
# 还会把 BRO 正在看的对话状态打断。 request_restart 是 CONFIRM 档·policy=confirm 下本
# 会自动 go·所以必须在 rank<=threshold 之前一刀拦死·且不受 OPUS_RESUME_AUTO_CONFIRM 影响。
_BACKGROUND_BLOCKED_TOOLS = {"request_restart"}


# === wish-2a4d8c1e · inline confirm UI (卷四十六 续 3) ===
#
# LLM 撞 CONFIRM/GUARD 工具 (超 policy 阈值) 时 · 不立刻 raise 'declined' · 改为:
#   1. 检查 trusted_commands (复用 wish-f563a56d) · 命中 downgrade · 直接 go
#   2. 没命中 → push SSE event `confirm_request` 给前端 (chat 弹卡片)
#   3. worker thread 阻塞 wait Event · 直到 BRO 点按钮 (POST /turns/confirm)
#   4. set Event · worker 解除阻塞 · 按决议返回 go/skip
#
# 阻塞机制: per-session lock 仍持 · 但只锁当前 session · 其他 session 不影响
# 超时: 30min 默认 · 超时 auto-deny + log
#
# 数据结构:
#   _PENDING_CONFIRMS[tool_call_id] = {
#     "event": threading.Event,  # set 时 worker 解阻塞
#     "session_id": str,
#     "turn_id": str,
#     "tool_name": str,
#     "args_clean": dict,        # 已 pop risk/mitigation 的净版 · worker 用它调真 tool
#     "command": str,            # shell_exec 特殊 · 用于 trust pattern 抽取
#     "decision": str | None,    # 由 endpoint 写入: approve_once/trust_30min/trust_24h/trust_permanent/deny
#     "reason": str,             # BRO 拒绝时填的备注
#     "created_at": float,
#   }
_PENDING_CONFIRMS: dict[str, dict] = {}
_PENDING_CONFIRMS_LOCK = threading.Lock()

# inline confirm 超时 30min · 超时 auto-deny 防 worker thread 永远阻塞
_CONFIRM_TIMEOUT_SEC = 30 * 60


def _pop_risk_fields(args: dict) -> tuple[str, str]:
    """从 args 里 pop 出 risk_explanation 和 mitigation (LLM 加的扩展字段)
    返回 (risk, mitigation) · args 被 mutate · 真 tool 不会看到这两个字段
    """
    risk = ""
    mit = ""
    try:
        if isinstance(args, dict):
            v = args.pop("risk_explanation", None)
            risk = str(v).strip() if v else ""
            v = args.pop("mitigation", None)
            mit = str(v).strip() if v else ""
    except Exception:
        pass
    return risk, mit


def _extract_trust_pattern(tool_name: str, args: dict) -> str:
    """从 tool_name + args 推导出 trusted_commands.json 用的 pattern

    目前只对 shell_exec 有意义 (其他工具不查 trusted_commands)。

    shell_exec 算法:
      1. shlex 分 token
      2. 跳过含 shell 控制字符 (| & ; > < ` $) 的 token —— 这些字符是 wish-f563a56d
         add_trusted 安全检查会拒掉的 (防 BRO 加 'pip install | rm -rf /' 这种 pattern)
      3. 取连续非控制字符前缀的前 2 个 token
      4. 没有可用 token → 退回 tool_name

    例:
      'tasklist | findstr python' → ['tasklist', '|', 'findstr', 'python']
        → 'tasklist' (跑到 `|` 就 break · 取前 1 个)
      'pip install duckduckgo' → ['pip', 'install', 'duckduckgo']
        → 'pip install' (前 2 个无控制字符)
      'curl -fsSL https://x.y' → ['curl', '-fsSL', 'https://x.y']
        → 'curl -fsSL'

    其他工具: 直接用 tool_name (写了也不会真生效 · 因为只 shell_exec.classify 查 is_trusted)
    """
    if tool_name == "shell_exec":
        import shlex as _shlex
        cmd = (args or {}).get("command") or ""
        s = cmd.strip().lstrip("([{ \t")
        if not s:
            return tool_name
        try:
            tokens = _shlex.split(s, posix=False)
        except ValueError:
            tokens = s.split()
        if not tokens:
            return tool_name
        # 跳过 shell 控制字符 token (跟 add_trusted 的安全检查一致)
        # 取连续非控制字符前缀
        _CTRL_CHARS = ("|", "&", ";", "`", "$", ">", "<")
        safe: list[str] = []
        for t in tokens[:6]:  # 看前 6 个就够 · 防过长 pattern
            if not t:
                continue
            if any(ch in t for ch in _CTRL_CHARS):
                break
            safe.append(t)
        if not safe:
            return tool_name
        return " ".join(safe[:2])  # 前 2 个安全 token
    return tool_name


def _trust_decision_to_minutes(decision: str) -> Optional[int]:
    """trust_XX → 分钟数 · 0 表示永久 · None 表示不写 trusted (approve_once / deny)"""
    return {
        "trust_30min": 30,
        "trust_24h": 24 * 60,
        "trust_permanent": 0,  # 0 → add_trusted 当永久
    }.get(decision)


def _supports_trust(tool_name: str) -> bool:
    """该 tool 是否支持 trust_XX 决议 (写 trusted_commands.json)
    只 shell_exec 真用 trusted_commands · 其他工具加了也不生效 · 前端按这个隐藏 trust 按钮
    """
    return tool_name == "shell_exec"


def cleanup_pending_confirm(tool_call_id: str) -> None:
    """worker 跑完后清掉该 tool_call_id 的 pending · 防内存泄漏"""
    with _PENDING_CONFIRMS_LOCK:
        _PENDING_CONFIRMS.pop(tool_call_id, None)


# WebUI / API 接入时追加到 system prompt 的"接入方式告知"
# 关键作用：让 OPUS 知道自己走的是非终端通道（无阻塞 y/n），但**不要误判 BRO 一定在远程**——
#   卷五十四：旧文案断言"BRO 通过手机、不在机器旁、看不到屏幕"，导致 OPUS 在本机 WebUI 里
#   也对 BRO 说"我是远程"。本机浏览器和手机远程走同一条通道、daemon 区分不了，所以改成
#   "可能远程"的保守措辞，并明确禁止 OPUS 对 BRO 断言"我是远程"。
_REMOTE_SYSTEM_HINT = """\

---

## 当前会话的接入方式：WebUI / API（非本机终端 REPL）

**重要**：你不是通过本机终端 REPL 跟 BRO 说话，而是通过 WebUI / API 通道。
**本机浏览器的 WebUI 和手机/外网远程走的是同一条通道·你无法区分**——
按"可能远程"的保守前提调整本机感知行为，但**别对 BRO 断言"你是远程"**
（他很可能就坐在这台机器前用浏览器）：

1. **不一定能看到屏幕** —— 他可能在本机浏览器（看得到），也可能在手机（看不到）。
   `take_screenshot` / `open_app` 这种"打开给你看"在远程会落空。要让 BRO 看东西，
   优先用能把内容直接带回对话的工具（`browser_fetch` / `web_fetch`），少用"我打开了 X 你看一下"。
2. **按不了终端 y/n** —— 本机终端那个阻塞式确认红框在这条通道里不存在。
   CONFIRM/AUTO 档工具按 `OPUS_API_DEFAULT_CONFIRM` 策略自动跑（默认 confirm 档：AUTO + CONFIRM
   都自动执行、不弹卡片）；只有 GUARD 档（高危）才会在 WebUI 弹 inline 确认卡片等 BRO 点。
   → 准确说法是"当前走 API 通道·CONFIRM 档按策略自动执行"，**别说"我是远程所以不弹确认"**误导 BRO。
3. **拿内容用 fetch 类工具** —— 想看网页用 `browser_fetch`（attach 他已登录的 Edge，能看
   登录态页面）或 `web_fetch`（无登录 / 走 httpx）。**不要**截屏让他描述。
4. **回话尽量精简** —— 屏幕可能小、流量可能贵；省略寒暄，直接给结论。需要多步骤的事，
   一段话讲清三件：你做了什么 / 看到了什么 / 下一步建议。
5. **长任务慎用** —— SSE 流式输出虽然解决了 cloudflared 100s 超时，但 BRO 在外面等
   3 分钟仍然是糟糕体验。`summon_cursor`、跨大目录 grep、连续抓十几个网页这种事
   宁愿告诉 BRO "需要回本机操作 / 让我用更直接的方法"。

## 反爬 / 限流 / 验证码的标准处理（卷十八硬规则）

OPUS 历史上反复栽过的坑：手机端被 BRO 让"拉知乎热榜 + 评论"，结果跑了 12 轮工具
反复换关键词换源死磕反爬，浪费 200 秒 + 大量 token + 最后输出"超出 max iterations"
什么都没给 BRO。**杜绝这种事**：

- 看到 `401 Unauthorized` / `403 Forbidden` / `HTTP 202`（DuckDuckGo 反爬）/
  网页里"验证 / 请登录 / 异常访问 / 安全验证 / 请求异常"等关键词 → **立即停止重试
  这个数据源**，不要换关键词 / 不要换聚合站继续撞。直接告诉 BRO 哪个源拿不到。
- **同一类目标连续 2 个源失败 → 立即停止，告诉 BRO 当前能拿到的部分 + 拿不到的原因**。
  不要试到 5 个源都失败。
- **已经拿到"够回答原问题"的数据，立刻停手输出**——不要因为"可以更全/更深"再去抓
  评论 / 详情。BRO 在外面要的是 30 秒能扫完的速答，不是博士论文。

## 工具调用 args 的纪律

每个工具的 input_schema 在 description 里都说得很清楚。**严格按字段名 + 字段类型**
传 args。如果你看到工具返回 "args 不符合 schema..." 错误：

- **不要重复同样的错误**——错误信息里告诉了你正确的字段名和类型，下一轮按那个改。
- **不要凭直觉造字段名**——比如 web_fetch 只有 `url` 和 `max_chars` 两个字段，
  不要塞 `"string"`、`"endpoint"`、`"target"` 这种字段。

## 卷四十六 wish-2a4d8c1e · Inline Confirm UI · CONFIRM/GUARD 工具撞 BRO

daemon 在 chat 里给你装了一个 inline confirm 卡片系统。当你调 CONFIRM 或 GUARD 级工具
（超出当前 policy 阈值）时：

1. **daemon 会在 chat 弹卡片给 BRO** —— 不再像以前那样直接返回 "declined" 给你。
2. **你必须在 args 里加两个扩展字段** —— schema 没列但 daemon 会读：
   - `risk_explanation`: **这条调用可能带来什么风险**（1-2 句话，具体到文件 / 进程 / 网络 /
     数据丢失）
   - `mitigation`: **你打算怎么规避这个风险**（1-2 句话，例如 "先 dry-run 看路径 / timeout
     10s / 失败不重试 / 留 git stash 兜底 / 只读不写"）
3. **写不下就别瞎写** —— 风险 / 规避必须**真**，不是套话。写 "可能有风险" / "我会小心"
   这种废话 BRO 会不放心、不点 approve。不知道副作用就老实说不知道 —— **直接调一个
   只读探测工具先看清楚，再来调有副作用的工具**。
4. BRO 看完会点 4 个按钮之一：[只这次] / [信任 30min] / [信任 24h] / [永久信任] 或 [拒绝]。
   你的 tool call 会**阻塞**到 BRO 点了为止（30min 超时则 auto-deny）。

**好坏对照示例** —— BRO 说 "清下 build 缓存吧"：

✓ 好的填法：
```
{
  "command": "rm -rf dist/",
  "risk_explanation": "递归删整个 dist/ 目录·里面是 npm build 的输出·删了下次 BRO 跑 npm build 要重做约 2 分钟",
  "mitigation": "我先 ls dist/ 确认确实是 build 输出 (.js / .map / index.html)·dist/ 不在 git 里·没回滚需求·删错也只是要重 build"
}
```

✗ 坏的填法（BRO 会不放心 → 拒绝）：
```
{
  "command": "rm -rf dist/",
  "risk_explanation": "可能有风险",
  "mitigation": "我会小心"
}
```

**重要补充**：
- `risk_explanation` / `mitigation` 这两个字段在 `input_schema` 里**没列出来**——这是
  daemon 通过 additionalProperties 接受的扩展字段。每次调 CONFIRM/GUARD 工具都加上即可，
  不会被 schema validator 拒掉。
- daemon 会 **pop 掉这两个字段** 再调真 tool —— 真 tool 不会看见它们。
- AUTO 工具不需要这两个字段（也不会弹卡片）。如果你不确定 tier，**保守起见加上**就行，
  daemon 不需要时会忽略。
- shell_exec 是唯一支持 **trust 持续信任** 的工具（trusted_commands.json 系统）。其他
  CONFIRM 工具的卡片上 BRO 只能选 [只这次] / [拒绝]——你写 mitigation 时不要承诺 "下次也
  不需要确认" 这种话，BRO 没这个按钮可点。
"""


# P1 代码归一 · 把 system 里的 OPUS/BRO 令牌本地化成本实例的名字 (母体走缺省值 = no-op)
try:
    from identity import localize as _localize
except Exception:
    def _localize(t):
        return t


def _build_remote_system(base: str, session_id: str = "") -> str:
    """稳定前缀 · 静态 soul + 远程接入 hint。

    3b · 缓存前缀稳定化: 一个 session 内字节不变 → DeepSeek 自动缓存命中它 /
    Claude 缓存断点打在它上面。 动态 telemetry (会变) 已挪到 _build_remote_tail·
    进 system_suffix·不再污染缓存前缀 (之前 telemetry 拼这里·每轮变·冲掉灵魂缓存)。
    session_id 参数保留只为兼容签名·已不再使用。
    """
    return base + _REMOTE_SYSTEM_HINT


def _build_remote_tail(session_id: str = "") -> str:
    """易变尾巴 · 动态 telemetry (当前时间 / git 脏区 / daemon uptime · wish-1d286099)。

    每轮都变 → 必须留在缓存前缀之外 (放 system_suffix)·否则每轮冲掉灵魂缓存。
    """
    if not session_id:
        return ""
    try:
        from workers.dynamic_telemetry import build_dynamic_telemetry
        return build_dynamic_telemetry(session_id)
    except Exception:
        return ""  # telemetry 炸了不影响正常对话


def _make_remote_confirm(
    policy: str,
    cancel_event: Optional[threading.Event] = None,
    session_id: str = "",
    turn_id: str = "",
    push_event: Optional[Callable[[str, dict], None]] = None,
):
    """生成一个 confirm callback。

    policy 决定允许到第几档自动 go：
      "auto"    → 只允许 AUTO
      "confirm" → AUTO + CONFIRM 自动 go
      "guard"   → 三档全开（远程 yolo，慎用）

    卷四十六 · wish-2a4d8c1e · inline confirm UI:
      当 tier 超 policy 阈值时 · 不立刻 skip · 走:
        1. 复用 wish-f563a56d trusted_commands · 命中直接 go
        2. push SSE confirm_request 给前端 · 等 BRO 点按钮
        3. 30min 超时 auto-deny
      session_id / turn_id / push_event 都是新参数 · 用于注册 _PENDING_CONFIRMS
      和 push SSE 事件; 老的 confirm_only_legacy 模式 (没传 push_event) 退化到旧逻辑

    新签名第四参数 tool_call_id (在 _call_confirm 里传) · 用作 _PENDING_CONFIRMS key

    卷三十六 · cancel_event 传进来 · BRO 点停止时 set · 这里返回 "abort"
    让 tool_loop 提前结束。
    """
    policy = policy if policy in ("auto", "confirm", "guard") else "confirm"
    threshold = {"auto": 1, "confirm": 2, "guard": 3}[policy]

    def _confirm(spec: ToolSpec, args: dict, _assistant_text: str = "", tool_call_id: str = "") -> str:
        if cancel_event is not None and cancel_event.is_set():
            return "abort"
        try:
            tier = spec.effective_tier(args)
        except Exception:
            tier = spec.tier
        rank = _TIER_RANK.get(tier, 99)

        # 卷五十六 · 后台续场 turn 防自爆链 (2026-06-06)
        # push_event is None = 没有前台 SSE 接收方 = 无人值守的 background turn
        #   (resume_runner follow_up 续场 turn 走的就是 progress=None)。 这种 turn 里
        #   绝不允许跑「重启/关停自己」的工具·抢在 rank<=threshold 之前拦死·
        #   不受 OPUS_RESUME_AUTO_CONFIRM=guard 影响。 详见 _BACKGROUND_BLOCKED_TOOLS 注释。
        if push_event is None and spec.name in _BACKGROUND_BLOCKED_TOOLS:
            return (
                "reject:你正跑在一个【后台续场 turn】里 (没有前台 SSE · BRO 不在场看)。"
                "这个 turn 本身就是上一次重启之后新 daemon 自动拉起的——新代码早已装载、"
                "你此刻就活在重启好的新 daemon 上·根本不需要再调 " + spec.name + "。"
                "在后台二次重启会造成「重启→续场→又重启」套娃·还会打断 BRO 正在看的对话。"
                "→ 直接做完你的验证任务即可; 如果你真判断还需要再重启·把原因讲给 BRO·"
                "由 BRO 在 WebUI 手动点重启按钮 (那条路径有前台在场)。"
            )

        # wish-2a4d8c1e · 先 pop risk/mitigation · 不管走哪条路 args 都不再带这两字段
        risk, mitigation = _pop_risk_fields(args)

        # 卷四十六 III 补丁 5 · GUARD tier 强制要求 risk_explanation + mitigation 都填
        # BRO 截图反馈: 经常看到"OPUS 未说明" · 闭眼批准心慌
        # 实现: 缺字段时直接 reject · 给 LLM 看到错误后重试加上字段
        # 注: 仅 GUARD tier 强制 · CONFIRM 不强制 (CONFIRM 太频 · 强制会拖慢日常对话)
        if rank == 3:  # GUARD tier
            missing = []
            if not risk:
                missing.append("risk_explanation")
            if not mitigation:
                missing.append("mitigation")
            if missing:
                return (
                    "reject:GUARD tier 工具 (高风险 · " + spec.name + ") 必须在 args 里加 "
                    + " + ".join(missing) + " 字段才能让 BRO 看到批准卡片. 你这次没填, "
                    "daemon 直接拦下来了——请重新调用同一个工具, 在 args 里加上:\n"
                    '  "risk_explanation": "这次操作的具体风险 (1-2 句, 比如 \'递归删 X 目录, 里面有 Y, 删了下次要 Z 分钟重做\')",\n'
                    '  "mitigation": "你打算怎么规避 (1-2 句, 比如 \'先 dry-run 看路径 / 失败不重试 / 留 git stash 兜底\')"\n'
                    "禁止套话 (\'可能有风险\' / \'我会小心\'), 必须真. 加上后立即重试, BRO 才会看到批准请求."
                )

        # 老规则: tier ≤ threshold → 直接 go (AUTO 永远过; confirm policy 下 CONFIRM 也过)
        if rank <= threshold:
            return "go"

        # 卷七十二 v4 · 0.2.0 · 信任 flow 内自动放行 CONFIRM (BRO 痛点: 跑过 OK 的 flow 不要次次问)
        # 设计:
        #   run_flow 启动时如果 flow.trust_level >= 2 · 会设 _TRUSTED_FLOW_CTX 为 flow_id
        #   confirm callback 看到这个 ContextVar 不空 · 对 CONFIRM tier 直接放行
        #   GUARD tier (rank==3) 不放行 · 保命线
        if rank == 2:  # CONFIRM tier
            try:
                from agent_tools import current_trusted_flow
                trusted_fid = current_trusted_flow()
                if trusted_fid:
                    # 真放行 · 不影响日志/SSE (push_event 还是会推 · BRO 仍能在 banner 看到)
                    return "go"
            except Exception:
                pass

        # 新增 fallback: shell_exec 命中 trusted → downgrade · 直接 go
        # 注: shell_exec.classify 已经在 effective_tier 里查过 trusted · 如果命中
        # tier 会是 TIER_AUTO · 上面 rank<=threshold 就过了。 这里再查一次是为了
        # 兜底其他 future 可能加 trusted 的工具
        if spec.name == "shell_exec":
            try:
                from workers.trusted_commands import is_trusted as _is_trusted
                if _is_trusted(args.get("command") or ""):
                    return "go"
            except Exception:
                pass

        # 走 inline confirm: 没 push_event (老 caller) 或没 tool_call_id (旧 tool_loop) → 退化 skip
        if push_event is None or not tool_call_id:
            return "skip"

        # wish-2a4d8c1e 核心 · 注册 pending + SSE push + 阻塞 wait
        ev = threading.Event()
        pending_data = {
            "event": ev,
            "session_id": session_id,
            "turn_id": turn_id,
            "tool_name": spec.name,
            "args_clean": dict(args),  # 净版 (已 pop risk/mitigation)
            "command": (args.get("command") or "") if spec.name == "shell_exec" else "",
            "decision": None,
            "reason": "",
            "created_at": time.time(),
        }
        with _PENDING_CONFIRMS_LOCK:
            _PENDING_CONFIRMS[tool_call_id] = pending_data

        # 摘要 (复用 spec.summarize · 但传净版 args)
        try:
            summary = spec.summarize(args) if hasattr(spec, "summarize") else spec.name
        except Exception:
            summary = spec.name

        tier_reason_map = {
            TIER_CONFIRM: "CONFIRM tier · 改动类操作 · 当前策略要 BRO 点确认",
            TIER_GUARD: "GUARD tier · 高风险 · 必须 BRO 显式批准",
        }
        tier_reason = tier_reason_map.get(tier, f"{tier} tier · policy={policy} 拒")

        try:
            push_event("confirm_request", {
                "turn_id": turn_id,
                "session_id": session_id,
                "tool_call_id": tool_call_id,
                "tool_name": spec.name,
                "args_summary": summary,
                "args_preview": _short_json_preview(args, max_chars=400),
                "tier": tier,
                "tier_reason": tier_reason,
                "risk_explanation": risk,  # 可能为空 · 前端会显示 "OPUS 没说明" 提示
                "mitigation": mitigation,
                "supports_trust": _supports_trust(spec.name),
                "suggested_trust_windows": ["approve_once", "trust_30min", "trust_24h", "trust_permanent"],
                "timeout_sec": _CONFIRM_TIMEOUT_SEC,
            })
            # 2026-07-28 BRO 需求 · 桌宠同步弹「等你拍板」· 不盯 WebUI 也知道 OPUS 在等
            try:
                from desktop_pet.activities import write_notify as _pet_notify
                _pet_notify("confirm", f"等你拍板 · {spec.name}")
            except Exception:
                pass
            # 事项 B · Windows toast · 不看屏幕也能收到 (独立 try · 不跟 pet_notify 串扰)
            try:
                from workers.windows_toast import send_toast as _send_toast
                _send_toast("OPUS 等你拍板", spec.name)
            except Exception:
                pass
        except Exception:
            pass  # push 失败不阻止流程 · 直接走超时 auto-deny

        # 阻塞等 BRO 决议 (或 cancel · 或超时)
        # 每 1s 检查一次 cancel · 让 BRO 点停止能立刻退出
        deadline = time.time() + _CONFIRM_TIMEOUT_SEC
        while True:
            if cancel_event is not None and cancel_event.is_set():
                cleanup_pending_confirm(tool_call_id)
                return "abort"
            remaining = deadline - time.time()
            if remaining <= 0:
                # 超时 auto-deny
                with _PENDING_CONFIRMS_LOCK:
                    pending_data["decision"] = "deny"
                    pending_data["reason"] = "(auto-denied · BRO 未在 30min 内响应)"
                try:
                    push_event("confirm_resolved", {
                        "tool_call_id": tool_call_id,
                        "decision": "deny",
                        "reason": pending_data["reason"],
                        "auto_timeout": True,
                    })
                except Exception:
                    pass
                cleanup_pending_confirm(tool_call_id)
                return "skip"
            wait_slot = min(1.0, remaining)
            if ev.wait(timeout=wait_slot):
                break  # event set · BRO 决议来了

        # 读决议
        # 注: trust_* 决议下的 add_trusted 已经在 POST /turns/{tid}/confirm endpoint 完成
        # (卷四十六续 4 · 防止 worker 端 try/except: pass 静默吞 ValueError)
        # 这里只读 decision 决定 go / skip
        with _PENDING_CONFIRMS_LOCK:
            decision = pending_data.get("decision") or "deny"
            reason = pending_data.get("reason") or ""

        cleanup_pending_confirm(tool_call_id)

        if decision == "deny":
            # 卷五十四 · 闭环修复 (Hermes '固化知识' 那一环): BRO 拒绝时填的理由
            # 必须喂回 LLM · 否则 OPUS 只收到"用户拒绝了"·学不到 BRO 的边界。
            # 走 reject:<msg> 通道 (tool_loop 会把 <msg> 当 tool_result.error 给 LLM)。
            r = (reason or "").strip()
            if r:
                return (
                    f"reject:BRO 拒绝了这次 `{spec.name}` 调用 · 理由: {r}\n"
                    f"→ 认真对待这个理由 (这是 BRO 的边界/偏好信号) · 换思路或先问清楚 · "
                    f"不要原样重试。 如果这是个该长期记住的偏好·考虑调 update_bro_note 记下来。"
                )
            return "skip"
        # approve_once 或 trust_* (即使 trust 写失败 endpoint 已记 applied_trust.ok=False) 都 go
        return "go"

    return _confirm


def _short_json_preview(obj: Any, max_chars: int = 400) -> str:
    """args 的 JSON 字符串预览 · 超长截断 · 给 confirm UI 显示用"""
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        try:
            s = str(obj)
        except Exception:
            s = "(unserializable args)"
    if len(s) > max_chars:
        s = s[:max_chars] + "\n… (truncated)"
    return s


def _no_observe(_spec, _args, _result) -> None:
    return None


# 卷三十八 · max_tokens 解析 · 三级 fallback
def _resolve_max_tokens(payload_value) -> int:
    """优先级: payload override > active config.max_tokens > .env OPUS_MAX_TOKENS > 8192 fallback.

    BRO 反馈"4096 太小 · DeepSeek 支持 384K 输出 · 这个限制让 OPUS 写两步就被截断".
    新策略: 每条 config 自带 max_tokens · 按模型推荐.
    """
    if payload_value:
        try:
            v = int(payload_value)
            if v > 0:
                return v
        except (ValueError, TypeError):
            pass
    try:
        from workers.provider_configs import get_active_config
        cfg = get_active_config(include_key=False)
        if cfg and cfg.get("max_tokens"):
            return int(cfg["max_tokens"])
    except Exception:
        pass
    env_v = os.environ.get("OPUS_MAX_TOKENS")
    if env_v:
        try:
            v = int(env_v)
            if v > 0:
                return v
        except (ValueError, TypeError):
            pass
    return 8192


# ─── 卷三十七 · provider config helper ───
def _activate_provider_config(cfg_id: str) -> None:
    """切换 active config · 重建 RUNTIME.client / model / provider / base_url.

    跟 /providers/switch 旧路径走同一个 setup_client · 但来源是 provider_configs.json.
    """
    from workers.provider_configs import get_config, apply_config_to_env, set_active
    cfg = get_config(cfg_id, include_key=True)
    if cfg is None:
        raise HTTPException(404, f"config not found: {cfg_id}")
    set_active(cfg_id)
    apply_config_to_env(cfg)
    from daemon_provider import setup_client
    pkind = cfg["provider_kind"]
    try:
        client, _default_model, resolved_base = setup_client(pkind)
    except SystemExit as e:
        raise HTTPException(500, f"setup_client failed: {e}") from e
    with _API_LOCK:
        RUNTIME.client = client
        RUNTIME.provider = pkind
        RUNTIME.model = cfg["model"]
        RUNTIME.base_url = resolved_base
        # wish-00ed11c2 · 补回 2026-06-03 丢失的同步行:
        # 激活配置时把该配置的 vision 标注同步进全局 override (L2 兼容层 ·
        # 按模型精确判断在 model_aliases.supports_vision L1 · 这里是双保险)
        RUNTIME.vision_override = cfg.get("vision")


async def _test_provider_inner(
    *, provider_kind: str, base_url: str, model: str, api_key: str
) -> dict:
    """直接 ping 一个 provider · 不动 RUNTIME · 返回 {ok, reply_preview, model} 或 {ok=False, error}."""
    if not model or not api_key:
        raise HTTPException(400, "model and api_key are required")
    base_url_ = base_url or None
    try:
        if provider_kind == "openai":
            from openai import OpenAI
            # 同步 SDK 调用包进线程 · 防网络慢时阻塞事件循环 (社区文档问题1)
            # timeout 15s + max_retries 0 · 失败请求不被重试放大
            def _openai_ping():
                client = OpenAI(api_key=api_key, base_url=base_url_, timeout=15.0, max_retries=0)
                extra_body: dict = {}
                if base_url and "deepseek.com" in base_url.lower():
                    extra_body = {"thinking": {"type": "disabled"}}
                resp = client.chat.completions.create(
                    model=model, max_tokens=200,
                    messages=[{"role": "user", "content": "reply with exactly 'pong'"}],
                    extra_body=extra_body if extra_body else None,
                )
                return (resp.choices[0].message.content or "").strip()
            reply = await asyncio.to_thread(_openai_ping)
        elif provider_kind == "anthropic":
            from anthropic import Anthropic
            def _anthropic_ping():
                kwargs: dict = {"api_key": api_key}
                if base_url_:
                    kwargs["base_url"] = base_url_
                client = Anthropic(**kwargs, timeout=15.0, max_retries=0)
                resp = client.messages.create(
                    model=model, max_tokens=200,
                    messages=[{"role": "user", "content": "reply with exactly 'pong'"}],
                )
                return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
            reply = await asyncio.to_thread(_anthropic_ping)
        else:
            raise HTTPException(400, f"unknown provider_kind: {provider_kind}")
    except HTTPException:
        raise
    except Exception as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "hint": "key 不对 / base_url 错 / 网络不通 / 余额不足",
        }
    return {"ok": True, "reply_preview": reply[:80], "model": model}


def _sink_advisor_wake(source: str, mode: str, advisor_model: str, sub_id: str = "", usage: dict | None = None) -> None:
    """wish-bec4f3b9 · 顾问唤醒落盘一行 jsonl (billing 能看到顾问切换烧了多少).

    source: coop_blueprint / replan_tool / coop_review
    mode: blueprint / unstick / review
    usage 拿不到就只记事件 · 至少 billing 能列唤醒次数.
    """
    import time as _AT
    from pathlib import Path as _AP
    try:
        sink = _AP(__file__).resolve().parent / "data" / "runtime" / "advisor_wakes.jsonl"
        sink.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": _AT.strftime("%Y-%m-%dT%H:%M:%S"),
            "source": source,
            "mode": mode,
            "advisor_model": advisor_model,
            "sub_id": sub_id,
        }
        if usage:
            entry["input_tokens"] = int(usage.get("input_tokens") or 0)
            entry["output_tokens"] = int(usage.get("output_tokens") or 0)
            entry["cache_read_tokens"] = int(usage.get("cache_read_tokens") or 0)
            entry["cache_creation_tokens"] = int(usage.get("cache_creation_tokens") or 0)
        with open(sink, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------- core handler (no HTTP framework dependency) ----------

def _resolve_session_id(session_id: Optional[str]) -> str:
    """统一的 session_id 校验 + 新建逻辑·让 /chat/stream endpoint 和 _chat_impl 复用 (wish-351793b8)。

    抽出独立函数的原因：流式接口要在 worker 启动**之前**就把 sid 算出来·
    塞进第一字节的 hello 事件推给前端·这样即使后续流式中断·浏览器也已经
    持有 session_id·下次请求能接力。该函数对 idempotent 调用安全 (传 api-
    前缀进来直接透传)。

    传入 None / 空字符串 → 生成新 "api-" 前缀 ID
    传入 "api-" 前缀     → 透传
    其他前缀             → ValueError
    """
    sid = (session_id or "").strip()
    if not sid:
        return "api-" + new_session_id()
    if not sid.startswith("api-"):
        # 限制 API 只能开/续 api- 前缀的 session——避免误改 BRO 终端 session
        # 历史。如果想 resume 终端 session，应该用 /sessions/{id} 接口先 read，
        # 在 client 侧把对话续上。
        raise ValueError(
            f"API sessions must start with 'api-' prefix; got: {sid!r}. "
            "Use empty session_id for a new chat."
        )
    return sid


def _process_attachments(attachments: list[dict], session_id: str) -> tuple[str, list[dict]]:
    """处理 WebUI 上传的附件（图片 + 文档）· 落盘 + 拼文字前缀 + 收集结构化 meta。

    attachments 格式：[{"name": "screenshot.png", "data_url": "data:image/png;base64,..."}]
    返回：(描述文字块, saved_meta)
      描述文字块注入 user message 头部；
      saved_meta = [{"name","path","mime","kind": image|file}] · 随 user 消息落 jsonl ·
      WebUI 刷新/重放后凭它重建气泡里的图片与文档卡片（wish-7c579a20 · 刷新图不丢）。
    """
    import base64 as _b64
    import re as _re
    import time as _time
    from pathlib import Path as _Path

    if not attachments:
        return "", []

    _ATTACH_DIR = _Path("data/runtime/attachments")
    _ATTACH_DIR.mkdir(parents=True, exist_ok=True)

    # 粘贴/上传的图按会话留存(不再看完即删)· 让 OPUS 之后能换个问法再 look_at 同一张。
    # 顺手清掉 7 天前的旧图 · 防目录无限堆积 (best-effort · 失败不影响主流程)。
    try:
        _cutoff = _time.time() - 7 * 86400
        for _old in _ATTACH_DIR.glob("*"):
            try:
                if _old.is_file() and _old.stat().st_mtime < _cutoff:
                    _old.unlink()
            except Exception:
                pass
    except Exception:
        pass

    descriptions = []
    saved_meta: list[dict] = []  # wish-7c579a20 · 结构化附件 meta · 落 jsonl 供 WebUI 刷新重建
    # wish-00ed11c2 · 多模态直看分支: 当前模型原生视觉 → 图不走 look_at 转文字 ·
    # 注册到 RUNTIME.pending_images · 发送前由 tool_loop._diet_messages_for_send
    # 临时组装成 content list 直接进主对话 (BRO: "你不要用 look_at · 直接自己看")。
    _native_vision = False
    try:
        from model_aliases import supports_vision as _sv
        from daemon_runtime import RUNTIME as _RT
        _native_vision = bool(_sv(_RT.model or ""))
    except Exception:
        _native_vision = False
    _native_images: list[tuple[str, str]] = []
    for i, att in enumerate(attachments):
        name = att.get("name", f"image_{i+1}")
        data_url = att.get("data_url", "")

        if not data_url:
            descriptions.append(f"图{i+1} ({name}): [空图片·跳过]")
            continue

        # 解析 data_url: "data:image/png;base64,xxxx" (图片) 或 "data:application/pdf;base64,..." (文档)
        match = _re.match(r"data:([\w.+-]+/[\w.+-]+);base64,(.+)", data_url, _re.S)
        if not match:
            descriptions.append(f"附件{i+1} ({name}): [无效 data_url·跳过]")
            continue

        mime, b64_str = match.group(1), match.group(2)
        is_image = mime.startswith("image/")
        ext = mime.split("/")[-1].split("+")[0][:12]
        if ext == "jpeg":
            ext = "jpg"

        # 存到附件目录(按会话留存·不看完即删)· 文件名做基本清洗防路径穿越
        _safe = _re.sub(r"[^\w.\-]", "_", (name or f"image_{i+1}").rsplit("/", 1)[-1].rsplit("\\", 1)[-1])[:60] or f"image_{i+1}"
        if not _re.search(r"\.\w{2,5}$", _safe):
            _safe += f".{ext}"
        keep_path = _ATTACH_DIR / f"{session_id}_{int(_time.time())}_{i}_{_safe}"
        try:
            keep_path.write_bytes(_b64.b64decode(b64_str))
        except Exception as e:
            descriptions.append(f"图{i+1} ({name}): [base64 解码失败: {e}]")
            continue

        rel_path = str(keep_path).replace("\\", "/")
        saved_meta.append({"name": name, "path": rel_path, "mime": mime,
                           "kind": "image" if is_image else "file"})

        # 文档附件: 不进视觉链 · 留路径提示 (OPUS 需要内容时可 pdf_read / read_file)
        if not is_image:
            descriptions.append(
                f"附件{i+1} ({name}) · 已存: {rel_path} · "
                f"文档内容不在消息里 · 需要读时用 pdf_read(path=『已存』路径) 等工具"
            )
            continue

        # 多模态直看: 只注册 pending + 轻量占位 · 图本身直接进主对话视野
        if _native_vision:
            _native_images.append((mime, b64_str))
            descriptions.append(f"图{i+1} ({name}) · 已存: {rel_path}")
            continue

        # 纯文本模型 · 调 look_at 借视觉模型看图 · 描述里带上留存路径 · 让 OPUS 想再细看/换问法时复用同一张
        try:
            from agent_tools.look_at import _run as _look_at_run
            result = _look_at_run({"path": str(keep_path), "question": "请描述这张图片的内容。如果有文字，逐字抄出来。"})
            if result.ok:
                descriptions.append(f"图{i+1} ({name}) · 已存: {rel_path}\n{result.output}")
            else:
                descriptions.append(f"图{i+1} ({name}) · 已存: {rel_path} · [首次看图失败: {result.error}]")
        except Exception as e:
            descriptions.append(f"图{i+1} ({name}) · 已存: {rel_path} · [look_at 调用异常: {type(e).__name__}: {e}]")

    if not descriptions:
        return "", []

    # 注册 pending 图 (本轮有效 · 下个 user 轮进 chat handler 时会被重置)
    if _native_vision and _native_images:
        try:
            from daemon_runtime import RUNTIME as _RT2
            _RT2.pending_images = {"sid": session_id, "images": _native_images}
        except Exception:
            pass
        header = (
            f"[用户上传了 {len(_native_images)} 张图片 · 原图已直接进你的视野 · 逐张仔细看]\n"
            "每张都给了『已存』路径 · 对话推进后想再看某张 / 换个角度问 → "
            "直接 look_at(path=对应『已存』路径, question=...) · 别自己编路径。\n"
        )
    else:
        header = (
            f"[用户上传了 {len(attachments)} 个附件 · 下面每个都给了『已存』路径]\n"
            "想再仔细看某张 / 换个角度问(数数量、抄全部文字、盯某个细节)→ "
            "直接 look_at(path=对应『已存』路径, question=...) 再看一次·别自己编路径。\n"
        )
    return header + "\n".join(descriptions) + "\n---\n", saved_meta


# 卷六十四续七 · 渠道感知 · 微信来的 turn 在 system 末尾追加这一段·让 AI 知道"用户在手机上"。
# 不挂 user 消息(不污染历史)·挂 system(随轮重拼·即弃)。根因:src:"wechat" 之前只存进
# 历史 metadata·没喂给大模型 → AI 当 PC 请求处理·用 write_clipboard 复制本地路径(手机拿不到)。
_WECHAT_CHANNEL_NOTE = (
    "\n\n=== 当前渠道：微信（他在手机上） ===\n"
    "这一轮对话来自微信，他现在在手机上、不在电脑前。由此：\n"
    "- 要把文件 / 图片 / 视频 / 音频发给他 → 用 wechat_send 带 media_path=本地文件路径，"
    "把『真文件』发到他微信（图片→图片，视频→视频，文档 / 音频 / 其它→文件附件，"
    "≤25MB，需 24h 窗口开着）。\n"
    "- 【绝对不要】用 write_clipboard 复制路径、也不要只回一个本地路径（C:\\... 这种）——"
    "他在手机上，Ctrl+V 和电脑路径都拿不到那个文件。\n"
    "- 文字照常回即可，你的回复会自动发回他微信。\n"
    "- 【模型认知 · 0.8.5】你实际在跑的模型 = telemetry 里的『当前实际模型』"
    "（provider_configs 的 active 配置）· 不是 .env 的 OPUS_MODEL（那只是冷启动 fallback）。"
    "他让你『换模型 / 换成 X』时：告诉他当前实际模型 + 去 WebUI 右上角 ⚙ 设置 → 模型 里切换"
    "（或说『帮我切成 X』我会在对话里处理）· 【绝对不要】自己去改 .env 文件（GUARD 档会被拦·"
    "而且改错会让 daemon 起不来）。\n"
)


def _chat_impl(
    message: str,
    session_id: Optional[str],
    auto_confirm: Optional[str],
    max_tokens: int,
    attachments: Optional[list[dict]] = None,
    progress: Optional[Callable[[str, dict], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    turn_id: str = "",
    user_meta: Optional[dict] = None,
    thinking: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    advisor_coop: bool = False,
) -> dict:
    """跑一次 API 端的 tool_loop，返回 reply payload。

    抽出来不依赖 FastAPI——这样将来如果想换 Flask / aiohttp / 直接 socket，
    只换上层壳即可。
    """
    # 所有 client-side 输入校验必须先于 server-state 检查——保证 400 vs 500 含义正确。
    if not message or not message.strip():
        raise ValueError("message is required and cannot be empty")

    sid = _resolve_session_id(session_id)

    if RUNTIME.client is None:
        raise RuntimeError(
            "还没有配置 API key。请在首次相遇页 / 设置页里填 key（配置后会立即生效，无需重启）。"
        )

    # 卷四十六 III 补丁 5 · R1 · trace_id 注入 · turn_id 没传时生成一个
    # tool_loop 内部 logger.info / each tool call 都会自动带上这个 tid
    try:
        from workers.opus_logging import set_trace_id, new_trace_id
        _trace_tid = (turn_id or "")[:8] or new_trace_id()
        _trace_token = set_trace_id(_trace_tid)
        import logging as _logging
        _logging.getLogger("opus.chat").info(
            "chat in · sid=%s · policy=%s · msg=%r",
            sid, auto_confirm or os.environ.get("OPUS_API_DEFAULT_CONFIRM", "confirm"),
            message[:80],
        )
    except Exception:
        _trace_token = None

    policy = auto_confirm or os.environ.get("OPUS_API_DEFAULT_CONFIRM", "").strip() or "confirm"

    # ② 自主巡航进度 (卷七十五续四) · 包一层进度记录器 · 无论 SSE 连没连都记最新一步 ·
    # 让轮询/后台 turn 也能显示进度 (SSE 主对话照常转发 · 行为不变)。 turn_id 空则原样。
    progress = _make_progress_recorder(turn_id, progress)

    confirm = _make_remote_confirm(
        policy,
        cancel_event=cancel_event,
        session_id=sid,
        turn_id=turn_id,
        push_event=progress,  # wish-2a4d8c1e · 让 confirm 也能 push SSE event
    )

    # wish-68b0e173 phase 2a · 不再抢 _API_LOCK 全局锁
    # 用 per-session lock · 不同 sid 真并行 · 同 sid 内仍 serialize (避免 messages 写入冲突)
    with _get_session_lock(sid):
        # 拿 session 历史：先看内存缓存，没有就从磁盘 load
        messages = _API_SESSIONS.get(sid)
        if messages is None:
            try:
                messages = load_session(sid)
            except FileNotFoundError:
                messages = []
            _API_SESSIONS[sid] = messages

        # 新会话即时命名的判据 · 落盘前先记「这是不是这个 session 的第一句」+ 原始用户文本
        # (在附件描述拼进 message 之前抓·标签用干净的用户原话)
        _is_first_turn = not messages
        _first_turn_text = (message or "").strip()

        # 新会话即时命名 · 用第一句话前 ~24 字当 session label · 让标签栏/历史列表不显示
        # 裸 api-xxxx (跟 spawn-task 同款·服务端落盘·刷新/换端/后台跑的会话都带名字)。
        # 只在从没命过名时写·绝不覆盖用户手动改的名 (renameSession) 或已有 label。
        # BRO 2026-07-28 · 命名必须在协同块【之前】: 顾问同步跑 10-60s · 之前放在协同后
        # 导致"顾问模式发消息标签先不改名" (等顾问跑完才落名)。
        if _is_first_turn and _first_turn_text:
            try:
                from daemon_session import get_session_meta, set_session_meta
                if not (get_session_meta(sid).get("label") or "").strip():
                    _lbl_src = " ".join(_first_turn_text.split())
                    _lbl = _lbl_src[:24] + ("…" if len(_lbl_src) > 24 else "")
                    if _lbl:
                        set_session_meta(sid, label=_lbl)
            except Exception:
                pass

        # 写入新 user turn
        # wish-58af621e · 让压缩层知道当前 session id，摘要落盘用
        from workers.memory_compression import set_session_id
        set_session_id(sid)
        # 卷四十六 III · wish-ed5553d5 hookup · 让 request_restart 等工具能拿到当前 session
        RUNTIME.session_id = sid
        # 编辑并发软锁 · 把当前对话身份写进 ContextVar · 让 edit_file/write_file 能区分"哪个对话在改"
        try:
            from agent_tools import set_session_context
            set_session_context(sid)
        except Exception:
            pass

        # wish-4a6331b2 · 处理图片附件 → 调 look_at → 拼描述到 message 头部
        # wish-00ed11c2 · 多模态时改为注册 pending_images (图直进主对话) ·
        # 每个新 user 轮先重置 pending · 保证"图只活在它被上传的那一轮"
        try:
            RUNTIME.pending_images = None
        except Exception:
            pass
        _att_saved: list[dict] = []  # wish-7c579a20 · 附件结构化 meta · 随 user 消息落 jsonl
        if attachments:
            att_desc, _att_saved = _process_attachments(attachments, sid)
            if att_desc:
                message = att_desc + message

        # wish-0e749752 · 顾问协同模式: BRO 开了输入区 toggle →
        # 工程层强制蓝图前置 (先由顾问出施工单 · 执行者按单施工)。
        # 为什么工程层强制而不是提醒 LLM 自觉调 replan:
        #   靠软约束让执行者自觉叫顾问 = 球员兼任裁判 (2026-07-27 通知体系顾问全程没醒的教训)
        # 降级纪律: 顾问没出成单 / 协同自身炸了 → 绝不 block BRO 的消息 · 降级常规推进
        _coop_advisor: dict | None = None  # BRO 2026-07-28 · 顾问卡持久化: 数据挂 user turn meta · 刷新后历史重建
        if advisor_coop:
            try:
                _adv_label = "顾问"
                try:
                    from workers.director import get_director_config as _get_dcfg
                    _dcfg = _get_dcfg()
                    if _dcfg:
                        _adv_label = f"顾问 {((_dcfg.get('name') or '') or (_dcfg.get('model') or '')).strip()}".strip()
                except Exception:
                    pass
                if progress:
                    progress("advisor_status", {"phase": "start", "mode": "blueprint",
                                                "model_label": _adv_label, "ts": time.time()})

                def _coop_sink(evt: dict) -> None:   # 顾问内部逐步事件 → 金卡 live tick
                    try:
                        if progress:
                            progress("advisor_status", {
                                "phase": "progress", "mode": "blueprint",
                                "model_label": _adv_label,
                                "kind": evt.get("kind", ""),
                                "turn": evt.get("turn", 0),
                                "name": evt.get("name", ""),
                                "target": evt.get("target", ""),
                                "files_read": evt.get("files_read", 0),
                                "ts": time.time(),
                            })
                    except Exception:
                        pass

                # BRO 2026-07-28 · 顾问连续性: 顾问每次都是全新上下文(干净视角的价值) ·
                # 但「补充信息再发」场景下它不该失忆——扫最近一轮协同轮的施工单+BRO原话喂给它 ·
                # 让它"在原单上调整"而不是从零出单。
                _prev_bp_text = ""
                _prev_user_text = ""
                for _m in reversed(messages):
                    if _m.get("role") != "user":
                        continue
                    _pm = (_m.get("meta") or {}).get("advisor_blueprint")
                    if _pm is None:
                        continue  # 非协同轮 · 跳过 (只续协同链·不捞普通闲聊)
                    if _pm.get("ok") and (_pm.get("text") or "").strip():
                        _prev_bp_text = _pm["text"].strip()
                    _c = (_m.get("content") or "")
                    if "[BRO 的原始需求]\n" in _c:
                        _c = _c.split("[BRO 的原始需求]\n", 1)[1]  # 剥掉施工单注入·取回原话
                    elif _c.startswith("[系统 · 顾问协同模式"):
                        _c = _c.split("\n", 1)[1] if "\n" in _c else ""  # 剥降级包装·取原话
                    _prev_user_text = _c.strip()
                    break  # 只取最近一轮协同轮
                _bp_ctx_parts = []
                if _prev_bp_text:
                    _bp_ctx_parts.append(
                        "【上次顾问已出过的施工单】BRO 现在补充了新信息——请在原单基础上调整/续写 "
                        "(也可推翻重出·以 BRO 最新信息为准)·不要从零再来:\n\n" + _prev_bp_text[:3000])
                if _prev_user_text:
                    _bp_ctx_parts.append("【上一轮 BRO 的原始需求】\n" + _prev_user_text[:1500])

                from agent_tools.replan import _run as _advisor_replan_run
                _bp_res = _advisor_replan_run({
                    "mode": "blueprint",
                    "goal": message,
                    "blocker": "",
                    "context": "\n\n".join(_bp_ctx_parts),
                    "task": None,
                    "_source": "coop_mode",
                    "_progress_sink": _coop_sink,
                    "_cancel_event": cancel_event,  # BRO 2026-07-28 · 停止按钮要真能掐停顾问
                })
                if cancel_event is not None and cancel_event.is_set():
                    # BRO 点了停止 · 顾问被掐 (tool_loop 返回 ok=True text='[aborted]' · 不能信)。
                    # 不注入施工单 · 让 message 保持 BRO 原话 → 主 tool_loop 第一轮 cancel_check 自然 abort。
                    _coop_advisor = {"ok": False, "aborted": True, "model_label": _adv_label,
                                     "text": "", "sub_id": ""}
                    if progress:
                        progress("advisor_status", {"phase": "blueprint_aborted", "mode": "blueprint",
                                                    "model_label": _adv_label, "ts": time.time()})
                else:
                    _bp_ok = bool(_bp_res.ok) and bool((_bp_res.output or "").strip())
                    _bp_text = (_bp_res.output or "").strip()
                    # 顾问卡持久化 · sub_id 从 output 固定尾注提取 (replan.py:260 的 sessions/sub-xxx.jsonl)
                    _bp_sub = ""
                    try:
                        import re as _re
                        _m_sub = _re.search(r"sessions/sub-([a-zA-Z0-9_-]+)\.jsonl", _bp_res.output or "")
                        if _m_sub:
                            _bp_sub = _m_sub.group(1)
                    except Exception:
                        pass
                    _coop_advisor = {
                        "ok": _bp_ok,
                        "model_label": _adv_label,
                        "text": _bp_text[:3000] if _bp_ok else "",
                        "sub_id": _bp_sub,
                    }
                    if progress:
                        progress("advisor_status", {
                            "phase": "blueprint_done" if _bp_ok else "blueprint_failed",
                            "mode": "blueprint",
                            "model_label": _adv_label,
                            "text": _bp_text[:3000],
                            "sub_id": _bp_sub,
                            "ts": time.time(),
                        })
                    if _bp_ok:
                        _sink_advisor_wake(
                            "coop_blueprint", "blueprint",
                            _adv_label, _bp_sub,
                            getattr(_bp_res, "usage", None) or None,
                        )
                        message = (
                            "[系统 · 顾问协同模式]\n"
                            "下面是顾问针对 BRO 这条需求出的【施工单】。你是执行者:\n"
                            "严格按施工单施工 · 施工单列的【禁区】不碰 · 完工对照【验收标准】自检。\n"
                            "若施工单与 BRO 原话冲突 · 以 BRO 原话为准并说明分歧。\n\n"
                            f"{_bp_text}\n\n"
                            "────────────────\n"
                            f"[BRO 的原始需求]\n{message}"
                        )
                    else:
                        message = (
                            "[系统 · 顾问协同模式 · 顾问本次没能给出施工单 · 按常规方式直接推进 BRO 的需求]\n"
                            f"{message}"
                        )
            except Exception as _coop_err:
                _coop_advisor = {"ok": False, "model_label": locals().get("_adv_label", "顾问"),
                                 "text": "", "sub_id": ""}
                try:
                    if progress:
                        progress("advisor_status", {"phase": "blueprint_failed",
                                                    "error": f"{type(_coop_err).__name__}: {_coop_err}",
                                                    "ts": time.time()})
                except Exception:
                    pass

        # 卷八十四 · 发送前消毒 (2026-07-28): 历史里 DeepSeek 产的 content="" 空串 → null
        # Kimi 严格校验: content 空串报 400 'must not be empty' · null 才合法。
        # 覆盖热路径缓存 + 同 session 中途切模型两条路 (冷加载 load_session 已同规修) · O(n) 便宜
        for _m in messages:
            if _m.get("role") == "assistant" and _m.get("tool_calls"):
                _c = _m.get("content")
                if isinstance(_c, str) and not _c.strip():
                    _m["content"] = None

        messages.append({"role": "user", "content": message})
        _user_meta = {"src": "api"}
        if _att_saved:  # wish-7c579a20 · 附件结构化落盘 · WebUI 刷新后重建图片/文档卡片
            _user_meta["attachments"] = _att_saved
        if user_meta:
            _user_meta.update(user_meta)
        if _coop_advisor:  # BRO 2026-07-28 · 顾问卡持久化: 刷新/切回后历史渲染重建金卡
            _user_meta["advisor_blueprint"] = _coop_advisor
        append_turn(sid, "user", message, meta=_user_meta)

        # 卷四十六 III 补丁 5 · Y2 · token budget 入口检查
        # default 全部禁用 (env=0)·BRO 调高才生效·超阈值直接抛 RuntimeError·UI 看得到
        try:
            from workers.token_budget_guard import check_budget as _tbg_check
            _budget = _tbg_check(sid)
            if not _budget.get("ok"):
                if messages and messages[-1].get("role") == "user":
                    messages.pop()
                _API_SESSIONS[sid] = messages
                raise RuntimeError(
                    f"token_budget_exceeded: {_budget.get('reason') or 'unknown'}"
                )
        except RuntimeError:
            raise
        except Exception:
            # guard 自己挂了不能拖累正常 chat
            pass

        # 卷四十一 · 增量落盘 callback · 解决 daemon kill -9 时 in-flight turn 丢失
        # 每完成一个 assistant turn / tool result · tool_loop 立即调这个 hook 写盘
        def _persist_entry(entry: dict) -> None:
            meta: dict[str, Any] = {"src": "api"}
            if "tool_calls" in entry:
                meta["tool_calls"] = entry["tool_calls"]
            if "reasoning_content" in entry:
                meta["reasoning_content"] = entry["reasoning_content"]
            if entry.get("role") == "tool" and "tool_call_id" in entry:
                meta["tool_call_id"] = entry["tool_call_id"]
            append_turn(sid, entry["role"], entry.get("content", ""), meta=meta)

        # 卷五十九 · SKILL 触发修复 · 收尾检查引擎接线 (一个引擎·三处挂载)
        #   begin_turn 清 turn 台账 · observe 记录本回合每个工具调用 (P1/P3 靠它判断干了啥/沉淀没)
        #   relevant_playbooks 把命中的 playbook 递到 OPUS 手边 (P2 · 堵"下次自动取出来用"断点 B)
        _closure_observe = _no_observe
        _pb_hint = ""
        _mem_hint = ""
        _docs_hint = ""
        _memwrite_hint = ""
        _client_hint = ""
        _casual_hint = ""
        _care_hint = ""
        _ledger_hint = ""
        try:
            from workers import closure_check as _cc
            _cc.begin_turn()
            _closure_observe = _cc.make_observe()
            _pb_hint = _cc.relevant_playbooks(message, session_id=sid)  # wish-599c46bd · 注入冷却+统计
            # ① 记忆自动注入 (保守版) · 相关 BRO 画像命中即递到 OPUS 手边
            _mem_hint = _cc.relevant_memories(message, session_id=sid)
            # ①b 知识库自动注入 · 私有文档目录/命中片段递到 OPUS 手边 (产品观第5条可追溯)
            _docs_hint = _cc.relevant_docs(message, session_id=sid)
            # wish-88b4dcdc (墨言 02) · RIF 抑制记账 · 每轮调·内部 30min 节流只真跑一次·
            # 注入未用→bump 抑制分·被 load→clear · 治"每次带出来、从不被用"的慢性噪音
            _cc.try_update_suppression()
            # ①c 显式"记住"意图 → 本轮硬提醒 update_bro_note 落盘 (堵"嘴上记住了·实际没记")
            _memwrite_hint = _cc.memory_write_hint(message)
            # ①d 客户对话侧写 (B-P1/P2) · 命中已知客户/交易信号 → 软提醒记进客户档案
            _client_hint = _cc.client_extract_hint(message)
            # ①e 情感轨 (C) · 隐式闲聊信号 → 悄悄 update_bro_note (显式已命中则不叠加·避免双重指令)
            _casual_hint = _cc.casual_profile_hint(message) if not _memwrite_hint else ""
            # ①f 情感轨主动侧 (C+) · 记情感/健康信号 + 成熟期在闲聊语境软回访 (每天最多一次·防尬)
            _cc.note_care_signals(message)
            _care_hint = _cc.care_followup_hint(message)
            # ①g ③抗套娃 · 本会话活跃任务账本(已验证✓/已排除✗/决策)每轮无损回灌 · 压缩压不掉
            _ledger_hint = _cc.ledger_hint(sid)
        except Exception:
            pass

        # 沉淀闭环 v2 刀② · 工坊上下文注入 (活跃 run + 命中的 app/flow 候选) · 治"先查再搓"铁律衰减
        _workshop_hint = ""
        try:
            from workers.workshop_context import workshop_hint as _ws_hint
            _workshop_hint = _ws_hint(message)
        except Exception:
            pass

        # 卷六十四续七 · 渠道感知 · 微信 turn 给 system 末尾挂一句"你在微信上·发文件走
        # wechat_send media_path·别 write_clipboard/甩路径"。挂 system 不污染 user 历史·随轮即弃。
        # 3b · 缓存前缀稳定化: 把 system 拆成「稳定前缀」+「易变尾巴」两段传。
        #   稳定前缀 (_sys_stable = 灵魂 + 远程 hint) 一个 session 内字节不变·是可缓存前缀;
        #   易变尾巴 (_sys_tail = telemetry时间/git + playbook/记忆/工坊提示 + 微信备注) 每轮变·
        #   走 system_suffix 留在缓存断点之外 → 尾巴变也不冲掉灵魂缓存 (省钱关键)。
        #   localize 对两段分别做 (纯 token 替换·分段等价)。
        _sys_stable = _build_remote_system(RUNTIME.system_prompt)
        _sys_tail = _build_remote_tail(sid) + _pb_hint + _mem_hint + _workshop_hint + _docs_hint + _memwrite_hint + _client_hint + _casual_hint + _care_hint + _ledger_hint
        if _user_meta.get("src") == "wechat":
            _sys_tail = _sys_tail + _WECHAT_CHANNEL_NOTE
        try:
            reply, messages, usage = run_tool_loop(
                client=RUNTIME.client,
                provider=RUNTIME.provider,
                model=RUNTIME.model,
                max_tokens=max_tokens,
                system=_localize(_sys_stable),
                system_suffix=_localize(_sys_tail),
                messages=messages,
                confirm=confirm,
                observe=_closure_observe,
                base_url=RUNTIME.base_url,
                progress=progress,
                cancel_check=(cancel_event.is_set if cancel_event is not None else None),
                on_message_commit=_persist_entry,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
                # wish-8914f90c · 墙钟熔断: 后台续场 turn 传环境变量收紧预算 (resume_runner 设置)
                wall_clock_sec=_env_float("_RESUME_WALL_CLOCK_SEC"),
                llm_timeout_sec=_env_float("_RESUME_LLM_TIMEOUT_SEC"),
            )
        except Exception as e:
            # 失败时回滚那条 user msg（不让 stale 状态污染下次）
            # 注意: tool_loop 内部已经增量落盘 · 这里不需要再补落
            if messages and messages[-1].get("role") == "user":
                messages.pop()
            _API_SESSIONS[sid] = messages
            raise RuntimeError(f"{type(e).__name__}: {e}") from e

        _API_SESSIONS[sid] = messages
        # 不再批量 append_turn · tool_loop 已经在每个 turn commit 时增量落盘了

        # BRO 2026-07-28 方案 B · 协同模式自动验收 (三唤醒点第三环·从「自觉」升级成「管线强制」):
        # 触发 = 本轮协同出了施工单 + 本轮有副作用(closure_check 台账) + BRO 没点停止。
        # PASS → 验收卡 · FAIL → 意见注入自动修正一轮 → 复验 · 最多 2 次 review (防死循环+控 K3 成本)。
        # 降级纪律同协同块: 验收自身炸了绝不 block BRO 的交付。
        _coop_review: dict | None = None
        try:
            from workers import closure_check as _cc
            _se_tools = [t for t in _cc.tools_called() if t in _cc.SIDE_EFFECT_TOOLS]
        except Exception:
            _se_tools = []
        if (
            _coop_advisor and _coop_advisor.get("ok")
            and (_coop_advisor.get("text") or "").strip()
            and _se_tools
            and not (cancel_event is not None and cancel_event.is_set())
        ):
            try:
                from agent_tools.replan import _run as _advisor_replan_run
                import re as _re

                _rv_label = _coop_advisor.get("model_label") or "顾问"

                def _rv_sink(evt: dict) -> None:   # 验收顾问内部逐步事件 → live 卡 tick
                    try:
                        if progress:
                            progress("advisor_status", {
                                "phase": "progress", "mode": "review",
                                "model_label": _rv_label,
                                "kind": evt.get("kind", ""), "turn": evt.get("turn", 0),
                                "name": evt.get("name", ""), "target": evt.get("target", ""),
                                "files_read": evt.get("files_read", 0), "ts": time.time()})
                    except Exception:
                        pass

                def _verdict_of(txt: str) -> str:
                    m = _re.search(r"验收结论[:：\s*]*(PASS|FAIL)", txt or "", _re.I)
                    if m:
                        return m.group(1).upper()
                    m2 = _re.search(r"\b(PASS|FAIL)\b", txt or "", _re.I)
                    # 没给明确结论按 FAIL · 严 · 防顾问当老好人 (跟 _REVIEW_SYSTEM 的「严」对齐)
                    return m2.group(1).upper() if m2 else "FAIL"

                for _attempt in (1, 2):
                    if cancel_event is not None and cancel_event.is_set():
                        break
                    if progress:
                        progress("advisor_status", {"phase": "start", "mode": "review",
                                                    "model_label": _rv_label,
                                                    "round": _attempt, "ts": time.time()})
                    _se_list = ", ".join(dict.fromkeys(_se_tools))
                    _rv = _advisor_replan_run({
                        "mode": "review",
                        "goal": (_coop_advisor.get("text") or "")[:3000],
                        "blocker": (
                            f"【执行者交付文案(截断)】\n{(reply or '')[:1800]}\n\n"
                            f"【本轮副作用工具调用】{_se_list}\n"
                            "【说明】执行者的写动作都在上面·顾问可自行 read_file / grep / git diff 验证实物·别凭交付文案下结论。"),
                        "context": "",
                        "task": None,
                        "_source": "coop_review",
                        "_progress_sink": _rv_sink,
                        "_cancel_event": cancel_event,
                    })
                    if cancel_event is not None and cancel_event.is_set():
                        break
                    _rv_text = (_rv.output or "").strip() if _rv.ok else ""
                    _vd = _verdict_of(_rv_text) if _rv.ok else "FAIL"
                    _rv_sub = ""
                    try:
                        _m_sub = _re.search(r"sessions/sub-([a-zA-Z0-9_-]+)\.jsonl", _rv.output or "")
                        if _m_sub:
                            _rv_sub = _m_sub.group(1)
                    except Exception:
                        pass
                    _coop_review = {"ok": bool(_rv.ok), "verdict": _vd, "text": _rv_text[:3000],
                                    "round": _attempt, "model_label": _rv_label, "sub_id": _rv_sub}
                    _sink_advisor_wake(
                        "coop_review", "review",
                        _rv_label, _rv_sub,
                        getattr(_rv, "usage", None) or None,
                    )
                    if progress:
                        progress("advisor_status", {"phase": "review_done", "mode": "review",
                                                    "verdict": _vd, "text": _rv_text[:3000],
                                                    "round": _attempt, "model_label": _rv_label,
                                                    "sub_id": _rv_sub, "ts": time.time()})
                    # SSE 断流兜底: 把验收结果也写进 advisor_live.json ·
                    # 前端超时 polling /api/advisor/status 能拿到完整结果自愈 (BRO 2026-07-29)
                    try:
                        from workers import advisor_live as _adv_live
                        _adv_live.finish_live(ok=bool(_rv.ok),
                                              iterations=getattr(_rv, "iterations", 0),
                                              sub_session_id=_rv_sub,
                                              text=_rv_text[:3000], verdict=_vd)
                    except Exception:
                        pass
                    # 每次验收完立刻落盘 (不只落最后一次) · 刷新后时间线 = 实时链:
                    # round1 FAIL 卡 → 修正注入 → round2 结果卡 · 全程可回放
                    try:
                        append_turn(sid, "system", "",
                                    meta={"kind": "advisor_review", "advisor_review": _coop_review})
                    except Exception:
                        pass
                    if _vd == "PASS" or _attempt == 2 or not _rv.ok:
                        break
                    # FAIL → 意见注入 → 自动修正一轮 → 下一轮复验
                    _fix_msg = (
                        "[系统 · 顾问验收未通过 · 以下是顾问的验收意见。请逐条修正后重新交付·"
                        "修正完简述改了什么·别整段重述。]\n\n" + _rv_text[:2500])
                    messages.append({"role": "user", "content": _fix_msg})
                    try:
                        append_turn(sid, "user", _fix_msg, meta={"src": "advisor_review"})
                    except Exception:
                        pass
                    reply, messages, _u2 = run_tool_loop(
                        client=RUNTIME.client,
                        provider=RUNTIME.provider,
                        model=RUNTIME.model,
                        max_tokens=max_tokens,
                        system=_localize(_sys_stable),
                        system_suffix=_localize(_sys_tail),
                        messages=messages,
                        confirm=confirm,
                        observe=_closure_observe,
                        base_url=RUNTIME.base_url,
                        progress=progress,
                        cancel_check=(cancel_event.is_set if cancel_event is not None else None),
                        on_message_commit=_persist_entry,
                        thinking=thinking,
                        reasoning_effort=reasoning_effort,
                        # wish-8914f90c · 墙钟熔断 (同主调用点)
                        wall_clock_sec=_env_float("_RESUME_WALL_CLOCK_SEC"),
                        llm_timeout_sec=_env_float("_RESUME_LLM_TIMEOUT_SEC"),
                    )
                    try:
                        usage.input_tokens += _u2.input_tokens
                        usage.output_tokens += _u2.output_tokens
                    except Exception:
                        pass
                    _API_SESSIONS[sid] = messages
                    # 修正轮的新动作并入交付说明 (复验要对照最新实物)
                    try:
                        _se_tools = [t for t in _cc.tools_called() if t in _cc.SIDE_EFFECT_TOOLS]
                    except Exception:
                        pass
            except Exception:
                pass  # 验收自身炸了不 block 交付 (跟协同块同一条降级纪律)

        # 卷五十九 · P3 · turn 结束反思 · 本回合干了活 (副作用工具≥2次) 却没沉淀 →
        # 推一张"收尾提示"卡 (SSE·前端可点) + 落对账台账 closure_hints.jsonl·闭环不靠当场记得。
        try:
            from workers import closure_check as _cc
            _cc_report = _cc.turn_end_report()
            if _cc_report:
                _cc.record_hint(sid, _cc_report)
                if progress is not None:
                    progress("closure_hint", _cc_report)
        except Exception:
            pass

        # 2026-07-28 BRO 需求 · 桌宠弹「🎉 干完了」· 实质 turn (干活+沉淀≥2) 收尾时
        # 文字取 OPUS 最终回复第一行 (收尾纪律保证它是"✅ 做完了:...") · 取不到就兜底
        # 2026-07-28 缝隙修: 计数集合 = 副作用 ∪ 沉淀 (SINK)——"验证+沉淀"的完整轮也弹
        # (原先只数副作用·沉淀工具刻意不在其中·导致最完整的一轮反而不弹·语义拧了)
        try:
            from workers import closure_check as _cc
            _se_n = len([t for t in _cc.tools_called() if t in (_cc.SIDE_EFFECT_TOOLS | _cc.SINK_TOOLS)])
            if _se_n >= 2:
                _first = (reply or "").strip().split("\n")[0].strip() if reply else ""
                _first = _first.lstrip("#* ✅🎉✨").strip()
                if not _first:
                    _first = f"做完了 · 这轮跑了 {_se_n} 个动作"
                # 桌宠气泡 (notify.jsonl)
                try:
                    from desktop_pet.activities import write_notify as _pet_notify
                    _pet_notify("done", _first[:40])
                except Exception:
                    pass
                # 事项 B · Windows toast (独立 try · 不跟 pet_notify 串扰)
                try:
                    from workers.windows_toast import send_toast as _send_toast
                    _send_toast("OPUS 干完了", _first[:40])
                except Exception:
                    pass
        except Exception:
            pass

        # 卷四十六 III 补丁 5 · Y2 · token budget 出口累加 · 不抛错
        try:
            from workers.token_budget_guard import consume as _tbg_consume
            _tbg_consume(
                sid,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
        except Exception:
            pass

        # wish-bec4f3b9 · 主对话 usage 落盘 (billing 按模型聚合 · 含缓存明细)
        try:
            from pathlib import Path as _UP
            import time as _UT
            _sink = _UP(__file__).resolve().parent / "data" / "runtime" / "chat_turns_usage.jsonl"
            _sink.parent.mkdir(parents=True, exist_ok=True)
            with open(_sink, "a", encoding="utf-8") as _uf:
                _uf.write(json.dumps({
                    "ts": _UT.strftime("%Y-%m-%dT%H:%M:%S"),
                    "session_id": sid,
                    "model_id": RUNTIME.model,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_read_tokens": usage.cache_read_tokens,
                    "cache_creation_tokens": usage.cache_creation_tokens,
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # 卷四十六 III 补丁 5 · R1 · 清 trace_id ContextVar
    if _trace_token is not None:
        try:
            from workers.opus_logging import reset_trace_id
            reset_trace_id(_trace_token)
        except Exception:
            pass

    return {
        "reply": reply,
        "session_id": sid,
        "model": RUNTIME.model,
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_creation_tokens": usage.cache_creation_tokens,
        },
        "auto_confirm": policy,
    }


# ---------- FastAPI app ----------

def build_app():
    """延迟 import fastapi——这样依赖没装时整个模块仍可被 import，
    只在真正想跑 API 时才需要装包。"""
    try:
        from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
        from fastapi.responses import (
            FileResponse,
            HTMLResponse,
            JSONResponse,
            PlainTextResponse,
        )
    except ImportError as e:
        raise RuntimeError(
            "fastapi not installed; run: pip install fastapi uvicorn"
        ) from e

    app = FastAPI(title="OPUS Daemon API", version="0.1.0")

    # wish-413999da phase 1 · closure helpers 提到 api_routes/_deps.py
    # 保留同名 local 绑定让旧路由 closure 调用照常工作
    from api_routes._deps import check_auth as _check_auth
    from api_routes._deps import check_rate_limit as _check_rate_limit

    # wish-bb84a386 · loopback 鉴权豁免 (卷四十六续 V) · 同机 127.0.0.1 自动信任
    # 关闭办法: env OPUS_LOOPBACK_TRUST=false (远程部署用)
    from api_routes._deps import loopback_auth_middleware
    app.middleware("http")(loopback_auth_middleware)


    # wish-413999da phase 1 · 5 路由抽到 api_routes/core.py:
    #   / · /api/ping-test · /ui · /static/{path:path} · /workshop/outputs/{filename:path}
    # 注册见 build_app() 末尾的 include_router(core_router)

    # wish-413999da phase 1 · /models /models/switch 2 路由抽到 api_routes/models.py

    # wish-413999da phase 1 · /status /api/token_budget/* /api/ratelimit/status
    # /api/audit/recent /api/session/repair 抽到 api_routes/governance.py
    # /api/env/reload_status /api/lifecycle_status 抽到 api_routes/lifecycle.py
    # /api/logs/tail 抽到 api_routes/core.py

    # wish-413999da phase 1 · /chat /chat/stream + turns/* (5 路由) 抽到 api_routes/chat.py
    # 见 build_app() 末尾 include_router

    # wish-413999da phase 1 · /sessions/* 6 路由抽到 api_routes/sessions.py

    # ── cockpit · 6+1 维聚合视图（卷二十五加）─────────────────
    # 一次返回所有维度的 head N 条 · 避免前端发 6+ 个并行 fetch · 减少 RTT
    # wish-413999da phase 1 · /dashboard/cockpit + /dashboard/{domain} 2 路由
    # + _list_reports + _build_calendar_day + _serve_report_file (closure helpers)
    # 抽到 api_routes/dashboard.py · 见 build_app() 末尾 include_router

    # ──────────────────────────────────────────────────────────
    # 卷四十四 K stage 2c · 出品工坊资产 endpoint · apps + flows
    # ──────────────────────────────────────────────────────────

    # wish-413999da phase 1 · workshop apps CRUD 4 路由抽到 api_routes/workshop.py

    # wish-413999da phase 1 · workshop 18 路由抽到 api_routes/workshop.py
    # 见 build_app() 末尾 include_router

    # wish-413999da phase 1 · /reviews /reviews/preview /reviews/file
    # + REVIEWS_DIR + _resolve_review_md 抽到 api_routes/intelligence.py

    # wish-413999da phase 1 · 沉淀位路由 (/sinks, /sinks/preview, /sinks/reveal)
    # + SINKS dict + _resolve_sink helper 抽到 api_routes/sinks_pulse_digest.py

    # ────────────────────────────────────────────────────────────────
    # wish-413999da phase 1 · 路由模块挂载
    # 每个 area 一个 api_routes/<area>.py · 这里 include_router
    # ────────────────────────────────────────────────────────────────
    from api_routes import core as _routes_core
    from api_routes import lifecycle as _routes_lifecycle
    from api_routes import governance as _routes_governance
    from api_routes import trust as _routes_trust
    from api_routes import sinks_pulse_digest as _routes_spd
    from api_routes import sessions as _routes_sessions
    from api_routes import intelligence as _routes_intel
    from api_routes import workshop as _routes_workshop
    from api_routes import chat as _routes_chat
    from api_routes import models as _routes_models
    from api_routes import providers as _routes_providers
    from api_routes import dashboard as _routes_dashboard
    from api_routes import knowledge as _routes_knowledge
    from api_routes import playbooks as _routes_playbooks
    from api_routes import clients as _routes_clients
    from api_routes import vision as _routes_vision
    from api_routes import notifications as _routes_notifications
    from api_routes import advisor as _routes_advisor
    # 2026-08-08 · /api/tts 语音回复 (商业化 TTS · 归属待决 · 优雅降级: 纯净版无 voice.py 不崩)
    try:
        from api_routes import voice as _routes_voice
    except Exception:
        _routes_voice = None
    app.include_router(_routes_core.router)
    app.include_router(_routes_lifecycle.router)
    app.include_router(_routes_governance.router)
    app.include_router(_routes_trust.router)
    app.include_router(_routes_spd.router)
    app.include_router(_routes_sessions.router)
    app.include_router(_routes_intel.router)
    app.include_router(_routes_workshop.router)
    app.include_router(_routes_chat.router)
    app.include_router(_routes_models.router)
    app.include_router(_routes_providers.router)
    # 知识库/技能库/客户档案路由必须在 dashboard 之前 · /dashboard/knowledge* /dashboard/playbooks* /dashboard/clients* 才不会被 /dashboard/{domain} 吞掉
    app.include_router(_routes_knowledge.router)
    app.include_router(_routes_playbooks.router)
    app.include_router(_routes_clients.router)
    app.include_router(_routes_dashboard.router)
    app.include_router(_routes_vision.router)  # wish-4a6331b2 · /vision-config (曾漏注册→404)
    app.include_router(_routes_notifications.router)  # wish-fb6b7427 · /notification-config
    app.include_router(_routes_advisor.router)  # wish-ea8922f7 · /api/advisor/status + trace
    if _routes_voice is not None:
        app.include_router(_routes_voice.router)  # 2026-08-08 · /api/tts 语音回复 (有 voice 才挂)

    # 形态 Z · 相遇初始化路由 (开源版 Daemonkey 有·母体 OPUS 无此模块 → 守卫跳过)
    try:
        from api_routes import onboarding as _routes_onboarding
        app.include_router(_routes_onboarding.router)
    except Exception:
        pass

    return app


def _compact_blank_lines(lines: list[str]) -> list[str]:
    """连续空行折叠为一个 · 给 docx 抽取兜底用"""
    out: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = (not line.strip())
        if is_blank and prev_blank:
            continue
        out.append(line)
        prev_blank = is_blank
    return out


# ---------- background thread starter ----------

_API_THREAD: Optional[threading.Thread] = None


def start_api_in_background(
    port: int,
    host: str = "127.0.0.1",
    log_level: str = "warning",
) -> Optional[threading.Thread]:
    """在后台 daemon thread 里跑 uvicorn。

    host 默认 127.0.0.1——只本机能访问，公网入口靠 cloudflared / frp tunnel
    主动转发。这是双重安全：
      1. 端口不直接暴露到公网，路由器 / 防火墙不用配
      2. tunnel 这一层可以加它自己的 access control（Cloudflare Access 等）

    想直接对外暴露（不推荐）→ host="0.0.0.0"

    卷四十六 III · 加 daemon_lifecycle init · 跟 run_api_only.py 对齐:
      - 双 daemon 防护 (pid 锁)
      - 重启续场 (consume restart_request · 给 session 注 system message)
      - crash 检测 (上次没 graceful exit → 给活跃 session 注 crash 通知)
    """
    global _API_THREAD
    if _API_THREAD is not None and _API_THREAD.is_alive():
        return _API_THREAD

    # 卷四十六 III 补丁 5 · R1 · 统一 logging · daemon 启动早期装上 (lifecycle 之前)
    try:
        from workers.opus_logging import init_logging
        init_logging()
    except Exception as e:
        print(f"[opus-api] WARN · opus_logging init 出错 (不阻塞启动): {type(e).__name__}: {e}")

    lc = None
    try:
        from workers.daemon_lifecycle import init_lifecycle
        lc = init_lifecycle(host, port)
        if not lc["ok"]:
            raise RuntimeError(f"daemon_lifecycle pid lock failed:\n{lc['lock_message']}")
        if lc.get("restart_request"):
            req = lc["restart_request"]
            print(f"[opus-api] 检测到 restart_request · reason='{(req.get('reason') or '')[:80]}' · "
                  f"session={req.get('session_id')} · 已注续场 system message")
        if lc.get("crash_marker"):
            cm = lc["crash_marker"]
            print(f"[opus-api] 上次 daemon (pid={cm.get('old_pid')}) 异常退出 · "
                  f"已给 {lc['resume_stats'].get('crash_resumed', 0)} 个活跃 session 注 crash 通知")
    except RuntimeError:
        raise
    except Exception as e:
        print(f"[opus-api] WARN · daemon_lifecycle init 出错 (不阻塞启动): {type(e).__name__}: {e}")

    # 卷四十六 III 补丁 3 · 自动续场 turn (start_api_in_background 路径 · 走 opus_daemon.py 入口)
    if lc and lc.get("restart_request"):
        try:
            from workers.resume_runner import schedule_resume_turn
            if schedule_resume_turn(lc["restart_request"]):
                fu = (lc["restart_request"].get("follow_up_message") or "")[:80]
                print(f"[opus-api] 自动续场 turn 已 schedule · follow_up='{fu}...'")
        except Exception as e:
            print(f"[opus-api] WARN · 自动续场 schedule 失败 (不阻塞): {type(e).__name__}: {e}")

    try:
        import uvicorn
    except ImportError:
        raise RuntimeError("uvicorn not installed; run: pip install uvicorn")

    app = build_app()
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level,
        access_log=False,
    )
    server = uvicorn.Server(config)

    def _run():
        try:
            server.run()
        except Exception as e:
            # API 线程崩了不能让主进程也崩——daemon 主循环优先
            print(f"[opus-api] uvicorn server crashed: {e}")

    t = threading.Thread(target=_run, daemon=True, name="opus-api")
    t.start()
    # 给 uvicorn 1 秒起服务器，方便启动消息打印有序
    time.sleep(0.5)
    _API_THREAD = t
    return t


def is_api_alive() -> bool:
    return _API_THREAD is not None and _API_THREAD.is_alive()
