"""
# wish-83fe7c7b 重启续场测试
daemon_api.py
=============

OPUS Daemon · HTTP API · 远程入口
---------------------------------
让 daemon 不再只能从本机终端被找到——任何外部入口（Telegram bridge /
Web UI / curl / iOS Shortcuts / 未来的微信桥）都通过这一层和 OPUS 对话。

设计要点（卷十四 用户 离职月省钱期立项）：

1. **session 隔离**：API 端的对话默认用独立 session（前缀 `api-`），不和
   daemon 终端主循环共享 messages。两个并发会话各跑各的——避免锁竞争 +
   防止远程消息污染 用户 当面跟 OPUS 的对话。

2. **三档信任 → 远程版**：用户 在外面按不了 y/n。API 端用单一 `auto_confirm`
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
#   - 所以 chat_impl 抢 session lock 不抢全局锁 · 用户 终端 A + 终端 B 真并行
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
# 用来让 frontend 启动 polling auto-refresh · 不让 用户 手动 F5 第二次
# turn_id → sid · 跟 _ACTIVE_TURNS 同步生命周期 (worker 启动注册 · 退出删)
_TURN_TO_SID: dict[str, str] = {}


# ---------- confirm policy ----------

_TIER_RANK = {TIER_AUTO: 1, TIER_CONFIRM: 2, TIER_GUARD: 3}

# 卷五十六 · 后台续场 turn 防自爆链 (2026-06-06 · 用户 复盘「连着重启两回」)
# 这些工具会重启/关停 daemon 自身。 在「无人值守 turn」(push_event is None · 没有
# 前台 SSE 接收方 · 典型就是 resume_runner 的 follow_up 续场 turn) 里绝不允许它们跑——
# 否则「前台重启 → 续场自动验证 → 续场又调 request_restart → 再重启」无限套娃·
# 还会把 用户 正在看的对话状态打断。 request_restart 是 CONFIRM 档·policy=confirm 下本
# 会自动 go·所以必须在 rank<=threshold 之前一刀拦死·且不受 OPUS_RESUME_AUTO_CONFIRM 影响。
_BACKGROUND_BLOCKED_TOOLS = {"request_restart"}


# === wish-2a4d8c1e · inline confirm UI (卷四十六 续 3) ===
#
# LLM 撞 CONFIRM/GUARD 工具 (超 policy 阈值) 时 · 不立刻 raise 'declined' · 改为:
#   1. 检查 trusted_commands (复用 wish-f563a56d) · 命中 downgrade · 直接 go
#   2. 没命中 → push SSE event `confirm_request` 给前端 (chat 弹卡片)
#   3. worker thread 阻塞 wait Event · 直到 用户 点按钮 (POST /turns/confirm)
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
#     "reason": str,             # 用户 拒绝时填的备注
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
         add_trusted 安全检查会拒掉的 (防 用户 加 'pip install | rm -rf /' 这种 pattern)
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
# 关键作用：让 OPUS 知道自己走的是非终端通道（无阻塞 y/n），但**不要误判 用户 一定在远程**——
#   卷五十四：旧文案断言"用户 通过手机、不在机器旁、看不到屏幕"，导致 OPUS 在本机 WebUI 里
#   也对 用户 说"我是远程"。本机浏览器和手机远程走同一条通道、daemon 区分不了，所以改成
#   "可能远程"的保守措辞，并明确禁止 OPUS 对 用户 断言"我是远程"。
_REMOTE_SYSTEM_HINT = """\

---

## 当前会话的接入方式：WebUI / API（非本机终端 REPL）

**重要**：你不是通过本机终端 REPL 跟 用户 说话，而是通过 WebUI / API 通道。
**本机浏览器的 WebUI 和手机/外网远程走的是同一条通道·你无法区分**——
按"可能远程"的保守前提调整本机感知行为，但**别对 用户 断言"你是远程"**
（他很可能就坐在这台机器前用浏览器）：

