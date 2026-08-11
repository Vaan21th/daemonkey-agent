"""
workers/clients.py
==================

通用【客户档案】—— GAP §5.1「客户档案 = 记忆的延伸」的落地存储。

不是冷冰冰的 CRM 表:每个客户是一份档案 · 记他的偏好 / 历次交付复盘 / 上次聊到哪 /
pipeline 阶段。资料(知识库文档)可以挂到某个客户(doc.client_id)· 于是打开客户就能
看到"他所有的资料 + 相关分析"。

存储(全在 data/clients/ · never_sync · 升级绝不覆盖):
  data/clients/manifest.json  · { "clients": { <client_id>: {档案字段} } }

notes 同步进 FTS5(source=client:<id>)· recall_memory(scope='clients'/'all') 能召回 ·
让客户档案真正"长在记忆里"。

设计红线:只动 data/clients/ · 不碰 soul / sessions / 系统目录。
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from workers.safe_write import atomic_write_json, _do_backup

ROOT = Path(__file__).resolve().parent.parent
CLIENTS_DIR = ROOT / "data" / "clients"
MANIFEST_PATH = CLIENTS_DIR / "manifest.json"

CLIENT_SOURCE_PREFIX = "client:"

# wish-a1c5f147 (墨言模块 11) · 复合操作锁: load→改→save 读改写三段·
# 多 session 并行丢更新 → 公开写函数整体持锁
_MANIFEST_LOCK = threading.Lock()

# pipeline 阶段 · lead(线索) → active(在合作) → paused(暂停) → done(结束/交付完)
STATUSES = ("lead", "active", "paused", "done")
# need=当前需求速览 · intent=意向(高/中/低) · quote=报价 · next=下一步动作
_ALLOWED = {"name", "company", "role", "contact", "status", "tags", "notes",
            "need", "intent", "quote", "next"}
_EXTRA_FIELDS = ("need", "intent", "quote", "next")  # 读出时补齐默认空串

# 客户动态时间线的条目类型 · 会议记录/交付过程都靠它归类
#   need=需求 · meeting=会议记录 · progress=进展 · deliver=交付 · note=备注
KINDS = ("need", "meeting", "progress", "deliver", "note")
_KIND_CN = {"need": "需求", "meeting": "会议", "progress": "进展", "deliver": "交付", "note": "备注"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_dir() -> None:
    CLIENTS_DIR.mkdir(parents=True, exist_ok=True)


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {"clients": {}}
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        # wish-a1c5f147 (墨言模块 11) · 损坏 → 先备份现场再返空壳 (防静默覆盖清空)
        try:
            _do_backup(MANIFEST_PATH)
        except Exception:
            pass
        return {"clients": {}}
    if not isinstance(data.get("clients"), dict):
        data["clients"] = {}
    return data


def _save_manifest(data: dict) -> None:
    _ensure_dir()
    # wish-a1c5f147 · 原子写 + 写前备份 (safe_write 复用)
    atomic_write_json(MANIFEST_PATH, data)


def _new_client_id() -> str:
    return "client-" + uuid.uuid4().hex[:8]


def _reindex(client_id: str, meta: dict | None) -> None:
    """把客户档案(名字/公司/需求/备注/时间线)送进 FTS5(source=client:<id>)。

    meta=None 或无实质内容(need/notes/log 全空)→ 撤索引。让 recall_memory(scope='clients')
    与跨客户检索都能命中"聊过啥/需求/会议要点"。
    """
    try:
        from workers.memory_index import incremental_update
    except Exception:
        return
    if not meta:
        try:
            incremental_update(f"{CLIENT_SOURCE_PREFIX}{client_id}", "")
        except Exception:
            pass
        return
    parts = [f"客户档案 · {meta.get('name', '')}"]
    if meta.get("company"):
        parts.append(str(meta["company"]))
    if (meta.get("need") or "").strip():
        parts.append(f"需求: {meta['need']}")
    if (meta.get("notes") or "").strip():
        parts.append(str(meta["notes"]))
    for e in meta.get("log") or []:
        kn = _KIND_CN.get(e.get("kind"), "")
        parts.append(f"[{e.get('date', '')}] {kn} {e.get('text', '')}".strip())
    body = "\n".join(p for p in parts if p and str(p).strip())
    has_content = bool(
        (meta.get("notes") or "").strip()
        or (meta.get("need") or "").strip()
        or (meta.get("log"))
    )
    try:
        incremental_update(f"{CLIENT_SOURCE_PREFIX}{client_id}", body if has_content else "")
    except Exception:
        pass


def resolve_client_id(hint: str) -> str | None:
    """按 id / 名字(精确→模糊)找 client_id · 给 NLP 工具用。"""
    hint = (hint or "").strip()
    if not hint:
        return None
    clients = load_manifest()["clients"]
    if hint in clients:
        return hint
    low = hint.lower()
    for cid, m in clients.items():
        if (m.get("name") or "").lower() == low:
            return cid
    for cid, m in clients.items():
        if low in (m.get("name") or "").lower() or low in (m.get("company") or "").lower():
            return cid
    return None


def add_client(
    name: str,
    *,
    company: str = "",
    role: str = "",
    contact: str = "",
    status: str = "lead",
    tags: list[str] | None = None,
    notes: str = "",
    need: str = "",
    intent: str = "",
    quote: str = "",
    next: str = "",
) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("客户档案需要 name")
    status = status if status in STATUSES else "lead"
    _ensure_dir()
    with _MANIFEST_LOCK:  # wish-a1c5f147 · 复合操作锁
        data = load_manifest()
        cid = _new_client_id()
        meta = {
            "id": cid,
            "name": name,
            "company": (company or "").strip(),
            "role": (role or "").strip(),
            "contact": (contact or "").strip(),
            "status": status,
            "tags": list(tags or []),
            "need": (need or "").strip(),
            "intent": (intent or "").strip(),
            "quote": (quote or "").strip(),
            "next": (next or "").strip(),
            "notes": notes or "",
            "log": [],
            "created_at": _now(),
            "updated_at": _now(),
        }
        data["clients"][cid] = meta
        _save_manifest(data)
    _reindex(cid, meta)
    return meta


def update_client(client_id: str, **changes) -> dict:
    with _MANIFEST_LOCK:  # wish-a1c5f147 · 复合操作锁
        data = load_manifest()
        meta = data["clients"].get(client_id)
        if meta is None:
            raise KeyError(client_id)
        for key, val in changes.items():
            if key not in _ALLOWED or val is None:
                continue
            if key == "status" and val not in STATUSES:
                continue
            meta[key] = val
        meta["updated_at"] = _now()
        _save_manifest(data)
    _reindex(client_id, meta)
    return meta


def append_note(client_id: str, text: str, kind: str = "note") -> dict:
    """往客户时间线 log 追加一条结构化动态(带日期+类型)· 客户档案主要靠这个长厚。

    kind ∈ KINDS(need/meeting/progress/deliver/note)· 非法值回退 note。
    保留旧 notes 字段(历史/导入用)不动·只往 log 追加·永不覆盖既有内容。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("动态内容不能为空")
    kind = kind if kind in KINDS else "note"
    with _MANIFEST_LOCK:  # wish-a1c5f147 · 复合操作锁
        data = load_manifest()
        meta = data["clients"].get(client_id)
        if meta is None:
            raise KeyError(client_id)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entry = {"ts": _now(), "date": stamp, "kind": kind, "text": text}
        log = meta.get("log")
        if not isinstance(log, list):
            log = []
        log.append(entry)
        meta["log"] = log
        meta["updated_at"] = _now()
        _save_manifest(data)
    _reindex(client_id, meta)
    return meta


