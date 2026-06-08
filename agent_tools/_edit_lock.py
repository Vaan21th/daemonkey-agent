"""
agent_tools/_edit_lock.py
=========================

编辑并发软锁 —— 防"对话 A 和对话 B 同时改同一个文件、后写的悄悄盖掉先写的"。

为什么造它:
  daemon 是单进程多会话(多个 WebUI 标签 / 续场 / 终端都在一个进程里跑)。两个对话
  几乎同时改同一个文件时:
    - edit_file 的"唯一命中"只在改【同一段】时撞墙·改【不同段】两边都成功(没问题)·
      但用 write_file 整文件覆盖就会无声碾掉对方。
    - 这是目前唯一会真正丢数据的并发口子(其余风险都有事后回退网兜着)。

它怎么治:
  一张【进程内】的按文件锁登记表(owner = session id · TTL 自动过期)。每次 edit_file /
  write_file 写盘前问一句:
    1) 锁冲突 —— 这文件 TTL 内正被【另一个对话】改 → 软提示"排队"·让 LLM 告诉用户·
       确认不冲突再带 force=true 重调。 (你选的 ask 软提示·不硬拦)
    2) 指纹防覆盖 —— 磁盘内容自上次被工具改过后又变了(被外部 / Cursor / 另一对话改的) →
       直接覆盖会盖掉那次改动 → 软提示·让 LLM 先重读再 force。

设计原则(照抄 _git_lock 的克制):
  - 纯进程内 · 一把 threading.Lock 守登记表 · 不落盘(不引入文件锁损坏风险)
  - 只覆盖 daemon 内多会话场景(BRO 说 Cursor 只当人工兜底·不靠它)
  - advisory(建议性) · 永远能 force 过 · 绝不把 OPUS 自己锁死
"""

from __future__ import annotations

import hashlib
import threading
import time

# 锁有效期(秒)。 超过这个时长没刷新的锁视为过期——上一个对话大概率早收尾了。
TTL_SECONDS = 180.0

_LOCK = threading.Lock()
# path(绝对路径 str) -> {"owner": str, "ts": float, "hash": str, "tool": str}
_REGISTRY: dict[str, dict] = {}


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


def _fmt_ago(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 60:
        return f"{s} 秒"
    return f"{s // 60} 分 {s % 60} 秒"


def _short(owner: str) -> str:
    """session id 可能是长 uuid · 给提示文案用前 8 位就够认。"""
    return owner[:8] if owner else "?"


def _prune(now: float) -> None:
    """删过期锁(调用方必须已持 _LOCK)。"""
    dead = [k for k, v in _REGISTRY.items() if now - v.get("ts", 0) > TTL_SECONDS]
    for k in dead:
        _REGISTRY.pop(k, None)


def guard(
    path: str,
    owner: str,
    current_text: str,
    *,
    force: bool = False,
    tool: str = "edit",
) -> tuple[bool, str | None]:
    """写盘【前】问一句能不能改。

    Args:
        path: 目标文件绝对路径
        owner: 当前对话身份(session id · 见 agent_tools.current_session_id)
        current_text: 磁盘当前内容(调用方刚读到的·用来算指纹)
        force: True = 强行接管(用户确认过不冲突) · 跳过两道软提示
        tool: 调用来源标签(给冲突文案用·如 'edit_file' / 'write_file:overwrite')

    Returns:
        (ok, msg):
          ok=False → 撞软锁了 · msg 是给 LLM 看的"排队/防覆盖"提示(返回为 ToolResult.error)
          ok=True  → 放行 · 已登记/刷新锁 · msg 可能是"已强行接管"的提示(拼进 output)·或 None

    写盘【成功后】记得调 note_write() 把锁刷新到新内容的指纹。
    """
    now = time.time()
    cur_hash = _sha(current_text)
    with _LOCK:
        _prune(now)
        existing = _REGISTRY.get(path)

        if existing and not force:
            # 道 1: 另一个对话 TTL 内持锁 → 排队软提示
            if existing.get("owner") != owner and (now - existing.get("ts", 0)) < TTL_SECONDS:
                from identity import localize_narration as _ln
                return False, _ln(
                    f"⚠️ 编辑锁冲突：这个文件 {_fmt_ago(now - existing['ts'])}前正被【另一个对话】"
                    f"(session {_short(existing['owner'])} · 用 {existing.get('tool', '?')})改，"
                    "它可能还没收尾。\n"
                    "为避免你俩互相覆盖，最好等它弄完——可以先去做别的、或问 BRO 那边是不是在改这个文件。\n"
                    "→ 如果确认现在就要改（那个对话已经停了 / 你确定改的不是同一段），"
                    "再调一次本工具并带 force=true。"
                )
            # 道 2: 指纹防覆盖——磁盘自上次被工具改过后又变了(外部/Cursor/另一对话)
            if existing.get("hash") and existing["hash"] != cur_hash:
                return False, (
                    f"⚠️ 防覆盖：这个文件自上次被工具改过后，磁盘内容又变了"
                    f"（最近一次工具改动记录在 {_fmt_ago(now - existing['ts'])}前，"
                    "之后被某个对话 / Cursor / 外部程序动过）。\n"
                    "你现在直接写会盖掉那次改动。\n"
                    "→ 先 read_file 重新看一眼当前内容确认无误，再带 force=true 写；"
                    "大文件请改用 edit_file 局部替换，别整文件覆盖。"
                )

        # 放行 · 登记/刷新锁(临时记当前磁盘指纹·写成功后由 note_write 覆盖成新指纹)
        takeover = None
        if existing and existing.get("owner") != owner and force:
            takeover = (
                f"(已强行接管编辑锁 · 该文件 {_fmt_ago(now - existing['ts'])}前"
                f"由另一个对话 session {_short(existing['owner'])} 持有)"
            )
        _REGISTRY[path] = {"owner": owner, "ts": now, "hash": cur_hash, "tool": tool}
        return True, takeover


def note_write(path: str, owner: str, new_text: str, tool: str = "edit") -> None:
    """写盘成功后调 · 把锁刷新到新内容的指纹(让同一对话连续编辑不误报)。"""
    now = time.time()
    with _LOCK:
        _REGISTRY[path] = {"owner": owner, "ts": now, "hash": _sha(new_text), "tool": tool}


def release(path: str, owner: str) -> None:
    """主动释放锁(可选 · 任务收尾时用)。 只能释放自己持的。"""
    with _LOCK:
        e = _REGISTRY.get(path)
        if e and e.get("owner") == owner:
            _REGISTRY.pop(path, None)


def snapshot() -> dict[str, dict]:
    """调试用 · 返当前锁表副本。"""
    with _LOCK:
        return {k: dict(v) for k, v in _REGISTRY.items()}