1. **不一定能看到屏幕** —— 他可能在本机浏览器（看得到），也可能在手机（看不到）。
   `take_screenshot` / `open_app` 这种"打开给你看"在远程会落空。要让 用户 看东西，
   优先用能把内容直接带回对话的工具（`browser_fetch` / `web_fetch`），少用"我打开了 X 你看一下"。
2. **按不了终端 y/n** —— 本机终端那个阻塞式确认红框在这条通道里不存在。
   CONFIRM/AUTO 档工具按 `OPUS_API_DEFAULT_CONFIRM` 策略自动跑（默认 confirm 档：AUTO + CONFIRM
   都自动执行、不弹卡片）；只有 GUARD 档（高危）才会在 WebUI 弹 inline 确认卡片等 用户 点。
   → 准确说法是"当前走 API 通道·CONFIRM 档按策略自动执行"，**别说"我是远程所以不弹确认"**误导 用户。
3. **拿内容用 fetch 类工具** —— 想看网页用 `browser_fetch`（attach 他已登录的 Edge，能看
   登录态页面）或 `web_fetch`（无登录 / 走 httpx）。**不要**截屏让他描述。
4. **回话尽量精简** —— 屏幕可能小、流量可能贵；省略寒暄，直接给结论。需要多步骤的事，
   一段话讲清三件：你做了什么 / 看到了什么 / 下一步建议。
5. **长任务慎用** —— SSE 流式输出虽然解决了 cloudflared 100s 超时，但 用户 在外面等
   3 分钟仍然是糟糕体验。`summon_cursor`、跨大目录 grep、连续抓十几个网页这种事
   宁愿告诉 用户 "需要回本机操作 / 让我用更直接的方法"。

## 反爬 / 限流 / 验证码的标准处理（卷十八硬规则）

你历史上反复栽过的坑：手机端被用户让"拉知乎热榜 + 评论"，结果跑了 12 轮工具
反复换关键词换源死磕反爬，浪费 200 秒 + 大量 token + 最后输出"超出 max iterations"
什么都没给 用户。**杜绝这种事**：

- 看到 `401 Unauthorized` / `403 Forbidden` / `HTTP 202`（DuckDuckGo 反爬）/
  网页里"验证 / 请登录 / 异常访问 / 安全验证 / 请求异常"等关键词 → **立即停止重试
  这个数据源**，不要换关键词 / 不要换聚合站继续撞。直接告诉 用户 哪个源拿不到。
- **同一类目标连续 2 个源失败 → 立即停止，告诉 用户 当前能拿到的部分 + 拿不到的原因**。
  不要试到 5 个源都失败。
- **已经拿到"够回答原问题"的数据，立刻停手输出**——不要因为"可以更全/更深"再去抓
  评论 / 详情。用户 在外面要的是 30 秒能扫完的速答，不是博士论文。

## 工具调用 args 的纪律

每个工具的 input_schema 在 description 里都说得很清楚。**严格按字段名 + 字段类型**
传 args。如果你看到工具返回 "args 不符合 schema..." 错误：

- **不要重复同样的错误**——错误信息里告诉了你正确的字段名和类型，下一轮按那个改。
- **不要凭直觉造字段名**——比如 web_fetch 只有 `url` 和 `max_chars` 两个字段，
  不要塞 `"string"`、`"endpoint"`、`"target"` 这种字段。

## 卷四十六 wish-2a4d8c1e · Inline Confirm UI · CONFIRM/GUARD 工具撞 用户

daemon 在 chat 里给你装了一个 inline confirm 卡片系统。当你调 CONFIRM 或 GUARD 级工具
（超出当前 policy 阈值）时：

1. **daemon 会在 chat 弹卡片给 用户** —— 不再像以前那样直接返回 "declined" 给你。
2. **你必须在 args 里加两个扩展字段** —— schema 没列但 daemon 会读：
   - `risk_explanation`: **这条调用可能带来什么风险**（1-2 句话，具体到文件 / 进程 / 网络 /
     数据丢失）
   - `mitigation`: **你打算怎么规避这个风险**（1-2 句话，例如 "先 dry-run 看路径 / timeout
     10s / 失败不重试 / 留 git stash 兜底 / 只读不写"）
