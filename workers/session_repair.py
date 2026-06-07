"""workers/session_repair.py
==============================

卷四十六 III 补丁 5 · R3 · session 悬空 tool_call 自动检测 + 自愈 · 2026-05-26

为什么需要这个
----------------
OpenAI / Anthropic tool use 协议要求:
  assistant turn: {role: 'assistant', tool_calls: [{id: 'abc', ...}]}
  下一 turn:     {role: 'tool', tool_call_id: 'abc', content: '...'}

如果第二个 turn **不存在** (daemon 在 tool 执行中崩了 / 用户 abort / 网络断在
tool result 写入前) · session jsonl 里就有个『悬空 tool_call』:
  - 下次 _chat_impl 重新载入这个 session · LLM 调用会报 400
    "An assistant message with 'tool_calls' must be followed by tool messages"
  - 表象: BRO 重启后想接着聊 · 一发 message 就 500

历史:
  - 2026-05-26 早晨 OPUS 自己 shell_exec Stop-Process 把 daemon 杀了 · session
    遗留悬空 tool_call · 我 (上根毛) 手动 jsonl 编辑加合成 tool result 救了一次
  - 教训: 不能依赖人工救 · 必须自动化

这一模块做三件事:
  1. **`find_dangling(messages)`**: 扫 messages · 找 assistant.tool_calls.id
     没有对应 tool.tool_call_id 的 · 返回悬空清单
  2. **`synthesize_tool_result(tool_call_id, reason)`**: 合成一条 tool turn
     说明这是 daemon 自愈 · 不是真 tool 跑出来的
  3. **`repair_session(session_id, dry_run=True)`**: 主入口 · 默认 dry_run
     - dry_run=True · 只检测 · log + return 报告
     - dry_run=False · 改 jsonl · 加合成 tool result · 加 backup

设计取舍
----------
- **dry_run default=True**: 第一阶段只检测 · 看清楚有多少悬空 · 再决定要不要
  自动修。 BRO 看 log 后手动跑一次 dry_run=False
- **不删 assistant turn**: 只补 tool result · 不丢用户的对话历史
- **改 jsonl 前先 backup**: 用 safe_write · 自动 timestamp 备份 · 救得回
- **合成的 content 标记 [daemon_self_heal]**: LLM 看得到 · 知道这是补的不是真跑的
- **load_session 不自动触发**: 启动期太微妙 · 让 daemon_lifecycle 在 init 时
  run 一次 dry_run · 报有几个悬空 · BRO 决定要不要修
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_log = logging.getLogger("opus.session_repair")


def find_dangling(messages: list[dict]) -> list[dict]:
    """扫 messages · 找悬空 tool_call

    Args:
        messages: load_session 的输出 · OpenAI 格式 list[dict]

    Returns:
        [{
          "tool_call_id": str,
          "assistant_index": int,   # messages 里的 index
          "name": str,
          "arguments": str,
        }, ...]
    """
    if not isinstance(messages, list):
        return []

    # 第一遍: 收集所有 tool.tool_call_id (已有 result 的)
    resolved_ids: set[str] = set()
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "tool":
            tcid = m.get("tool_call_id")
            if tcid:
                resolved_ids.add(tcid)

    # 第二遍: 找 assistant.tool_calls 里 id 不在 resolved_ids 的
    dangling = []
    for i, m in enumerate(messages):
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        tcs = m.get("tool_calls") or []
        for tc in tcs:
            if not isinstance(tc, dict):
                continue
            tcid = tc.get("id")
            if not tcid or tcid in resolved_ids:
                continue
            fn = tc.get("function") or {}
            dangling.append({
                "tool_call_id": tcid,
                "assistant_index": i,
                "name": fn.get("name") or tc.get("name") or "(unknown)",
                "arguments": fn.get("arguments") or tc.get("arguments") or "",
            })

    return dangling


def synthesize_tool_result(
    tool_call_id: str,
    name: str = "(unknown)",
    reason: str = "daemon 异常退出 · 此 tool 执行结果丢失",
) -> dict:
    """合成一条 tool result turn · OpenAI 格式

    LLM 在下次 turn 会看到这个 content · 知道这是 daemon 自愈补的 · 不是真跑出来的
    """
    payload = {
        "ok": False,
        "self_heal": True,
        "tool_name": name,
        "reason": reason,
        "synthesized_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "[daemon_self_heal] daemon 检测到这个 tool_call 没有对应的执行结果 ·  "
            "通常是 daemon 在 tool 执行中崩了 / 用户 abort / 网络断在落档前。"
            " 系统合成了这条假 result 让对话能继续 · 真实结果丢失。"
            " 如果工具是重要操作 (写文件/发请求/git commit 等) · 建议再跑一遍。"
        ),
    }
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps(payload, ensure_ascii=False, indent=2),
    }


def heal_messages_inplace(messages: list[dict]) -> int:
    """在内存里给 messages 补上悬空 tool_call 的合成 result · 原地修改 · 返补了几条。

    卷五十五 · 2026-06-03: 这是『发给 LLM 之前』的最后一道自愈闸 (run_tool_loop 入口调)。
    病根: turn 在 tool 执行前被打断 (重启/abort/网断) → 历史里 assistant.tool_calls 没有
    对应 tool result → 下次发给 LLM 报 400 "tool_calls must be followed by tool messages"
    → BRO 重启后一发消息就 500 · 续场 background turn 也撞同一颗雷静默死掉。

    跟 repair_session 的区别:
      - repair_session = 改磁盘 jsonl (持久 · 要 backup · 启动期手动跑)
      - 本函数 = 纯内存 · 不碰文件 · 对健康 session 是 no-op · 每次 LLM 调用前都跑得起

    合成 result 必须紧跟在悬空 assistant turn 之后 (OpenAI 协议要求位置) ·
    所以按 assistant_index 倒序插入 · 避免前面的插入打乱后面 turn 的 index。
    """
    if not isinstance(messages, list):
        return 0
    dangling = find_dangling(messages)
    if not dangling:
        return 0
    for d in sorted(dangling, key=lambda x: x["assistant_index"], reverse=True):
        synth = synthesize_tool_result(d["tool_call_id"], d.get("name") or "(unknown)")
        messages.insert(d["assistant_index"] + 1, synth)
    return len(dangling)


def remove_orphan_tool_results(messages: list[dict]) -> int:
    """删掉孤儿 tool result · 原地修改 · 返删了几条。

    卷五十五 · 2026-06-03 · P3: 这是悬空 tool_call 的『镜像病』。
    病根: assistant turn 丢了 / 历史被截断 / 手工编辑出错 → 留下 role=tool 但它对应的
    tool_call 不在它之前的任何 assistant 里 → LLM 报 400 "tool message must be a
    response to a preceding tool_call"。 悬空 (有 call 没 result) 能补合成 result · 但
    孤儿 (有 result 没 call) 没法补 call (会改写历史语义) · 只能丢。

    判据从严: 只删『它之前没有任何 assistant.tool_calls 声明过这个 id』的 tool turn ·
    保证不误删正常 result。 对健康 session 是 no-op。
    """
    if not isinstance(messages, list):
        return 0
    seen_call_ids: set[str] = set()
    keep: list[dict] = []
    removed = 0
    for m in messages:
        if not isinstance(m, dict):
            keep.append(m)
            continue
        role = m.get("role")
        if role == "assistant":
            for tc in (m.get("tool_calls") or []):
                if isinstance(tc, dict) and tc.get("id"):
                    seen_call_ids.add(tc["id"])
            keep.append(m)
        elif role == "tool":
            tcid = m.get("tool_call_id")
            if tcid and tcid in seen_call_ids:
                keep.append(m)
            else:
                removed += 1  # 孤儿 · 它前面没有对应的 tool_call · 丢
        else:
            keep.append(m)
    if removed:
        messages[:] = keep  # 原地替换内容 · 保持同一个 list 对象 (调用方持有引用)
    return removed


def sanitize_messages_inplace(messages: list[dict]) -> dict:
    """发给 LLM 前的会话结构体检 · 原地修复所有会触发 API 400 的结构病 · 返报告。

    卷五十五 · 2026-06-03 · P3: 把 heal (只补悬空 tool_call) 扩成完整体检 ·
    run_tool_loop 入口调。 两类镜像病都治:
      ① 孤儿 tool result (有 result 没 call) → 删 (remove_orphan_tool_results)
      ② 悬空 tool_call   (有 call 没 result) → 补合成 result (heal_messages_inplace)
    先删孤儿再补悬空 (孤儿的 id 不会被误当成已解析)。 对健康 session 全程 no-op ·
    每次 LLM 调用前都跑得起 · 纯内存不碰文件。

    返 {"orphans_removed": int, "dangling_healed": int}
    """
    if not isinstance(messages, list):
        return {"orphans_removed": 0, "dangling_healed": 0}
    orphans = remove_orphan_tool_results(messages)
    healed = heal_messages_inplace(messages)
    return {"orphans_removed": orphans, "dangling_healed": healed}


def repair_session(
    session_id: str,
    *,
    dry_run: bool = True,
    sessions_dir: Optional[Path] = None,
) -> dict:
    """主入口 · 检测 + (可选) 自愈一个 session

    Args:
        session_id: 例 'aaff8c0c-...' · 不含 .jsonl 后缀
        dry_run: True (default) · 只检测 + log · 不改文件
                 False · 真改 jsonl · 用 safe_write 自动备份
        sessions_dir: 默认 ROOT / 'sessions' · 测试用

    Returns:
        {
          "session_id": str,
          "dry_run": bool,
          "ok": bool,
          "dangling_count": int,
          "dangling": [...],
          "repair_applied": bool,
          "backup": Optional[str],  # dry_run=False 时的 backup 路径
          "error": Optional[str],
        }
    """
    from daemon_session import load_session, session_path

    if sessions_dir is None:
        sp = session_path(session_id)
    else:
        sp = sessions_dir / f"{session_id}.jsonl"

    result = {
        "session_id": session_id,
        "dry_run": dry_run,
        "ok": True,
        "dangling_count": 0,
        "dangling": [],
        "repair_applied": False,
        "backup": None,
        "error": None,
    }

    if not sp.exists():
        result["ok"] = False
        result["error"] = f"session 文件不存在: {sp}"
        return result

    try:
        messages = load_session(session_id) if sessions_dir is None else _load_jsonl(sp)
    except Exception as e:
        result["ok"] = False
        result["error"] = f"load_session 失败: {type(e).__name__}: {e}"
        return result

    dangling = find_dangling(messages)
    result["dangling_count"] = len(dangling)
    result["dangling"] = dangling

    if not dangling:
        _log.info("session %s 健康 · 0 悬空 tool_call", session_id)
        return result

    _log.warning(
        "session %s 检测到 %d 个悬空 tool_call: %s",
        session_id, len(dangling),
        [f"{d['name']}({d['tool_call_id'][:8]})" for d in dangling],
    )

    if dry_run:
        return result

    # 真修: 读原 jsonl + 在每个悬空 assistant turn 之后插入合成 tool result
    try:
        from workers.safe_write import atomic_write_text
    except ImportError:
        result["ok"] = False
        result["error"] = "workers.safe_write 不可用 · 不修"
        return result

    # 直接读 jsonl 行 · 然后按 assistant_index 找到对应行 · 在它之后插入
    raw_lines = sp.read_text(encoding="utf-8").splitlines()

    # messages index → raw lines index 的映射不一定 1:1 (因为 system message
    # 也可能在 jsonl 里? 看 load_session 是 ignore system 的)
    # 安全做法: 重新扫 raw_lines · 同样的算法找悬空 tool_call · 找到对应行的 index
    # 然后在该行 raw_lines 之后插入合成 tool result 的 JSONL 行
    insert_after_indices: list[tuple[int, str]] = []

    # 重新扫 raw 找悬空 + 行 index
    resolved_in_raw: set[str] = set()
    for raw in raw_lines:
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except Exception:
            continue
        if rec.get("role") == "tool":
            tcid = (rec.get("meta") or {}).get("tool_call_id")
            if tcid:
                resolved_in_raw.add(tcid)

    for line_idx, raw in enumerate(raw_lines):
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except Exception:
            continue
        if rec.get("role") != "assistant":
            continue
        tcs = (rec.get("meta") or {}).get("tool_calls") or []
        for tc in tcs:
            tcid = tc.get("id")
            if not tcid or tcid in resolved_in_raw:
                continue
            fn = tc.get("function") or {}
            name = fn.get("name") or tc.get("name") or "(unknown)"
            # 合成 jsonl 行 (跟 append_turn 的格式一致)
            synth_rec = {
                "role": "tool",
                "content": synthesize_tool_result(tcid, name)["content"],
                "ts": datetime.now(timezone.utc).isoformat(),
                "meta": {
                    "src": "session_repair",
                    "tool_call_id": tcid,
                    "self_heal": True,
                },
            }
            synth_line = json.dumps(synth_rec, ensure_ascii=False)
            insert_after_indices.append((line_idx, synth_line))

    if not insert_after_indices:
        return result

    # 按 line_idx 倒序插入 · 避免改一处影响下一处的 idx
    new_raw = list(raw_lines)
    insert_after_indices.sort(key=lambda x: x[0], reverse=True)
    for line_idx, synth_line in insert_after_indices:
        new_raw.insert(line_idx + 1, synth_line)

    new_text = "\n".join(new_raw) + ("\n" if raw_lines and raw_lines[-1] != "" else "")
    write_res = atomic_write_text(sp, new_text, backup=True)
    result["repair_applied"] = True
    result["backup"] = write_res.get("backup")

    _log.warning(
        "session %s 已自愈 · 加了 %d 条合成 tool result · backup=%s",
        session_id, len(insert_after_indices), write_res.get("backup"),
    )
    return result


def _load_jsonl(path: Path) -> list[dict]:
    """简化版 load_session · 测试用 · 不依赖 daemon_session 模块"""
    msgs = []
    if not path.exists():
        return msgs
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except Exception:
            continue
        role = rec.get("role")
        content = rec.get("content", "")
        meta = rec.get("meta") or {}
        if role == "user":
            msgs.append({"role": "user", "content": content})
        elif role == "assistant":
            entry = {"role": "assistant", "content": content}
            tcs = meta.get("tool_calls") or []
            if tcs:
                entry["tool_calls"] = tcs
            msgs.append(entry)
        elif role == "tool":
            msgs.append({
                "role": "tool",
                "tool_call_id": meta.get("tool_call_id", ""),
                "content": content,
            })
    return msgs


__all__ = [
    "find_dangling",
    "synthesize_tool_result",
    "heal_messages_inplace",
    "remove_orphan_tool_results",
    "sanitize_messages_inplace",
    "repair_session",
]
