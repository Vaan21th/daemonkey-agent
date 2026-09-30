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
import re
import tempfile
import threading
import time
import uuid
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent
SESSIONS_DIR = ROOT / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

# 卷三十四补丁 · session 元数据集中存
_META_PATH = SESSIONS_DIR / "_index.json"
_META_LOCK = threading.Lock()  # B-② · 2026-08-27 · index RMW 原子 · 并发改不同 session 不丢更新 (Grok 全量审计)
_RESTORE_FENCE: set[str] = set()
_RESTORE_FENCE_LOCK = threading.Lock()


def set_restore_fence(session_id: str, on: bool) -> None:
    """回退期间拦住 append / 压缩重写，避免截断后又被写回去。"""
    sid = str(session_id or "")
    if not sid:
        return
    with _RESTORE_FENCE_LOCK:
        if on:
            _RESTORE_FENCE.add(sid)
        else:
            _RESTORE_FENCE.discard(sid)


def is_restore_fenced(session_id: str) -> bool:
    sid = str(session_id or "")
    if not sid:
        return False
    with _RESTORE_FENCE_LOCK:
        return sid in _RESTORE_FENCE


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
    last_model_cfg: Optional[str] = None,
    last_think_cfg: Optional[dict] = None,
    last_tool_profile: Optional[str] = None,
    working_docs: Optional[list] = None,
    project_id: Optional[str] = None,
) -> dict:
    """更新一个 session 的 metadata · None 表示不改

    返回更新后的完整 meta dict。
    """
    with _META_LOCK:  # B-② · 读-改-写整段持锁 · 挂稿和改名不能互踩
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

        if last_model_cfg is not None:
            s = (last_model_cfg or "").strip()
            if s:
                cur["last_model_cfg"] = s
            else:
                cur.pop("last_model_cfg", None)

        # wish-00490c86 · 思考开关跟对话实例走（以前存 localStorage 全局键 · B 关思考会串到 A）
        if last_think_cfg is not None:
            cfg = {k: v for k, v in (last_think_cfg or {}).items() if v not in (None, "")}
            if cfg:
                cur["last_think_cfg"] = cfg
            else:
                cur.pop("last_think_cfg", None)

        # wish-16fa5930 · 档位跟对话实例走（一场一种厚度 · 开跑即锁）
        if last_tool_profile is not None:
            s = (last_tool_profile or "").strip()
            if s:
                cur["last_tool_profile"] = s
            else:
                cur.pop("last_tool_profile", None)

        if working_docs is not None:
            cur["working_docs"] = list(working_docs)

        # wish-acc37841 · 这个会话挂在哪个外部项目（"我的项目"的外键）
        # ⚠ 语义跟 label / last_tool_profile 一致：None = 不改 · 空串 = 摘掉项目归属
        #   （不能写 None —— None 在这条通道里是"不更新"，会静默不生效 · 2026-09-16 踩过）
        if project_id is not None:
            s = (project_id or "").strip()
            if s:
                cur["project_id"] = s
            else:
                cur.pop("project_id", None)

        cur["updated_at"] = now
        idx[session_id] = cur
        _save_meta_index(idx)
        return cur.copy()


def delete_session(session_id: str) -> bool:
    """真删一个 session · jsonl + 压缩摘要 + meta 条目 + 召回索引 全部清掉

    返回是否真删到了东西（任一存在就算 True）

    摘要和索引也必须清: 只删 jsonl 的话 · 已删对话还能被 recall_memory 搜出来 ·
    而且留着的 <sid>.summary.json 会在下次全量重建时把它重新索引回来 —— 等于删不掉。
    """
    deleted = False
    p = session_path(session_id)
    if p.exists():
        try:
            p.unlink()
            deleted = True
        except OSError:
            pass

    summary = SESSIONS_DIR / f"{session_id}.summary.json"
    if summary.exists():
        try:
            summary.unlink()
            deleted = True
        except OSError:
            pass

    idx = _load_meta_index()
    if session_id in idx:
        idx.pop(session_id, None)
        _save_meta_index(idx)
        deleted = True

    try:
        from workers.memory_index import purge_session
        purge_session(session_id)
    except Exception:
        pass      # 索引清不掉不该让"删会话"整体失败 · 下次全量重建会兜住

    return deleted