3. **写不下就别瞎写** —— 风险 / 规避必须**真**，不是套话。写 "可能有风险" / "我会小心"
   这种废话 用户 会不放心、不点 approve。不知道副作用就老实说不知道 —— **直接调一个
   只读探测工具先看清楚，再来调有副作用的工具**。
4. 用户 看完会点 4 个按钮之一：[只这次] / [信任 30min] / [信任 24h] / [永久信任] 或 [拒绝]。
   你的 tool call 会**阻塞**到 用户 点了为止（30min 超时则 auto-deny）。

**好坏对照示例** —— 用户 说 "清下 build 缓存吧"：

✓ 好的填法：
```
{
  "command": "rm -rf dist/",
  "risk_explanation": "递归删整个 dist/ 目录·里面是 npm build 的输出·删了下次 用户 跑 npm build 要重做约 2 分钟",
  "mitigation": "我先 ls dist/ 确认确实是 build 输出 (.js / .map / index.html)·dist/ 不在 git 里·没回滚需求·删错也只是要重 build"
}
```

✗ 坏的填法（用户 会不放心 → 拒绝）：
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
  CONFIRM 工具的卡片上 用户 只能选 [只这次] / [拒绝]——你写 mitigation 时不要承诺 "下次也
  不需要确认" 这种话，用户没这个按钮可点。
