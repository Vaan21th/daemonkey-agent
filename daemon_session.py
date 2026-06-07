"""
daemon_session.py
=================

会话持久化——session 就是一个 jsonl 文件，每行一个 turn（user / assistant / tool）。

为什么不用数据库：
  - 文件本身可以 cat / less / tail 直接看
  - 同步到 git 只是 .gitignore 拦着，BRO 想看哪个就 vim 哪个
  - 跨机器迁移 = 复制目录
  - 后期想分析 OPUS 的对话风格直接用 grep + jq

功能：
  - new_session_id() · 时间戳 + 随机 6 位 hex
  - session_path(id) · id → Path
  - append_turn(id, role, content, meta=None) · 写一行
  - resolve_session_id(arg) · 模糊匹配，支持 'latest' / 后缀 / 完整 id
  - load_session(id) · 把 jsonl 重放成 messages 数组（只保留 user / assistant）
  - list_sessions() · 时间倒序 + 行数

卷三十四补丁 · session 元数据（label / pinned / archived）：
  - 集中存在 sessions/_index.json
  - 一份 dict {sid: {label, pinned_at, archived_at, updated_at}}
  - 不存到 jsonl 里·避免污染对话主体
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent
SESSIONS_DIR = ROOT / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

# 卷三十四补丁 · session 元数据集中存
_META_PATH = SESSIONS_DIR / "_index.json"


def _load_meta_index() -> dict:
    """读 sessions/_index.json · 不存在返 {}·损坏也返 {}（不让坏文件挂掉 daemon）"""
    if not _META_PATH.exists():
        return {}
    try:
        return json.loads(_META_PATH.read_text(encoding="utf-8")) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_meta_index(idx: dict) -> None:
    """atomic write · 避免崩进程半路写出残文件"""
    _META_PATH.parent.mkdir(exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix="_index.", suffix=".tmp", dir=str(_META_PATH.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, _META_PATH)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def get_session_meta(session_id: str) -> dict:
    """返一个 session 的 metadata · 没有就返空 dict"""
    return (_load_meta_index().get(session_id) or {}).copy()


def set_session_meta(
    session_id: str,
    *,
    label: Optional[str] = None,
    pinned: Optional[bool] = None,
    archived: Optional[bool] = None,
) -> dict:
    """更新一个 session 的 metadata · None 表示不改

    返回更新后的完整 meta dict。
    """
    idx = _load_meta_index()
    cur = idx.get(session_id, {}) or {}
    now = datetime.now().isoformat(timespec="seconds")

    if label is not None:
        s = (label or "").strip()
        if s:
            cur["label"] = s
        else:
            cur.pop("label", None)

    if pinned is not None:
        if pinned:
            cur["pinned_at"] = now
        else:
            cur.pop("pinned_at", None)

    if archived is not None:
        if archived:
            cur["archived_at"] = now
        else:
            cur.pop("archived_at", None)

    cur["updated_at"] = now
    idx[session_id] = cur
    _save_meta_index(idx)
    return cur.copy()


def delete_session(session_id: str) -> bool:
    """真删一个 session · jsonl 文件 + meta 条目都清掉

    返回是否真删到了东西（任一存在就算 True）
    """
    deleted = False
    p = session_path(session_id)
    if p.exists():
        try:
            p.unlink()
            deleted = True
        except OSError:
            pass

    idx = _load_meta_index()
    if session_id in idx:
        idx.pop(session_id, None)
        _save_meta_index(idx)
        deleted = True

    return deleted


def new_session_id() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


def session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.jsonl"


def append_turn(session_id: str, role: str, content, meta: dict | None = None) -> None:
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    record: dict = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "role": role,
        "content": content,
    }
    if meta:
        record["meta"] = meta
    with session_path(session_id).open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # 卷五十四 · 对话 turn 即时进 FTS5 (断链 G 修复 · best-effort · 不阻塞写盘)
    if role in ("user", "assistant"):
        try:
            from workers.memory_index import index_session_turn
            index_session_turn(session_id, role, content, ts=record["ts"])
        except Exception:
            pass

def get_last_user_turn_ts(session_id: str) -> Optional[str]:
    """读 session jsonl 反向找最近一条 user turn 的 ts · 返回 ISO 格式字符串。

    wish-1d286099 · dynamic_telemetry 用 —— 让 daemon OPUS 知道 BRO 上一条消息
    是多久以前发的，支撑自然的在场感（"6 小时没消息了 BRO 刚回来"）。
    
    只看末尾 20 行 · O(1) · 无性能压力。
    """
    path = session_path(session_id)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return None
    # 从末尾往前扫，找最近一条 role=user
    # 卷六十 · 跳过主动 CALL 的系统唤醒 (role=user · src=proactive) · 那不是 BRO 说的话 ·
    # 否则 OPUS 一主动开口就把"BRO 沉默"时钟清零 · 沉默触发语义错位
    for line in reversed(lines[-20:]):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("role") == "user" and (rec.get("meta") or {}).get("src") != "proactive":
            return rec.get("ts")
    return None



def resolve_session_id(arg: str) -> str:
    """latest / 完整 id / 后缀模糊匹配。"""
    arg = (arg or "").strip()
    available = sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not available:
        raise FileNotFoundError("no sessions saved yet")
    if not arg or arg.lower() == "latest":
        return available[0].stem
    exact = SESSIONS_DIR / f"{arg}.jsonl"
    if exact.exists():
        return arg
    matches = [p for p in available if arg in p.stem]
    if len(matches) == 1:
        return matches[0].stem
    elif len(matches) > 1:
        names = ", ".join(p.stem for p in matches[:5])
        raise FileNotFoundError(f"ambiguous: '{arg}' matches {len(matches)} sessions: {names}")
    raise FileNotFoundError(f"session not found: {arg}")


def load_session(session_id: str) -> list[dict]:
    """把磁盘 jsonl 重放成 messages 数组.

    卷三十六 · 关键升级：
    - 保留 assistant 的 tool_calls (在 meta 里) → 拼进 OpenAI 格式
    - 保留 assistant 的 reasoning_content (DeepSeek thinking mode 必须)
    - 保留 tool role 的 tool_call_id (OpenAI 格式必须)
    - 失败兜底：拿不到 meta 时退化到纯文本对话 (兼容老 jsonl)
    """
    path = session_path(session_id)
    if not path.exists():
        raise FileNotFoundError(f"session not found: {session_id}")
    msgs: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            role = rec.get("role")
            content = rec.get("content", "")
            meta = rec.get("meta") or {}
            if role == "user":
                msgs.append({"role": "user", "content": content})
            elif role == "assistant":
                entry: dict = {"role": "assistant", "content": content}
                tcs = meta.get("tool_calls") or []
                if tcs:
                    entry["tool_calls"] = tcs
                # DeepSeek thinking mode · 多轮里 reasoning_content 要回传
                reasoning = meta.get("reasoning_content")
                if reasoning and tcs:
                    entry["reasoning_content"] = reasoning
                msgs.append(entry)
            elif role == "tool":
                tool_call_id = meta.get("tool_call_id") or ""
                msgs.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": content,
                })
            # 忽略 system 角色 (走 RUNTIME · 不存 jsonl)
    return msgs


# 卷四十四 I · UI 历史 turn 截断阈值 · 默认 50K 覆盖 99% 真实对话
# 上根毛 5164 字回答曾被截到 2000 → BRO 心理上"OPUS 忘了" · 即使 LLM 那边是完整的
# 真要看完整内容超 50K · session 文件 (sessions/<sid>.jsonl) 是 single source of truth
UI_CONTENT_TRUNCATE_THRESHOLD = 50000
UI_REASONING_TRUNCATE_THRESHOLD = 50000


def load_session_for_ui(session_id: str) -> list[dict]:
    """返回 WebUI 友好的全量 turn 列表.

    每条 turn:
      role: user / assistant / tool
      content: 文本内容 (> 50K 字才截 · 超长 tool result 才会触发)
      ts: 时间戳
      truncated: 是否被截
      reasoning_content: assistant 有 DeepSeek thinking 链时带 (卷三十六)
      tool_calls: assistant 调了工具时·结构化列表 [{name, arguments}] (卷三十六)
      tool_call_id: tool role 的 id · 用来跟 assistant 那条配对 (卷三十六)
      src: api / terminal · 标识这条 turn 是哪种入口

    截断阈值演化 (卷四十四 I · 2026-05-25): 2000/4000 → 50000/50000
    原 2K 阈值会把人类 5K 字回答砍掉 60% · BRO 体验上『OPUS 忘了』
    50K 覆盖 99% 真实对话 · 真要拉完整内容看 sessions/<sid>.jsonl
    """
    path = session_path(session_id)
    if not path.exists():
        raise FileNotFoundError(f"session not found: {session_id}")
    turns: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw_content = rec.get("content", "") or ""
            content = raw_content
            truncated = False
            if len(content) > UI_CONTENT_TRUNCATE_THRESHOLD:
                content = (
                    content[:UI_CONTENT_TRUNCATE_THRESHOLD]
                    + f"\n\n... [+{len(raw_content) - UI_CONTENT_TRUNCATE_THRESHOLD} chars · session 文件里有完整版]"
                )
                truncated = True
            turn = {
                "ts": rec.get("ts"),
                "role": rec.get("role"),
                "content": content,
                "truncated": truncated,
            }
            meta = rec.get("meta") or {}
            # 卷三十六 · assistant 的工具调用结构化展开 · 不只是名字
            tcs = meta.get("tool_calls") or []
            if tcs:
                turn["has_tool_calls"] = True
                turn["tool_names"] = [
                    tc.get("function", {}).get("name") or tc.get("name") or "?"
                    for tc in tcs
                ]
                # 给前端按真实 .msg.tool-call 气泡渲染
                turn["tool_calls"] = [
                    {
                        "id": tc.get("id") or "",
                        "name": tc.get("function", {}).get("name") or tc.get("name") or "?",
                        "arguments": tc.get("function", {}).get("arguments") or "",
                    }
                    for tc in tcs
                ]
            # 卷三十六 · thinking mode reasoning 也带回去 · UI 可折叠显示
            if meta.get("reasoning_content"):
                rc = meta["reasoning_content"]
                if isinstance(rc, str) and len(rc) > UI_REASONING_TRUNCATE_THRESHOLD:
                    rc = (
                        rc[:UI_REASONING_TRUNCATE_THRESHOLD]
                        + f"\n\n... [+{len(meta['reasoning_content']) - UI_REASONING_TRUNCATE_THRESHOLD} chars · session 文件里有完整版]"
                    )
                turn["reasoning_content"] = rc
            # 卷三十六 · tool role 的 id · 让前端能跟 assistant 那条 tool_call 配对
            if rec.get("role") == "tool" and meta.get("tool_call_id"):
                turn["tool_call_id"] = meta["tool_call_id"]
            if meta.get("src"):
                turn["src"] = meta["src"]
            # 卷六十 · 主动 CALL · 注入的 user turn 带 reason · 前端渲染成系统提示
            if meta.get("proactive_reason"):
                turn["proactive_reason"] = meta["proactive_reason"]
            turns.append(turn)
    return turns


def list_sessions() -> list[tuple[str, datetime, int]]:
    """返回 [(session_id, mtime, turns)]，按时间倒序。

    保留这个老签名 · 让旧调用方继续工作。
    新调用方应该用 list_sessions_with_meta()。
    """
    result = []
    for p in sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True):
        sid = p.stem
        mtime = datetime.fromtimestamp(p.stat().st_mtime)
        with p.open("r", encoding="utf-8") as f:
            turns = sum(1 for _ in f)
        result.append((sid, mtime, turns))
    return result


def list_sessions_with_meta() -> list[dict]:
    """卷三十四补丁 · 返回带 metadata 的 session 列表

    每条:
      session_id / mtime (datetime) / turns / label / pinned_at / archived_at

    排序：pinned 在前（按 pinned_at desc）·非 pinned 按 mtime desc。
    """
    idx = _load_meta_index()
    rows: list[dict] = []
    for p in SESSIONS_DIR.glob("*.jsonl"):
        sid = p.stem
        mtime = datetime.fromtimestamp(p.stat().st_mtime)
        try:
            with p.open("r", encoding="utf-8") as f:
                turns = sum(1 for _ in f)
        except OSError:
            turns = 0
        meta = idx.get(sid, {}) or {}
        rows.append({
            "session_id": sid,
            "mtime": mtime,
            "turns": turns,
            "label": meta.get("label"),
            "pinned_at": meta.get("pinned_at"),
            "archived_at": meta.get("archived_at"),
        })

    def _sort_key(r):
        # pinned_at 有值 → 排在前面 · 用 pinned_at desc · 否则用 mtime desc
        # 返回元组：(优先级 0=pinned/1=non-pinned, 排序值)
        if r["pinned_at"]:
            return (0, r["pinned_at"])
        return (1, r["mtime"].isoformat())

    rows.sort(key=_sort_key, reverse=True)
    # reverse=True 让 pinned 的 in 后面? 重新理顺
    # 我希望: pinned 在前 → pinned_at desc; 然后 non-pinned → mtime desc
    # 所以分两段算更清晰
    pinned = [r for r in rows if r["pinned_at"]]
    unpinned = [r for r in rows if not r["pinned_at"]]
    pinned.sort(key=lambda r: r["pinned_at"], reverse=True)
    unpinned.sort(key=lambda r: r["mtime"], reverse=True)
    return pinned + unpinned