def new_session_id() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


_SAFE_SID_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def session_path(session_id: str) -> Path:
    sid = str(session_id or "")
    if not _SAFE_SID_RE.match(sid):
        # 防路径穿越 (B5 · 2026-08-27): 非法 sid (含 / \ 或空白等) 映射到必然不存在的
        # _rejected_ 路径 · 读写都落在 sessions/ 内 · 调用方看到的是 404/空 · 不会穿出目录
        sid = "_rejected_" + hashlib.sha1(sid.encode("utf-8", "replace")).hexdigest()[:16]
    return SESSIONS_DIR / f"{sid}.jsonl"


def append_turn(session_id: str, role: str, content, meta: dict | None = None) -> None:
    if is_restore_fenced(session_id):
        return
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    record: dict = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "role": role,
        "content": content,
    }
    if meta:
        record["meta"] = meta
    # 社区 7/31 · Bug #7 · open("a") 被 Defender 瞬态锁 → 带重试打开
    try:
        from workers.safe_write import robust_open_append
        _open_append = robust_open_append
    except ImportError:
        _open_append = lambda p: p.open("a", encoding="utf-8")
    with _open_append(session_path(session_id)) as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # 卷五十四 · 对话 turn 即时进 FTS5 (断链 G 修复 · best-effort · 不阻塞写盘)
    if role in ("user", "assistant"):
        try:
            from workers.memory_index import index_session_turn
            index_session_turn(session_id, role, content, ts=record["ts"])
        except Exception:
            pass


def rewrite_session(session_id: str, messages: list[dict]) -> None:
    """v2 · 压缩/修剪后整本重写 session jsonl (wish-7f0adf2c · 治重启蒸发)。

    load_session 的逆变换: assistant 的 tool_calls/reasoning_content 进 meta ·
    tool 的 tool_call_id 进 meta · system 不存。原件已在 sessions/archive/ · 此写不丢数据。

    原记录 ts 尽量复用 (role+content 完全相等 → 保持 UI 时间线) · 内容被 prune 替换的
    tool 消息匹配不到 → 用当前时间 (可接受)。tmp + os.replace 原子写。
    """
    path = session_path(session_id)
    if is_restore_fenced(session_id):
        return
    old_ts: dict = {}
    old_user_tids: list[tuple[str, str]] = []
    old_user_extra: list[tuple[str, dict]] = []
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    rec = json.loads(line)
                    key = (rec.get("role"), rec.get("content"))
                    old_ts.setdefault(key, rec.get("ts"))
                    if rec.get("role") == "user":
                        um = rec.get("meta") or {}
                        tid = um.get("turn_id") or ""
                        if tid:
                            old_user_tids.append((rec.get("content") or "", tid))
                        old_user_extra.append((tid, um))
        except (OSError, json.JSONDecodeError):
            old_ts = {}
            old_user_tids = []
            old_user_extra = []

    now = datetime.now().isoformat(timespec="seconds")
    records: list[dict] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role == "system":
            continue  # system 不存 (走 RUNTIME)
        content = m.get("content")
        if content is None:
            content = ""
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        rec: dict = {
            "ts": old_ts.get((role, content), now),
            "role": role,
            "content": content,
        }
        # v3 (wish-273d3d3f) · 被折叠进摘要的原话标记。
        # 磁盘留全量(可回溯/UI 显示), load_session 跳过(不回放给 LLM),
        # load_session_for_ui 带回给前端渲染「已折叠」提示。
        # 注: 内容未变 → (role, content) 仍能匹配到旧 ts · 时间线不塌。
        if m.get("compacted"):
            rec["compacted"] = True
        meta: dict = {}
        if role == "user":
            mm = m.get("meta") if isinstance(m.get("meta"), dict) else {}
            tid = str(mm.get("turn_id") or m.get("turn_id") or "")
            if not tid:
                for i, (c, t) in enumerate(old_user_tids):
                    if c == content:
                        tid = t
                        old_user_tids.pop(i)
                        break
            if tid:
                meta["turn_id"] = tid
            old_m = {}
            if tid:
                for i, (t, om) in enumerate(old_user_extra):
                    if t == tid:
                        old_m = om
                        old_user_extra.pop(i)
                        break
            if old_m.get("attachments"):
                meta["attachments"] = old_m["attachments"]
            if old_m.get("attach_prompt"):
                meta["attach_prompt"] = old_m["attach_prompt"]
            from workers.attach_prompt import extract_prompt, for_ui
            if (content or "").lstrip().startswith("[用户上传了"):
                if not meta.get("attach_prompt"):
                    p = extract_prompt(content)
                    if p:
                        meta["attach_prompt"] = p
                content = for_ui(content)
                rec["content"] = content
        elif role == "assistant":
            if m.get("tool_calls"):
                # 2026-09-19 · 写盘闸: jsonl 里永远只落标准形态 (type + function 包装)
                meta["tool_calls"] = _normalize_tool_calls(m["tool_calls"])
            if m.get("reasoning_content"):
                meta["reasoning_content"] = m["reasoning_content"]
        elif role == "tool":
            if m.get("tool_call_id"):
                meta["tool_call_id"] = m["tool_call_id"]
        if meta:
            rec["meta"] = meta
        records.append(rec)

    # 原子写 · 复用 append_turn 的 Defender 抗锁思路 (tmp + os.replace)
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=".rewrite.", suffix=".tmp", dir=str(SESSIONS_DIR)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

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



