"""
workers/feishu_sessions.py · 飞书多会话管理 (wish-a0e7301c · 块 B)

对标 cc-connect core/session.go 的 SessionManager 精简移植:
- 多会话 + JSON 持久化 (data/runtime/feishu_sessions.json)
- userKey 维度: p2p 按 sender open_id (user:<id>) · 群按 chat_id (group:<id>)
- 每个会话映射一个 daemon session sid (api-feishu-<key>-s<N> · api- 前缀是 daemon 校验要求) · _chat_impl 直接传 sid
- 命令层 (/new /list /switch /current) 调用本模块
- 预留 reset_on_idle_mins 空闲自动轮换 (默认关 · 可在 feishu_config.json 配)

设计取舍 (对标 cc-connect 但砍掉不需要的):
- 不存 History (daemon_session 自己存 · 避免双份)
- 不存每会话 provider (我们的 provider 是全局的)
- ActiveProvider / PastAgentSessionIDs 等字段不移植 · 需要时再加
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("opus.feishu")

_STORE_PATH = Path("data/runtime/feishu_sessions.json")
_DEFAULT_NAME = "默认会话"
_TIME_FMT = "%Y-%m-%d %H:%M:%S"


class FeishuSessionManager:
    """飞书多会话管理器 · 每个 userKey 维护一个会话列表 + 当前 active 指针。"""

    def __init__(self, store_path=None, reset_on_idle_mins: int = 0):
        self.store_path = Path(store_path) if store_path else _STORE_PATH
        self.reset_on_idle_mins = reset_on_idle_mins
        self.data: dict = {}  # userKey -> {"active_sid": str, "sessions": [dict]}
        self._counter = 0
        # 并发写保护: 多线程 (飞书消息 3 线程池) 同时 touch/new/_save 会写坏 JSON (2026-08-06 实测 Extra data)
        self._lock = threading.RLock()
        self._load()

    # ── 持久化 ──────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if self.store_path.exists():
                raw = json.loads(self.store_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.data = raw
                    # 恢复序号 counter · 保证新会话 sid 不撞
                    for rec in self.data.values():
                        for s in rec.get("sessions", []):
                            sid = s.get("sid", "")
                            # 恢复序号 counter · 保证新会话 sid 不撞 (兼容旧 feishu- + 新 api-feishu-)
                            if (sid.startswith("api-feishu-") or sid.startswith("feishu-")) and "-s" in sid:
                                try:
                                    n = int(sid.rsplit("-s", 1)[1])
                                    self._counter = max(self._counter, n)
                                except (IndexError, ValueError):
                                    logger.warning("sessions 会话解析失败 (L61)", exc_info=True)
        except Exception as e:
            logger.warning("feishu sessions 加载失败: %s", e)

    def _save(self) -> None:
        try:
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            self.store_path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("feishu sessions 保存失败: %s", e)
    # ── key / sid 构造 ──────────────────────────────────────

    @staticmethod
    def make_key(user_id: str, chat_id: str, is_group: bool) -> str:
        """userKey 维度: p2p 按发送者 open_id · 群按 chat_id (对标 cc-connect sessionKey)。"""
        if is_group:
            return f"group:{chat_id}"
        return f"user:{user_id or chat_id}"

    @staticmethod
    def _sid_for(key: str, n: int) -> str:
        # daemon _chat_impl 校验 session_id 必须以 api- 开头 (daemon_api._resolve_api_session_id)
        safe = key.replace(":", "_").replace("/", "_")
        return f"api-feishu-{safe}-s{n}"

    # ── 会话操作 ────────────────────────────────────────────

    def _record(self, key: str) -> dict:
        return self.data.setdefault(key, {"active_sid": None, "sessions": []})

    def _new_for_key(self, key: str, rec: dict) -> dict:
        with self._lock:
            self._counter += 1
            now = time.strftime(_TIME_FMT)
            s = {
                "sid": self._sid_for(key, self._counter),
                "name": _DEFAULT_NAME,
                "created_at": now,
                "updated_at": now,
                "last_user_activity": now,
                "msg_count": 0,
            }
            rec["sessions"].append(s)
            rec["active_sid"] = s["sid"]
            self._save()
            return s

    def get_or_create(self, key: str) -> dict:
        """取当前 active 会话 · 没有就建一个 (并发安全: 同一 key 不会建重复会话)。"""
        with self._lock:
            rec = self._record(key)
            active = self._find(rec, rec.get("active_sid"))
            if active is None:
                active = self._new_for_key(key, rec)
            return active

    def new_session(self, key: str) -> dict:
        """开新会话 (命令 /new) · 旧会话的 sid 留在列表里可 /switch 回来。"""
        with self._lock:
            rec = self._record(key)
            return self._new_for_key(key, rec)

    def list_sessions(self, key: str) -> list:
        rec = self.data.get(key)
        return rec["sessions"] if rec else []

    def active(self, key: str) -> Optional[dict]:
        rec = self.data.get(key)
        if not rec:
            return None
        return self._find(rec, rec.get("active_sid"))

    def _find(self, rec: dict, sid: Optional[str]) -> Optional[dict]:
        if sid:
            for s in rec.get("sessions", []):
                if s["sid"] == sid:
                    return s
        return None

    def switch(self, key: str, target: str) -> tuple:
        """target: 序号(1-based) / 名称 / sid。返回 (session_or_None, error)。"""
        with self._lock:
            rec = self.data.get(key)
            sessions = rec["sessions"] if rec else []
            if not sessions:
                return None, "还没有会话 · 先发条消息或 /new 建一个"
            if target.isdigit():
                idx = int(target) - 1
                if 0 <= idx < len(sessions):
                    rec["active_sid"] = sessions[idx]["sid"]
                    self._save()
                    return sessions[idx], None
                return None, f"序号 {target} 不存在（共 {len(sessions)} 个）"
            for s in sessions:
                if s["name"] == target or s["sid"] == target:
                    rec["active_sid"] = s["sid"]
                    self._save()
                    return s, None
            return None, f"找不到会话「{target}」"

    def touch(self, key: str) -> None:
        """真实用户消息到达时更新活跃时间 + 计数 (对标 LastUserActivity)。"""
        with self._lock:
            s = self.active(key)
            if s:
                now = time.strftime(_TIME_FMT)
                s["updated_at"] = now
                s["last_user_activity"] = now
                s["msg_count"] = s.get("msg_count", 0) + 1
                self._save()

    # ── 空闲自动轮换 (对标 reset_on_idle_mins · 默认关) ────────

    def maybe_rotate_idle(self, key: str) -> Optional[dict]:
        """当前会话空闲超过 reset_on_idle_mins → 自动开新会话并返回它 (否则 None)。"""
        if self.reset_on_idle_mins <= 0:
            return None
        with self._lock:
            s = self.active(key)
            if not s:
                return None
            last = s.get("last_user_activity") or s.get("created_at") or ""
            try:
                last_ts = time.mktime(time.strptime(last, _TIME_FMT))
            except Exception:
                return None
            if time.time() - last_ts >= self.reset_on_idle_mins * 60:
                rec = self._record(key)
                logger.info("feishu 会话空闲超时自动轮换: %s", key)
                return self._new_for_key(key, rec)
            return None


# ── 与 daemon 本地 session 对齐 (2026-08-06 · 飞书台账 vs sessions/*.jsonl) ──

def prune_empty(store_path=None) -> int:
    """清理空壳会话: 台账里有但 daemon 本地无对应 session 文件 (msg_count==0) 的删掉。

    历史遗留: 早期 /new 建了 sid 为 feishu- 前缀(非法)的会话 · 从没真正创建过本地文件。
    返回清理条数。本地文件在 sessions/<sid>.jsonl。
    """
    mgr = get_manager() if store_path is None else FeishuSessionManager(store_path=store_path)
    sess_dir = Path("sessions")
    removed = 0
    with mgr._lock:
        for ukey, rec in list(mgr.data.items()):
            alive = []
            for s in rec.get("sessions", []):
                sid = s.get("sid", "")
                has_file = (sess_dir / f"{sid}.jsonl").exists() if sid else False
                if not has_file and s.get("msg_count", 0) == 0:
                    removed += 1
                    continue
                alive.append(s)
            rec["sessions"] = alive
            if rec.get("active_sid") and not any(s["sid"] == rec["active_sid"] for s in alive):
                rec["active_sid"] = alive[0]["sid"] if alive else None
            if not alive:
                mgr.data.pop(ukey, None)
        mgr._save()
    return removed


def real_stats(sid: str) -> dict:
    """读 daemon 本地真实数据: {turns, label} (对齐 /list 显示 · 不依赖台账 msg_count)。"""
    turns, label = 0, ""
    try:
        from daemon_session import list_sessions, get_session_meta
        for s, _ts, n in list_sessions():
            if s == sid:
                turns = n
                break
        label = (get_session_meta(sid).get("label") or "") if sid else ""
    except Exception:
        logger.warning("sessions 状态更新失败 (L237)", exc_info=True)
    return {"turns": turns, "label": label}


_manager: Optional[FeishuSessionManager] = None


def get_manager() -> FeishuSessionManager:
    """全局单例 · reset_on_idle_mins 从 feishu_config.json 读 (默认关)。"""
    global _manager
    if _manager is None:
        reset = 0
        try:
            from workers import feishu_client
            cfg = feishu_client.load_config() or {}
            reset = int(cfg.get("reset_on_idle_mins") or 0)
        except Exception:
            logger.warning("sessions 清理失败 (L254)", exc_info=True)
        _manager = FeishuSessionManager(reset_on_idle_mins=reset)
    return _manager