def remove_client(client_id: str) -> dict:
    with _MANIFEST_LOCK:  # wish-a1c5f147 · 复合操作锁
        data = load_manifest()
        meta = data["clients"].pop(client_id, None)
        if meta is None:
            raise KeyError(client_id)
        _save_manifest(data)
    _reindex(client_id, None)  # 撤索引
    return meta


def _norm_read(meta: dict | None) -> dict | None:
    """读出时补齐新字段(log/need)默认值 · 只补内存不落盘 · 老档案照样能显示。"""
    if meta is None:
        return None
    if "log" not in meta or not isinstance(meta.get("log"), list):
        meta["log"] = []
    for f in _EXTRA_FIELDS:
        if f not in meta:
            meta[f] = ""
    return meta


def get_client(client_id: str) -> dict | None:
    return _norm_read(load_manifest()["clients"].get(client_id))


def list_clients() -> list[dict]:
    """列全部客户 · 活跃的排前面 · 再按更新时间倒序。"""
    order = {"active": 0, "lead": 1, "paused": 2, "done": 3}
    clients = [_norm_read(c) for c in load_manifest()["clients"].values()]
    clients.sort(key=lambda c: (order.get(c.get("status"), 9), c.get("updated_at", "")), reverse=False)
    # updated 倒序 within status: 二次稳定排序
    clients.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
    clients.sort(key=lambda c: order.get(c.get("status"), 9))
    return clients