"""


# P1 代码归一 · 把 system 里的 OPUS/BRO 令牌本地化成本实例的名字 (母体走缺省值 = no-op)
try:
    from identity import localize as _localize
except Exception:
    def _localize(t):
        return t


def _build_remote_system(base: str, session_id: str = "") -> str:
    """拼装 system prompt · 静态 soul + 远程 hint + 动态 telemetry (wish-1d286099)。"""
    result = base + _REMOTE_SYSTEM_HINT
    if session_id:
        try:
            from workers.dynamic_telemetry import build_dynamic_telemetry
            result += build_dynamic_telemetry(session_id)
        except Exception:
            pass  # telemetry 炸了不影响正常对话
    return result


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
        2. push SSE confirm_request 给前端 · 等 用户 点按钮
        3. 30min 超时 auto-deny
      session_id / turn_id / push_event 都是新参数 · 用于注册 _PENDING_CONFIRMS
      和 push SSE 事件; 老的 confirm_only_legacy 模式 (没传 push_event) 退化到旧逻辑

    新签名第四参数 tool_call_id (在 _call_confirm 里传) · 用作 _PENDING_CONFIRMS key

    卷三十六 · cancel_event 传进来 · 用户 点停止时 set · 这里返回 "abort"
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
                "reject:你正跑在一个【后台续场 turn】里 (没有前台 SSE · 用户 不在场看)。"
                "这个 turn 本身就是上一次重启之后新 daemon 自动拉起的——新代码早已装载、"
                "你此刻就活在重启好的新 daemon 上·根本不需要再调 " + spec.name + "。"
                "在后台二次重启会造成「重启→续场→又重启」套娃·还会打断 用户 正在看的对话。"
                "→ 直接做完你的验证任务即可; 如果你真判断还需要再重启·把原因讲给 用户·"
                "由 用户 在 WebUI 手动点重启按钮 (那条路径有前台在场)。"
            )

        # wish-2a4d8c1e · 先 pop risk/mitigation · 不管走哪条路 args 都不再带这两字段
        risk, mitigation = _pop_risk_fields(args)

        # 卷四十六 III 补丁 5 · GUARD tier 强制要求 risk_explanation + mitigation 都填
        # 用户 截图反馈: 经常看到"OPUS 未说明" · 闭眼批准心慌
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
                    + " + ".join(missing) + " 字段才能让 用户 看到批准卡片. 你这次没填, "
                    "daemon 直接拦下来了——请重新调用同一个工具, 在 args 里加上:\n"
                    '  "risk_explanation": "这次操作的具体风险 (1-2 句, 比如 \'递归删 X 目录, 里面有 Y, 删了下次要 Z 分钟重做\')",\n'
                    '  "mitigation": "你打算怎么规避 (1-2 句, 比如 \'先 dry-run 看路径 / 失败不重试 / 留 git stash 兜底\')"\n'
                    "禁止套话 (\'可能有风险\' / \'我会小心\'), 必须真. 加上后立即重试, 用户 才会看到批准请求."
                )

        # 老规则: tier ≤ threshold → 直接 go (AUTO 永远过; confirm policy 下 CONFIRM 也过)
        if rank <= threshold:
            return "go"

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
            TIER_CONFIRM: "CONFIRM tier · 改动类操作 · 当前策略要 用户 点确认",
            TIER_GUARD: "GUARD tier · 高风险 · 必须 用户 显式批准",
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
        except Exception:
            pass  # push 失败不阻止流程 · 直接走超时 auto-deny

        # 阻塞等 用户 决议 (或 cancel · 或超时)
        # 每 1s 检查一次 cancel · 让 用户 点停止能立刻退出
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
                    pending_data["reason"] = "(auto-denied · 用户 未在 30min 内响应)"
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
                break  # event set · 用户 决议来了

        # 读决议
        # 注: trust_* 决议下的 add_trusted 已经在 POST /turns/{tid}/confirm endpoint 完成
        # (卷四十六续 4 · 防止 worker 端 try/except: pass 静默吞 ValueError)
        # 这里只读 decision 决定 go / skip
        with _PENDING_CONFIRMS_LOCK:
            decision = pending_data.get("decision") or "deny"
            reason = pending_data.get("reason") or ""

        cleanup_pending_confirm(tool_call_id)

        if decision == "deny":
            # 卷五十四 · 闭环修复 (Hermes '固化知识' 那一环): 用户 拒绝时填的理由
            # 必须喂回 LLM · 否则 OPUS 只收到"用户拒绝了"·学不到 用户 的边界。
            # 走 reject:<msg> 通道 (tool_loop 会把 <msg> 当 tool_result.error 给 LLM)。
            r = (reason or "").strip()
            if r:
                return (
                    f"reject:用户 拒绝了这次 `{spec.name}` 调用 · 理由: {r}\n"
                    f"→ 认真对待这个理由 (这是 用户 的边界/偏好信号) · 换思路或先问清楚 · "
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

    用户 反馈"4096 太小 · DeepSeek 支持 384K 输出 · 这个限制让 OPUS 写两步就被截断".
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
            client = OpenAI(api_key=api_key, base_url=base_url_)
            extra_body: dict = {}
            if base_url and "deepseek.com" in base_url.lower():
                extra_body = {"thinking": {"type": "disabled"}}
            resp = client.chat.completions.create(
                model=model, max_tokens=200,
                messages=[{"role": "user", "content": "reply with exactly 'pong'"}],
                extra_body=extra_body if extra_body else None,
            )
            reply = (resp.choices[0].message.content or "").strip()
        elif provider_kind == "anthropic":
            from anthropic import Anthropic
            kwargs: dict = {"api_key": api_key}
            if base_url_:
                kwargs["base_url"] = base_url_
            client = Anthropic(**kwargs)
            resp = client.messages.create(
                model=model, max_tokens=200,
                messages=[{"role": "user", "content": "reply with exactly 'pong'"}],
            )
            reply = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
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
        # 限制 API 只能开/续 api- 前缀的 session——避免误改 用户 终端 session
        # 历史。如果想 resume 终端 session，应该用 /sessions/{id} 接口先 read，
        # 在 client 侧把对话续上。
        raise ValueError(
            f"API sessions must start with 'api-' prefix; got: {sid!r}. "
            "Use empty session_id for a new chat."
        )
    return sid


def _process_attachments(attachments: list[dict], session_id: str) -> str:
    """处理 WebUI 上传的图片附件 · 对每张图调 look_at → 拼成文字前缀。

    attachments 格式：[{"name": "screenshot.png", "data_url": "data:image/png;base64,..."}]
    返回：拼好的描述文字块（可直接注入 user message 头部）
    """
    import base64 as _b64
    import re as _re
    from pathlib import Path as _Path

    if not attachments:
        return ""

    _ATTACH_DIR = _Path("data/runtime/attachments")
    _ATTACH_DIR.mkdir(parents=True, exist_ok=True)

    descriptions = []
    for i, att in enumerate(attachments):
        name = att.get("name", f"image_{i+1}")
        data_url = att.get("data_url", "")

        if not data_url:
            descriptions.append(f"图{i+1} ({name}): [空图片·跳过]")
            continue

        # 解析 data_url: "data:image/png;base64,xxxx"
        match = _re.match(r"data:(image/[\w+-]+);base64,(.+)", data_url, _re.S)
        if not match:
            descriptions.append(f"图{i+1} ({name}): [无效 data_url·跳过]")
            continue

        mime, b64_str = match.group(1), match.group(2)
        ext = mime.split("/")[-1].split("+")[0]
        if ext == "jpeg":
            ext = "jpg"

        # 写到临时文件
        tmp_path = _ATTACH_DIR / f"{session_id}_{i}_{name}"
        try:
            tmp_path.write_bytes(_b64.b64decode(b64_str))
        except Exception as e:
            descriptions.append(f"图{i+1} ({name}): [base64 解码失败: {e}]")
            continue

        # 调 look_at 看图
        try:
            from agent_tools.look_at import _run as _look_at_run
            result = _look_at_run({"path": str(tmp_path), "question": "请描述这张图片的内容。如果有文字，逐字抄出来。"})
            if result.ok:
                desc = result.output
                descriptions.append(f"图{i+1} ({name}):\n{desc}")
            else:
                descriptions.append(f"图{i+1} ({name}): [看图失败: {result.error}]")
        except Exception as e:
            descriptions.append(f"图{i+1} ({name}): [look_at 调用异常: {type(e).__name__}: {e}]")
        finally:
            # 清理临时文件
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    if not descriptions:
        return ""

    header = f"[用户上传了 {len(attachments)} 张图片]\n"
    return header + "\n".join(descriptions) + "\n---\n"


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
        raise RuntimeError("daemon RUNTIME not initialized; API called too early?")

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
        if attachments:
            att_desc = _process_attachments(attachments, sid)
            if att_desc:
                message = att_desc + message
        messages.append({"role": "user", "content": message})
        _user_meta = {"src": "api"}
        if user_meta:
            _user_meta.update(user_meta)
        append_turn(sid, "user", message, meta=_user_meta)

        # 卷四十六 III 补丁 5 · Y2 · token budget 入口检查
        # default 全部禁用 (env=0)·用户 调高才生效·超阈值直接抛 RuntimeError·UI 看得到
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
        try:
            from workers import closure_check as _cc
            _cc.begin_turn()
            _closure_observe = _cc.make_observe()
            _pb_hint = _cc.relevant_playbooks(message)
        except Exception:
            pass

        # 卷六十四续七 · 渠道感知 · 微信 turn 给 system 末尾挂一句"你在微信上·发文件走
        # wechat_send media_path·别 write_clipboard/甩路径"。挂 system 不污染 user 历史·随轮即弃。
        _sys = _build_remote_system(RUNTIME.system_prompt, session_id=sid) + _pb_hint
        if _user_meta.get("src") == "wechat":
            _sys = _sys + _WECHAT_CHANNEL_NOTE
        try:
            reply, messages, usage = run_tool_loop(
                client=RUNTIME.client,
                provider=RUNTIME.provider,
                model=RUNTIME.model,
                max_tokens=max_tokens,
                system=_localize(_sys),
                messages=messages,
                confirm=confirm,
                observe=_closure_observe,
                base_url=RUNTIME.base_url,
                progress=progress,
                cancel_check=(cancel_event.is_set if cancel_event is not None else None),
                on_message_commit=_persist_entry,
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
    app.include_router(_routes_dashboard.router)

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