def derive_label_from_first_turn(session_id: str, max_chars: int = 24) -> Optional[str]:
    """从 session 第一条真人 user turn 抽个标签(前 ~24 字)· 给没 label 的老会话补名用。

    只扫前 ~40 行找第一条 role=user 且非 proactive(系统唤醒不算)的 · 规则跟
    daemon_api 新会话即时命名完全一致。找不到(空会话 / 全是系统唤醒)返回 None。
    """
    path = session_path(session_id)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 40:
                    break
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("role") != "user":
                    continue
                if (rec.get("meta") or {}).get("src") == "proactive":
                    continue
                txt = " ".join((rec.get("content") or "").split())
                if not txt:
                    continue
                return txt[:max_chars] + ("…" if len(txt) > max_chars else "")
    except OSError:
        return None
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


def load_session(session_id: str, *, include_compacted: bool = False) -> list[dict]:
    """把磁盘 jsonl 重放成 messages 数组.

    include_compacted=True = 【存储形态】(连折叠原话一起回放) · 只给"要写回 jsonl"
    的调用方用 (见 load_session_for_storage)。默认 False = 发给 LLM 的折叠版。

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
        _recs = [json.loads(_l) for _l in f if _l.strip()]
    # v3 (wish-273d3d3f) · 磁盘行里标了 compacted 的原话不回放给 LLM (摘要那条仍在
    # messages 里 · 语义完整), 但必须【成组跳过】: assistant(tool_calls) 被折叠时,
    # 配对的 tool 结果要一起跳 —— 否则 tool_call_id 悬空 → OpenAI/DeepSeek 400
    # → 会话直接打不开。
    _dropped_tc: set[str] = set()
    for _r in _recs:
        if _r.get("compacted"):
            for _tc in ((_r.get("meta") or {}).get("tool_calls") or []):
                if isinstance(_tc, dict) and _tc.get("id"):
                    _dropped_tc.add(_tc["id"])
    # v3 · 反方向: 被折叠的 tool 记录 → 要摘掉 assistant 那边对应的 tool_call。
    # 否则 assistant 带着 tool_calls 却没有配对 tool 回放 → 同样 400。
    _dropped_result_ids: set[str] = set()
    for _r in _recs:
        if _r.get("compacted") and _r.get("role") == "tool":
            _tid = (_r.get("meta") or {}).get("tool_call_id")
            if _tid:
                _dropped_result_ids.add(_tid)
    _skip_folded = not include_compacted
    for rec in _recs:
        if _skip_folded and rec.get("compacted"):
            continue
        if _skip_folded and rec.get("role") == "tool" and (rec.get("meta") or {}).get("tool_call_id") in _dropped_tc:
            continue
        role = rec.get("role")
        content = rec.get("content", "")
        meta = rec.get("meta") or {}
        if role == "user":
            from workers.attach_prompt import for_llm
            _uentry: dict = {"role": "user", "content": for_llm(content, meta)}
            if include_compacted:
                # wish-e3c3e379 · 存储形态(写盘专用)必须带回 compacted 标记。
                # 写盘路径(_assemble_full_from_disk / _prune_full_from_disk)靠它判
                # 「哪些原话已折走」; 丢了它 → 全量被折叠版顶掉 → 历史被抹。
                _uentry["compacted"] = bool(rec.get("compacted"))
            msgs.append(_uentry)
        elif role == "assistant":
            tcs = meta.get("tool_calls") or []
            # v3 · 反向成组: 配对的 tool 结果若已被折叠(它自己 compacted),
            # 这条 assistant 的对应 tool_call 也要摘掉 — 否则 tool_calls 悬空。
            if _skip_folded and tcs and _dropped_result_ids:
                tcs = [t for t in tcs
                       if not isinstance(t, dict) or t.get("id") not in _dropped_result_ids]
            # 2026-09-19 · 回放闸: 老 jsonl / 被 UI 形态写坏的行里 tool_calls 是短形态
            # {id, name, arguments} → 直接发 API 报 422 missing field `type`。统一补全。
            if tcs:
                tcs = _normalize_tool_calls(tcs)
            if not (content or "").strip() and not tcs:
                # 卷八十四 · 空 content 且无 tool_calls 的 assistant → Kimi/OpenAI 都 400
                # (must not be empty) · 剔除。无 tool_calls 即无配对 tool 消息 · 不会 dangling
                continue
            entry: dict = {"role": "assistant", "content": content}
            if tcs:
                entry["tool_calls"] = tcs
                if not (content or "").strip():
                    # 卷八十四 · DeepSeek 存的 "" 空串 → null (2026-07-28 跨模型切换 500 根治:
                    # Kimi 严格校验只认 null · "" 报 400 must not be empty · 换模型续旧 session 必炸)
                    entry["content"] = None
            # DeepSeek thinking mode · 多轮里 reasoning_content 要回传
            reasoning = meta.get("reasoning_content")
            if reasoning and tcs:
                entry["reasoning_content"] = reasoning
            if include_compacted:
                entry["compacted"] = bool(rec.get("compacted"))
            msgs.append(entry)
        elif role == "tool":
            tool_call_id = meta.get("tool_call_id") or ""
            _tentry: dict = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
            }
            if include_compacted:
                _tentry["compacted"] = bool(rec.get("compacted"))
            msgs.append(_tentry)
        # 忽略 system 角色 (走 RUNTIME · 不存 jsonl)
    return msgs


def _normalize_tool_calls(tcs: list) -> list[dict]:
    """把 tool_calls 归一到 OpenAI 标准形态 {id, type:"function", function:{name, arguments}}。

    为什么需要这道闸 (2026-09-19 事故):
      磁盘 jsonl 里存在历史短形态 {id, name, arguments}(缺 type/function 包装) —— 来源是
      压缩/剪枝落盘时误用了 load_session_for_ui() 的输出(给前端渲染的压扁形态)。
      这种行回放给 DeepSeek 官方 API → 422 "missing field `type`" → 整个会话打不开。

    解法 = 读写两侧各一道: 读侧(load_session)保证喂给 LLM 的永远标准形态,
    写侧(rewrite_session)保证写进 jsonl 的永远标准形态。存量文件无需批量改写。

    幂等: 已是标准形态的 tc 走同一路径重建 · 值不变。
    """
    out: list[dict] = []
    for tc in tcs or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function")
        fn = fn if isinstance(fn, dict) else {}
        name = fn.get("name") or tc.get("name") or ""
        args = fn.get("arguments")
        if args is None:
            args = tc.get("arguments")
        if args is None:
            args = ""
        out.append({
            "id": tc.get("id") or "",
            "type": "function",
            "function": {"name": name, "arguments": args},
        })
    return out


def load_session_for_storage(session_id: str) -> list[dict]:
    """【存储形态】读盘 —— 写盘专用 (磁盘全量版)。

    跟 load_session 的区别: 不跳过 compacted 行 (磁盘要留全量)。
    跟 load_session_for_ui 的区别: 不截断 content/reasoning · 不做 for_ui 转换 ·
      tool_calls 保持标准形态 —— 输出的是"能安全写回 jsonl 的形态"。

    ⚠ 任何【要写盘】的取数必须走本函数 · 禁止拿 load_session_for_ui
      (那个是给前端渲染的有损形态: tool_calls 被压扁 / content 会截断 / meta 不全)。
    """
    return load_session(session_id, include_compacted=True)


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
        for i, line in enumerate(f):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw_content = rec.get("content", "") or ""
            if rec.get("role") == "user":
                from workers.attach_prompt import for_ui
                raw_content = for_ui(raw_content)
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
                "line": i,
            }
            # v3 (wish-273d3d3f) · 原话已被折叠进摘要 (UI 仍完整显示 · 只是标一下)
            if rec.get("compacted"):
                turn["compacted"] = True
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
            # wish-7c579a20 · 附件 meta 透传 · WebUI 历史重建图片/文档卡片
            if meta.get("attachments"):
                turn["attachments"] = meta["attachments"]
            # 卷六十 · 主动 CALL · 注入的 user turn 带 reason · 前端渲染成系统提示
            if meta.get("proactive_reason"):
                turn["proactive_reason"] = meta["proactive_reason"]
            # 0.9.8 · 异步分身完成通报 · 前端渲染成系统通报卡 (不是 user 气泡)
            # 双源: 汇报轮落的带 meta._bg_subagent_report · 老版降级落的在顶层
            if meta.get("_bg_subagent_report") or rec.get("_bg_subagent_report"):
                turn["bg_subagent_report"] = True
            # BRO 2026-07-28 · 顾问协同卡持久化 · 历史渲染重建金卡用
            if meta.get("advisor_blueprint"):
                turn["advisor_blueprint"] = meta["advisor_blueprint"]
            # BRO 2026-07-28 方案 B · 协同自动验收结果 (append-only system 记录) · 历史渲染重建验收卡
            if meta.get("kind") == "advisor_review" and meta.get("advisor_review"):
                turn["advisor_review"] = meta["advisor_review"]
            if rec.get("role") == "user" and meta.get("turn_id"):
                turn["turn_id"] = meta["turn_id"]
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


# 2026-09-15 · turns 数行缓存。列表页每次都要 turns，500+ 个 jsonl 全量重扫代价太大
#   key=sid · value=(mtime, turns) · 文件 mtime 没变就直接命中
#   进程内缓存（重启清空）· 不碰持久化 meta 格式 · 已删 session 留几条死键无妨
#   并发下 dict get/set 在 CPython 是原子的，最坏重算一次，不加锁
_TURNS_CACHE: dict[str, tuple[float, int]] = {}
# 2026-09-16 · wish-3bc2fdaf 续 · 缓存落盘（开机冷盘解药）
#   开机后第一次点「话题列表」要把 553 个 jsonl / 58MB 全读一遍数行 ·
#   热盘 0.43s · 冷盘 + 杀软扫描下冲到 10s+（BRO 报的「一直加载中」）
#   落盘后冷启动只读一个 ~16KB 的 json · 只有 mtime 变过的会话才重算
_TURNS_CACHE_PATH = ROOT / "data" / "runtime" / "session_turns_cache.json"
_TURNS_STATE: dict = {"loaded": False, "dirty": False, "last_save": 0.0}
_TURNS_SAVE_LOCK = threading.Lock()
_TURNS_SAVE_INTERVAL = 30.0  # 秒 · 写盘节流


def _load_turns_cache() -> None:
    """进程内首次用到时从磁盘捞缓存 · 坏文件静默忽略（最坏重算一遍）。"""
    if _TURNS_STATE["loaded"]:
        return
    _TURNS_STATE["loaded"] = True
    try:
        raw = json.loads(_TURNS_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(raw, dict):
        return
    for sid, v in raw.items():
        try:
            if isinstance(v, list) and len(v) == 2:
                _TURNS_CACHE[str(sid)] = (float(v[0]), int(v[1]))
        except (TypeError, ValueError):
            continue


def _save_turns_cache(force: bool = False) -> None:
    """节流落盘（默认 30s 最多一次）· 原子替换 · 任何失败静默不影响列表。"""
    if not force and not _TURNS_STATE["dirty"]:
        return
    now = time.monotonic()
    _last = _TURNS_STATE["last_save"]
    if not force and _last and (now - _last) < _TURNS_SAVE_INTERVAL:
        return   # 只跟「上次真写过」的时刻比 · 0 = 本进程还没写过 → 放行（否则开机 <30s 时首写会被误跳过）
    if not _TURNS_SAVE_LOCK.acquire(blocking=False):
        return   # 另一线程在写 → 跳过这轮（缓存只是加速器·丢一次无害）
    try:
        _TURNS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _TURNS_CACHE_PATH.with_suffix(".json.tmp")
        snap = {k: [v[0], v[1]] for k, v in list(_TURNS_CACHE.items())}
        tmp.write_text(json.dumps(snap), encoding="utf-8")
        os.replace(tmp, _TURNS_CACHE_PATH)
        _TURNS_STATE["dirty"] = False
        _TURNS_STATE["last_save"] = now
    except Exception:   # 写缓存失败永不影响列表（并发迭代 / 磁盘满 / 权限）
        pass
    finally:
        _TURNS_SAVE_LOCK.release()


def _count_turns(p, mtime_ts: float) -> int:
    """数一个 session jsonl 的行数 · 带 mtime 缓存（调用方已 stat 过）。"""
    hit = _TURNS_CACHE.get(p.stem)
    if hit is not None and hit[0] == mtime_ts:
        return hit[1]
    try:
        with p.open("r", encoding="utf-8") as f:
            turns = sum(1 for _ in f)
    except OSError:
        turns = 0
    _TURNS_CACHE[p.stem] = (mtime_ts, turns)
    _TURNS_STATE["dirty"] = True
    return turns


def list_sessions_with_meta() -> list[dict]:
    """卷三十四补丁 · 返回带 metadata 的 session 列表

    每条:
      session_id / mtime (datetime) / turns / label / pinned_at / archived_at

    排序：pinned 在前（按 pinned_at desc）·非 pinned 按 mtime desc。
    """
    idx = _load_meta_index()
    _load_turns_cache()   # 冷启动从磁盘捞 turns 缓存 · 不再 553 个文件全量重读
    rows: list[dict] = []
    for p in SESSIONS_DIR.glob("*.jsonl"):
        sid = p.stem
        try:
            mtime_ts = p.stat().st_mtime   # 只 stat 一次（原来同一文件 stat 两次）
        except OSError:
            continue
        mtime = datetime.fromtimestamp(mtime_ts)
        turns = _count_turns(p, mtime_ts)
        meta = idx.get(sid, {}) or {}
        rows.append({
            "session_id": sid,
            "mtime": mtime,
            "turns": turns,
            "label": meta.get("label"),
            "pinned_at": meta.get("pinned_at"),
            "archived_at": meta.get("archived_at"),
            "last_model_cfg": meta.get("last_model_cfg"),
            "last_think_cfg": meta.get("last_think_cfg") or {},   # wish-00490c86 · 思考开关跟对话实例走（行组装在源头加 · sessions.py 那层拿的是本函数产物）
            "last_tool_profile": meta.get("last_tool_profile"),   # wish-16fa5930 · 档位跟对话实例走
            "project_id": meta.get("project_id"),                # wish-acc37841 · 挂在哪个外部项目
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
    _save_turns_cache()   # 新算出来的 turns 落盘 · 下次冷启动直接命中
    return pinned + unpinned