def search_clients(query: str, limit: int = 20) -> list[dict]:
    """跨客户检索 · 名字/公司/需求/备注/时间线全文命中 · 返回带匹配片段的客户列表。

    先走内存匹配(名字/公司/标签)· 再走 FTS(recall 客户档案正文)· 合并去重。
    给"第二大脑·跨客户检索面板"用 —— 一个词捞出所有相关客户。
    """
    q = (query or "").strip()
    if not q:
        return []
    ql = q.lower()
    hits: dict[str, dict] = {}

    for c in list_clients():
        blob_parts = [c.get("name", ""), c.get("company", ""), c.get("role", ""),
                      c.get("need", ""), c.get("notes", ""), " ".join(c.get("tags") or [])]
        for e in c.get("log") or []:
            blob_parts.append(e.get("text", ""))
        blob = "\n".join(str(p) for p in blob_parts if p)
        if ql in blob.lower():
            snippet = ""
            low = blob.lower()
            pos = low.find(ql)
            if pos >= 0:
                start = max(0, pos - 24)
                snippet = blob[start:pos + len(q) + 40].replace("\n", " ").strip()
            hits[c["id"]] = {**{k: c.get(k) for k in ("id", "name", "company", "status", "need")},
                             "snippet": snippet}
    return list(hits.values())[:limit]


def stats() -> dict:
    clients = list(load_manifest()["clients"].values())
    by_status: dict[str, int] = {}
    for c in clients:
        s = c.get("status", "lead")
        by_status[s] = by_status.get(s, 0) + 1
    return {"total": len(clients), "by_status": by_status}


# ── B-P0 · Excel/CSV 批量导入 ──────────────────────────────────────
# "合伙人接手一份现成客户名单" —— 一次把表格灌进档案·省得一个个建。
# 流程: parse_table(拆表) → suggest_mapping(猜列) → 前端确认映射 → import_rows(落档)。
# 保守红线: 只新增·默认按 name 去重跳过·从不改/删已有档案(不覆盖用户数据)。
MAX_IMPORT_ROWS = 2000  # 单次上限·防超大表炸内存/刷屏(超出截断·返回时提示)

# 表头关键词 → 档案字段 (中英混合·大小写不敏感·命中即映射)
_FIELD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "name": ("姓名", "名字", "名称", "客户", "联系人", "对接人", "昵称", "称呼", "name", "client", "contact person"),
    "company": ("公司", "单位", "企业", "组织", "机构", "甲方", "company", "org"),
    "role": ("职位", "角色", "头衔", "岗位", "职务", "title", "role", "position"),
    "contact": ("联系方式", "联系", "电话", "手机", "微信", "邮箱", "qq", "tel", "phone", "email", "wechat", "mobile"),
    "status": ("状态", "阶段", "进度", "status", "stage", "pipeline"),
    "tags": ("标签", "分类", "类型", "tag", "tags", "category", "label"),
    "notes": ("备注", "说明", "描述", "需求", "note", "notes", "remark", "memo", "desc"),
}

# 导入时把各种口语状态词归一到 pipeline 阶段
_STATUS_ALIASES: dict[str, str] = {
    "线索": "lead", "潜在": "lead", "意向": "lead", "lead": "lead", "new": "lead",
    "在合作": "active", "合作中": "active", "进行中": "active", "active": "active", "ongoing": "active",
    "暂停": "paused", "搁置": "paused", "paused": "paused", "hold": "paused",
    "已结束": "done", "结束": "done", "完成": "done", "已成交": "done", "done": "done", "closed": "done", "won": "done",
}


def _norm_status(raw: str) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return "lead"
    if s in STATUSES:
        return s
    for alias, canon in _STATUS_ALIASES.items():
        if alias in s:
            return canon
    return "lead"


def _cell(row: list, mapping: dict, field: str) -> str:
    idx = mapping.get(field)
    if idx is None:
        return ""
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return ""
    if idx < 0 or idx >= len(row):
        return ""
    return str(row[idx] if row[idx] is not None else "").strip()


def _parse_xlsx(data: bytes) -> tuple[list[str], list[list[str]]]:
    try:
        import io
        import openpyxl
    except ImportError as exc:
        raise ValueError("解析 Excel(.xlsx) 需要 openpyxl · 先 pip install openpyxl · 或改用 CSV 导入") from exc
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        ws = wb.active
        grid: list[list[str]] = []
        for r in ws.iter_rows(values_only=True):
            grid.append(["" if c is None else str(c).strip() for c in r])
            if len(grid) > MAX_IMPORT_ROWS + 1:
                break
    finally:
        wb.close()
    grid = [row for row in grid if any(row)]
    if not grid:
        raise ValueError("表格是空的(没读到任何行)")
    return grid[0], grid[1:]


def _parse_csv(data: bytes, *, tsv: bool = False) -> tuple[list[str], list[list[str]]]:
    import csv
    import io
    text = None
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            text = data.decode(enc)
            break
        except Exception:
            continue
    if text is None:
        text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=("\t" if tsv else ","))
    grid: list[list[str]] = []
    for row in reader:
        grid.append([str(c).strip() for c in row])
        if len(grid) > MAX_IMPORT_ROWS + 1:
            break
    grid = [row for row in grid if any(row)]
    if not grid:
        raise ValueError("CSV 是空的(没读到任何行)")
    return grid[0], grid[1:]


def parse_table(data: bytes, filename: str = "") -> tuple[list[str], list[list[str]]]:
    """把上传的 csv/xlsx 字节流拆成 (表头, 数据行) · 数据行是二维字符串数组。

    按扩展名分发·拿不到扩展名时按内容嗅探(xlsx 是 zip·以 PK 开头)。
    Raises: ValueError —— 空表 / 缺依赖 / 格式不认。
    """
    if not data:
        raise ValueError("文件是空的")
    ext = Path(filename or "").suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        return _parse_xlsx(data)
    if ext == ".tsv":
        return _parse_csv(data, tsv=True)
    if ext in (".csv", ".txt", ".text"):
        return _parse_csv(data)
    # 无扩展名 · 嗅探:zip 头(PK\x03\x04)当 xlsx·否则按 csv
    if data[:2] == b"PK":
        return _parse_xlsx(data)
    return _parse_csv(data)


def suggest_mapping(headers: list[str]) -> dict:
    """按表头关键词猜"哪一列是 name/company/...":返回 {field: col_index}。

    一列只认一个字段(先到先得)· name 没猜到则兜底取第一列(客户名单第一列几乎总是名字)。
    """
    mapping: dict[str, int] = {}
    used: set[int] = set()
    for field, kws in _FIELD_KEYWORDS.items():
        for idx, h in enumerate(headers):
            if idx in used:
                continue
            hl = str(h or "").strip().lower()
            if hl and any(kw in hl for kw in kws):
                mapping[field] = idx
                used.add(idx)
                break
    if "name" not in mapping and headers:
        mapping["name"] = 0
    return mapping


def import_rows(rows: list, mapping: dict, *, dedupe: bool = True) -> dict:
    """按映射把数据行批量建档 · 一次性存盘(不逐行写)· 只新增不覆盖。

    mapping: {field: col_index} · 必须含 name。dedupe=True 时同名(不分大小写)跳过。
    Returns: {created, skipped, errors[]}。
    """
    if mapping.get("name") is None:
        raise ValueError("必须指定「客户名(name)」是哪一列")
    _ensure_dir()
    with _MANIFEST_LOCK:  # wish-a1c5f147 · 复合操作锁 (整批读改写整体持锁)
        data = load_manifest()
        clients = data["clients"]
        existing = {(m.get("name") or "").strip().lower() for m in clients.values()}
        created = 0
        skipped = 0
        errors: list[str] = []
        to_index: list[str] = []
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for i, row in enumerate(rows or []):
            try:
                if not isinstance(row, (list, tuple)):
                    skipped += 1
                    continue
                name = _cell(row, mapping, "name")
                if not name:
                    skipped += 1
                    continue
                if dedupe and name.lower() in existing:
                    skipped += 1
                    continue
                tags_raw = _cell(row, mapping, "tags")
                tags = [t.strip() for t in re.split(r"[,，;；、/\s]+", tags_raw) if t.strip()] if tags_raw else []
                notes = _cell(row, mapping, "notes")
                cid = _new_client_id()
                # 导入的备注/进度列 → 落成初始时间线条(kind=note)· 这样导入客户在新详情里直接有动态
                log = [{"ts": _now(), "date": stamp, "kind": "note", "text": notes.strip()}] if notes.strip() else []
                meta = {
                    "id": cid,
                    "name": name,
                    "company": _cell(row, mapping, "company"),
                    "role": _cell(row, mapping, "role"),
                    "contact": _cell(row, mapping, "contact"),
                    "status": _norm_status(_cell(row, mapping, "status")),
                    "tags": tags,
                    "need": "",
                    "notes": "",
                    "log": log,
                    "created_at": _now(),
                    "updated_at": _now(),
                }
                clients[cid] = meta
                existing.add(name.lower())
                if log:
                    to_index.append(cid)
                created += 1
            except Exception as e:  # noqa: BLE001 — 单行坏不连累整批
                errors.append(f"第 {i + 1} 行: {e}")

        _save_manifest(data)
    for cid in to_index:
        _reindex(cid, clients.get(cid))  # 存盘后再补 FTS·失败也不回滚已建档
    return {"created": created, "skipped": skipped, "errors": errors[:20]}
