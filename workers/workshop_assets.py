"""workers/workshop_assets.py

 K stage 2c · 出品工坊资产层 · apps + workflows
 K stage 2c++ · wish-6fd76512 · 软删 + 回收站 (2026-05-25 第十六根毛)
 12 · wish-165ea1f6 phase A · ui_form_schema (2026-05-26 第二十之前的一次)
 12 · wish-165ea1f6 phase B · output_schema (2026-05-26 第二十之前的一次)
 13 · wish-165ea1f6 phase C · exec_kind + exec_template (2026-05-26 第二十之前的一次)

------------------------------------------------------------
跟 studio_workshop.py 是什么关系
------------------------------------------------------------

studio_workshop.py
    旧 4 维 markdown 产出 (content / design / dev / docs) — 已有 · 不动 · 仍在跑

workshop_assets.py (本文件)
    新形态: app + workflow 资产 · 一个个 json 文件 · 给 AI 自演进用
    - app: 独立模块 · 一个被 AI prompt + 工具白名单封装的子能力
    - workflow: 把多个 app / 工具串起来的 LiteGraph 流程

------------------------------------------------------------
落档结构
------------------------------------------------------------

data/workshop/
├── apps/
│   ├── app-<id>.json           ← active
│   └── _trash/
│       └── app-<id>.json       ← 软删 · 含 deleted_at 字段
└── flows/
    ├── flow-<id>.json
    └── _trash/
        └── flow-<id>.json

每个 app json:
    id / kind / name / description / icon / system_prompt
    tools (list[str] · 工具白名单) / model_hint / created_at / created_by / runs
    ui_form_schema (list[dict] · 声明式 form 字段 · wish-165ea1f6 phase A)
    output_schema (list[dict] · LiteGraph output ports · wish-165ea1f6 phase B)
    deleted_at (软删后才有 · ISO 8601)

ui_form_schema 字段说明 (wish-165ea1f6 phase A):
    每个元素是一个 form 字段 · JSON Schema 风格:
        name / type / label / required / default / help / max_chars / min / max / options / accept
    type ∈ text / textarea / number / select / boolean / file
    哲学: 声明式 JSON · 不是 HTML · 前端控制渲染 · 没注入风险

output_schema 字段说明 (wish-165ea1f6 phase B):
    给工作流引擎用 · 告诉下游节点这个 app 输出啥
    每个元素:
        name  · 变量名 (输出端口名 · 给下游 input 引用)
        type  · string / number / boolean / array / object / file
        label · 给 用户 看的人话
    哲学: 不强约束 (app 输出形态太多·硬卡 schema 会限制创造力)。 没填默认单一 'output' 字符串。

exec_kind / exec_template 字段说明 (wish-165ea1f6 phase C · 2026-05-26 主对话 AI 提出):
    `exec_kind` ∈ 'agentic' (默认) | 'scripted'
        - agentic · 走 app_runner.run_app · 一次 LLM session · 老路径 · 灵活但贵 (phase B 实现)
        - scripted · 走 http_executor · 表单字段直接拼 HTTP · 0 LLM · 快/省/稳 (phase C 实现)

    `exec_template` (scripted 必填 · agentic 可空):
        声明式 HTTP 调用模板 · 不允许任意表达式 (只允许变量替换 + 简单条件路由)
        见 _validate_exec_template 函数注释里的完整 schema

    哲学: scripted = 给纯 API 转发 app 一条直路 (GPT Image 2 / SOVITS / ElevenLabs 等都是这种)
         agentic = 给需要智能决策的 app 留 LLM 通道 ("整理周报" / "写代码改 bug" 这种)
         二者底层引擎不同 · 同一个 /workshop/apps/{aid}/run endpoint 按 exec_kind 路由

每个 flow json:
    id / kind / name / description / litegraph_json (LiteGraph.serialize 出来的)
    created_at / created_by / runs
    deleted_at (软删后才有)

------------------------------------------------------------
API
------------------------------------------------------------

# active
list_apps()            -> list[dict]    时间倒序 · 不含 _trash
list_flows()           -> list[dict]    时间倒序 · 不含 _trash
load_app(aid)          -> dict | None
load_flow(fid)         -> dict | None
save_app(spec)         -> dict          落档 · 自动补 id/created_at
save_flow(spec)        -> dict          落档 · 自动补 id/created_at

# trash (wish-6fd76512)
delete_app(aid)        -> bool          软删 · 移到 _trash/ · 加 deleted_at
delete_flow(fid)       -> bool          软删
restore_app(aid)       -> bool          从 _trash 移回 apps/ · 删 deleted_at
restore_flow(fid)      -> bool          从 _trash 移回 flows/
list_trash_apps()      -> list[dict]    列回收站 apps · 按 deleted_at 倒序
list_trash_flows()     -> list[dict]    列回收站 flows
empty_trash_app(aid)   -> bool          真 unlink 单条 app
empty_trash_flow(fid)  -> bool          真 unlink 单条 flow
empty_trash_all(kind)  -> int           清空回收站 · kind ∈ ('app', 'flow', 'all') · 返删除条数
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
APPS_DIR = ROOT / "data" / "workshop" / "apps"
FLOWS_DIR = ROOT / "data" / "workshop" / "flows"
APPS_TRASH_DIR = APPS_DIR / "_trash"
FLOWS_TRASH_DIR = FLOWS_DIR / "_trash"


# ──────────────────────────────────────────────────────────
# 公共入口 · App
# ──────────────────────────────────────────────────────────

def list_apps(*, max_items: int = 200) -> list[dict]:
    """列所有 app · 时间倒序 (最近创建在前)"""
    APPS_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for p in sorted(APPS_DIR.glob("app-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append(_sanitize_app(data))
        if len(out) >= max_items:
            break
    return out


def load_app(aid: str) -> Optional[dict]:
    """读单个 app · 找不到返回 None"""
    if not aid or not aid.startswith("app-"):
        return None
    p = APPS_DIR / f"{aid}.json"
    if not p.exists():
        return None
    try:
        return _sanitize_app(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return None


def save_app(spec: dict) -> dict:
    """落一个 app · spec 至少要有 name + description

    自动补:
        id (新建时)        - app-<8hex>
        kind               - "app"
        created_at         - ISO 8601
        created_by         - "AI" 默认
        runs               - 0
        icon               - '<i class="ri-puzzle-fill"></i>' 默认 (Remix Icon)
        tools              - [] 默认
        model_hint         - "" 默认
        system_prompt      - "" 默认 (允许后续编辑)

    沉淀闭环 v2 刀① (2026-06-10) · 本函数是 create_app / update_app / WebUI POST 的
    单一咽喉点 · 在这里挂结构校验 + 版本化:
        - app_spec_guard 校验六段结构 / 产出隔离 / asset_slots (新 app 严格·老 app 宽限)
        - version 单调自增 · updated_at · changelog (spec 可传 change_note 记一句话)
        - spec_version=2 标记已达标 app · 达标后更新也按严格执行
        - 返回值带 _warnings (宽限项·不落盘·给调用方回显)
    """
    spec = dict(spec or {})
    name = (spec.get("name") or "").strip()
    description = (spec.get("description") or "").strip()
    if not name:
        raise ValueError("name is required")
    if not description:
        raise ValueError("description is required")

    aid = (spec.get("id") or "").strip()
    if not aid:
        aid = "app-" + uuid.uuid4().hex[:8]
    elif not aid.startswith("app-"):
        raise ValueError(f"app id must start with 'app-': {aid}")

    tools = spec.get("tools") or []
    if not isinstance(tools, list):
        raise ValueError("tools must be a list of tool names")
    tools = [str(t).strip() for t in tools if str(t).strip()]

    ui_form_schema = _validate_ui_form_schema(spec.get("ui_form_schema"))
    output_schema = _validate_output_schema(spec.get("output_schema"))

    exec_kind = (spec.get("exec_kind") or "agentic").strip().lower()
    if exec_kind not in {"agentic", "scripted"}:
        raise ValueError(f"exec_kind must be 'agentic' or 'scripted' · got {exec_kind!r}")

    exec_template = spec.get("exec_template")
    if exec_kind == "scripted":
        if not exec_template:
            raise ValueError("scripted app 必须有 exec_template")
        exec_template = _validate_exec_template(exec_template)
    else:
        exec_template = _validate_exec_template(exec_template) if exec_template else None

    from .app_spec_guard import (
        SPEC_VERSION,
        render_reject,
        validate_app_payload,
        validate_asset_slots,
    )

    payload = {
        "id": aid,
        "kind": "app",
        "name": name,
        "description": description,
        "icon": (spec.get("icon") or '<i class="ri-puzzle-fill"></i>').strip() or '<i class="ri-puzzle-fill"></i>',
        "system_prompt": (spec.get("system_prompt") or "").strip(),
        "tools": tools,
        "model_hint": (spec.get("model_hint") or "").strip(),
        "ui_form_schema": ui_form_schema,
        "output_schema": output_schema,
        "exec_kind": exec_kind,
        "exec_template": exec_template,
        "asset_slots": validate_asset_slots(spec.get("asset_slots")),
        "created_at": spec.get("created_at") or _iso_now(),
        "created_by": (spec.get("created_by") or "AI").strip(),
        "runs": int(spec.get("runs") or 0),
        "shipped": False,  # 默认 False · 下面 sticky 逻辑会复原 prev.shipped 或读 spec.shipped
    }

    # ── 沉淀闭环 v2 · 结构校验 (prev 直接读磁盘 · 不信任调用方传入的状态) ──
    prev: Optional[dict] = None
    prev_path = APPS_DIR / f"{aid}.json"
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
        except Exception:
            prev = None

    # 沉淀闭环 v2 刀⑤修正 (2026-06-10): shipped 字段处理
    # - 显式传 shipped 在 spec → 用 spec.shipped (覆盖 prev · 允许将来用工具改 shipped 状态)
    # - 否则继承 prev.shipped (sticky · 防止 update_app 漏传把 shipped 抹掉)
    if "shipped" in spec:
        payload["shipped"] = bool(spec["shipped"])
    elif prev and prev.get("shipped"):
        payload["shipped"] = True

    errors, warnings, strict_ok = validate_app_payload(payload, prev)
    if errors:
        raise ValueError(render_reject(errors, aid))

    # ── 版本化: version 单调自增 · changelog 留痕 ──
    now = _iso_now()
    prev_version = int((prev or {}).get("version") or 0)
    payload["version"] = prev_version + 1
    payload["updated_at"] = now
    if strict_ok:
        payload["spec_version"] = SPEC_VERSION
    else:
        payload["spec_version"] = int((prev or {}).get("spec_version") or 1)

    changelog = list((prev or {}).get("changelog") or [])
    note = (spec.get("change_note") or "").strip()
    if note or prev is None:
        changelog.append({
            "v": payload["version"],
            "at": now,
            "note": note or "初版",
        })
    payload["changelog"] = changelog[-30:]

    # 沉淀闭环 v2 刀④ · 覆盖前快照 prev 到 _versions/<aid>/v<N>.json (失败永不阻塞)
    if prev:
        try:
            from .workshop_app_versions import snapshot as _ver_snapshot
            _ver_snapshot(prev)
        except Exception:
            pass

    APPS_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(
        APPS_DIR / f"{aid}.json",
        json.dumps(payload, ensure_ascii=False, indent=2),
    )
    if warnings:
        payload = dict(payload)
        payload["_warnings"] = warnings
    return payload


def delete_app(aid: str) -> bool:
    """软删一个 app · 移到 _trash/ · 加 deleted_at 字段

    返回 True 表示成功移到回收站 · False 表示找不到 / 失败。
    跟 wish-6fd76512 一同上线。 原物理 unlink 语义改为 empty_trash_app。
    """
    if not aid or not aid.startswith("app-"):
        return False
    return _move_to_trash(APPS_DIR, APPS_TRASH_DIR, f"{aid}.json", _stamp_deleted)


def restore_app(aid: str) -> bool:
    """从 _trash 移回 apps/ · 删 deleted_at 字段

    apps/ 里已存在同 aid 时返回 False (避免覆盖 active 版本)。
    """
    if not aid or not aid.startswith("app-"):
        return False
    return _restore_from_trash(APPS_DIR, APPS_TRASH_DIR, f"{aid}.json", _unstamp_deleted)


def list_trash_apps(*, max_items: int = 200) -> list[dict]:
    """列回收站里的 apps · 按 deleted_at 倒序 (最近删的在前)"""
    return _list_trash_dir(APPS_TRASH_DIR, "app-*.json", _sanitize_app, max_items)


def empty_trash_app(aid: str) -> bool:
    """真删一个回收站里的 app · 不可恢复

    跟 GUARD 档对齐:agent_tools/empty_trash 会调用此函数。
    """
    if not aid or not aid.startswith("app-"):
        return False
    return _hard_unlink(APPS_TRASH_DIR, f"{aid}.json")


# ──────────────────────────────────────────────────────────
# 公共入口 · Workflow
# ──────────────────────────────────────────────────────────

def list_flows(*, max_items: int = 200) -> list[dict]:
    FLOWS_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for p in sorted(FLOWS_DIR.glob("flow-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append(_sanitize_flow(data, with_graph=False))
        if len(out) >= max_items:
            break
    return out


def load_flow(fid: str) -> Optional[dict]:
    """读单个 flow · 包含完整 litegraph_json"""
    if not fid or not fid.startswith("flow-"):
        return None
    p = FLOWS_DIR / f"{fid}.json"
    if not p.exists():
        return None
    try:
        return _sanitize_flow(json.loads(p.read_text(encoding="utf-8")), with_graph=True)
    except Exception:
        return None


def save_flow(spec: dict) -> dict:
    """落一个 workflow · spec 必须含 name + description + (steps 或 litegraph_json)

    沉淀闭环 v2 刀② (2026-06-10): 新增 steps 线性格式 (flow 本体) ·
    传了 steps 时 litegraph_json 自动从 steps 投影 (画布只读视图) ·
    老 litegraph flow 不传 steps 照旧兼容。
    """
    spec = dict(spec or {})
    name = (spec.get("name") or "").strip()
    description = (spec.get("description") or "").strip()
    graph = spec.get("litegraph_json")
    raw_steps = spec.get("steps")
    if not name:
        raise ValueError("name is required")
    if not description:
        raise ValueError("description is required")

    steps: list[dict] = []
    if raw_steps:
        from .flow_steps import steps_to_litegraph, validate_steps
        steps = validate_steps(raw_steps)
        graph = steps_to_litegraph(steps)  # steps 是本体 · 画布永远是最新投影
    elif graph is None or not isinstance(graph, dict):
        raise ValueError("必须提供 steps (推荐·线性步骤清单) 或 litegraph_json (老画布格式)")

    fid = (spec.get("id") or "").strip()
    if not fid:
        fid = "flow-" + uuid.uuid4().hex[:8]
    elif not fid.startswith("flow-"):
        raise ValueError(f"flow id must start with 'flow-': {fid}")

    # 0.2.0 · 信任账本 (trust_level)
    # 保留旧值 · 否则 update_app 类 load→改→save 流程会把信任洗成 0
    existing = load_flow(fid) or {} if fid else {}
    existing_trust = int(existing.get("trust_level") or 0)
    incoming_trust = spec.get("trust_level")
    if incoming_trust is None:
        trust_level = existing_trust
    else:
        trust_level = max(0, min(3, int(incoming_trust)))
    success_runs = int(spec.get("success_runs") or existing.get("success_runs") or 0)
    last_failure_at = spec.get("last_failure_at") if "last_failure_at" in spec else existing.get("last_failure_at")
    trusted_by = spec.get("trusted_by") if "trusted_by" in spec else existing.get("trusted_by")

    payload = {
        "id": fid,
        "kind": "flow",
        "name": name,
        "description": description,
        "flow_kind": "steps" if steps else "litegraph",
        "steps": steps,
        "litegraph_json": graph,
        "created_at": spec.get("created_at") or _iso_now(),
        "created_by": (spec.get("created_by") or "AI").strip(),
        "runs": int(spec.get("runs") or 0),
        # 信任账本 (用户 痛点: 跑过 OK 的 flow 不要次次问)
        # trust_level 含义:
        #   0 = 没跑过 / 失败过 · CONFIRM 全要 y/n
        #   1 = 跑过 1 次成功 · 入口不打断 · 内部 CONFIRM 仍要 y/n
        #   2 = 跑过 3 次成功 · 内部 CONFIRM 也自动放行 (autopilot 默认开)
        #   3 = 用户 钦定 · 同 2 但带 🌟 标记
        #   GUARD tier 永远不降级 · 是保命线
        "trust_level": trust_level,
        "success_runs": success_runs,          # 累计成功跑过几次 (统计 + 自动升 lvl 用)
        "last_failure_at": last_failure_at,    # 最近失败时间 · 失败会重置 trust → 0
        "trusted_by": trusted_by,              # "用户" / "auto" · 谁拍板信任的
    }

    FLOWS_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(
        FLOWS_DIR / f"{fid}.json",
        json.dumps(payload, ensure_ascii=False, indent=2),
    )
    return payload


# 信任账本辅助函数 (flow_runner / trust_flow 工具调)
def bump_flow_trust(fid: str) -> Optional[dict]:
    """flow 一次 run 成功后调 · success_runs++ · 满 3 次自动升 trust_level 到 2"""
    flow = load_flow(fid)
    if not flow:
        return None
    flow["success_runs"] = int(flow.get("success_runs") or 0) + 1
    cur_level = int(flow.get("trust_level") or 0)
    # 自动升级阶梯: 1 次 → lvl 1 · 3 次 → lvl 2 · lvl 3 只有 用户 手动给
    target_level = 0
    if flow["success_runs"] >= 3:
        target_level = 2
    elif flow["success_runs"] >= 1:
        target_level = 1
    # 只升不降 (用户 已钦定 lvl 3 不能被自动覆盖)
    new_level = max(cur_level, target_level)
    flow["trust_level"] = new_level
    if new_level > cur_level and not flow.get("trusted_by"):
        flow["trusted_by"] = "auto"
    flow["last_failure_at"] = None
    return save_flow(flow)


def reset_flow_trust(fid: str, *, reason: str = "") -> Optional[dict]:
    """flow 一次 run 失败后调 · trust_level 降到 0 · success_runs 归零 · 让 用户 重新背书"""
    flow = load_flow(fid)
    if not flow:
        return None
    flow["trust_level"] = 0
    flow["success_runs"] = 0
    flow["last_failure_at"] = _iso_now()
    flow["trusted_by"] = None
    return save_flow(flow)


def set_flow_trust(fid: str, *, level: int, by: str = "用户") -> Optional[dict]:
    """用户 手动设 trust_level · level=3 = 钦定 · 不会被自动逻辑覆盖"""
    flow = load_flow(fid)
    if not flow:
        return None
    flow["trust_level"] = max(0, min(3, int(level)))
    flow["trusted_by"] = by
    if flow["trust_level"] == 0:
        flow["success_runs"] = 0
    return save_flow(flow)


def delete_flow(fid: str) -> bool:
    """软删一个 flow · 移到 _trash/ · 加 deleted_at 字段"""
    if not fid or not fid.startswith("flow-"):
        return False
    return _move_to_trash(FLOWS_DIR, FLOWS_TRASH_DIR, f"{fid}.json", _stamp_deleted)


def restore_flow(fid: str) -> bool:
    """从 _trash 移回 flows/ · 删 deleted_at 字段"""
    if not fid or not fid.startswith("flow-"):
        return False
    return _restore_from_trash(FLOWS_DIR, FLOWS_TRASH_DIR, f"{fid}.json", _unstamp_deleted)


def list_trash_flows(*, max_items: int = 200) -> list[dict]:
    """列回收站里的 flows · 按 deleted_at 倒序"""
    return _list_trash_dir(
        FLOWS_TRASH_DIR,
        "flow-*.json",
        lambda d: _sanitize_flow(d, with_graph=False),
        max_items,
    )


def empty_trash_flow(fid: str) -> bool:
    """真删一个回收站里的 flow · 不可恢复"""
    if not fid or not fid.startswith("flow-"):
        return False
    return _hard_unlink(FLOWS_TRASH_DIR, f"{fid}.json")


# ──────────────────────────────────────────────────────────
# 公共入口 · runs 计数 (沉淀闭环 v2 刀② · 字段早就有 · 自增一直缺失)
# ──────────────────────────────────────────────────────────

def _increment_runs(path: Path) -> None:
    """直改 json 的 runs+1 · 不走 save_app 校验 (内部计数 · 非内容变更 · 不动 version)"""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["runs"] = int(data.get("runs") or 0) + 1
        _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))
    except Exception:
        pass  # 计数失败不影响执行


def increment_app_runs(aid: str) -> None:
    if aid and aid.startswith("app-"):
        _increment_runs(APPS_DIR / f"{aid}.json")


def increment_flow_runs(fid: str) -> None:
    if fid and fid.startswith("flow-"):
        _increment_runs(FLOWS_DIR / f"{fid}.json")


# ──────────────────────────────────────────────────────────
# 公共入口 · 清空回收站
# ──────────────────────────────────────────────────────────

def empty_trash_all(kind: str = "all") -> int:
    """清空回收站 · 真 unlink · 不可恢复

    Args:
        kind: 'app' | 'flow' | 'all' (默认全清)

    Returns:
        真删了几条 (跨 app + flow)
    """
    kind = (kind or "all").strip().lower()
    if kind not in ("app", "flow", "all"):
        return 0

    count = 0
    if kind in ("app", "all"):
        if APPS_TRASH_DIR.exists():
            for p in APPS_TRASH_DIR.glob("app-*.json"):
                try:
                    p.unlink()
                    count += 1
                except OSError:
                    continue
    if kind in ("flow", "all"):
        if FLOWS_TRASH_DIR.exists():
            for p in FLOWS_TRASH_DIR.glob("flow-*.json"):
                try:
                    p.unlink()
                    count += 1
                except OSError:
                    continue
    return count


# ──────────────────────────────────────────────────────────
# 内部
# ──────────────────────────────────────────────────────────

def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _atomic_write(path: Path, content: str) -> None:
    """原子写—— · wish-badd4 收编到 safe_write
    workshop assets registry (app / workflow / templates) 是 用户 自建作品·backup=True"""
    from .safe_write import atomic_write_text
    atomic_write_text(path, content, backup=True)


# ──────────────────────────────────────────────────────────
# trash 内部辅助 (app + flow 共用)
# ──────────────────────────────────────────────────────────

def _move_to_trash(
    src_dir: Path,
    trash_dir: Path,
    filename: str,
    stamp_fn,
) -> bool:
    """原子地把 active 文件搬到 trash · 加 deleted_at 字段"""
    src = src_dir / filename
    if not src.exists():
        return False
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except Exception:
        return False

    data = stamp_fn(data)
    trash_dir.mkdir(parents=True, exist_ok=True)
    target = trash_dir / filename

    try:
        _atomic_write(target, json.dumps(data, ensure_ascii=False, indent=2))
        src.unlink()
        return True
    except OSError:
        return False


def _restore_from_trash(
    active_dir: Path,
    trash_dir: Path,
    filename: str,
    unstamp_fn,
) -> bool:
    """从 trash 移回 active · 删 deleted_at · active 已存在同 aid 时拒绝"""
    src = trash_dir / filename
    if not src.exists():
        return False
    active_dir.mkdir(parents=True, exist_ok=True)
    target = active_dir / filename
    if target.exists():
        return False

    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except Exception:
        return False

    data = unstamp_fn(data)
    try:
        _atomic_write(target, json.dumps(data, ensure_ascii=False, indent=2))
        src.unlink()
        return True
    except OSError:
        return False


def _list_trash_dir(
    trash_dir: Path,
    glob_pat: str,
    sanitize_fn,
    max_items: int,
) -> list[dict]:
    """列 trash 子目录 · 按 deleted_at 倒序 · 缺 deleted_at 用 mtime 兜底"""
    if not trash_dir.exists():
        return []
    items: list[tuple[str, dict]] = []
    for p in trash_dir.glob(glob_pat):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        entry = sanitize_fn(data)
        entry["deleted_at"] = data.get("deleted_at") or ""
        sort_key = entry["deleted_at"] or time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(p.stat().st_mtime)
        )
        items.append((sort_key, entry))

    items.sort(key=lambda kv: kv[0], reverse=True)
    return [entry for _, entry in items[:max_items]]


def _hard_unlink(trash_dir: Path, filename: str) -> bool:
    """真 unlink trash 里的单条 · 必须文件在 trash 子目录里 (双保险防越权)"""
    p = trash_dir / filename
    if not p.exists():
        return False
    try:
        resolved = p.resolve()
        trash_root = trash_dir.resolve()
        if trash_root not in resolved.parents and resolved != trash_root:
            return False
    except OSError:
        return False
    try:
        p.unlink()
        return True
    except OSError:
        return False


def _stamp_deleted(data: dict) -> dict:
    data = dict(data)
    data["deleted_at"] = _iso_now()
    return data


def _unstamp_deleted(data: dict) -> dict:
    data = dict(data)
    data.pop("deleted_at", None)
    return data


# ──────────────────────────────────────────────────────────
# ui_form_schema 验证 (wish-165ea1f6 phase A)
# ──────────────────────────────────────────────────────────

_VALID_FIELD_TYPES = {"text", "textarea", "number", "select", "boolean", "file"}
_VALID_OUTPUT_TYPES = {"string", "number", "boolean", "array", "object", "file"}
_VALID_EXEC_KINDS = {"http"}
_VALID_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_VALID_BODY_KINDS = {"json", "multipart_form", "form_urlencoded", "raw"}
_VALID_RESPONSE_KINDS = {"json", "text", "binary_save", "b64_save"}


def _validate_exec_template(spec: object) -> dict:
    """规范化 + 校验 exec_template · 返回清洗后的 dict

    完整 schema (wish-165ea1f6 phase C · 故意做窄·避免变成 mini Jinja DSL):

    {
      "kind": "http",                          // 当前只支持 http · 未来可加 shell/python
      "routes": [                              // 至少 1 个 · 按 when 顺序匹配 · 第一个命中
        {
          "when": "default" | "<field>==<value>",  // 简单相等 · 不支持复杂表达式
          "method": "GET|POST|PUT|PATCH|DELETE",
          "url": "https://...${ui:prompt}...",
          "headers": {"Authorization": "Bearer ${secret:api_key}"},
          "body": {...} | null,                // body_kind=json 时是 dict · multipart 时是 dict
          "body_kind": "json|multipart_form|form_urlencoded|raw",
          "timeout_sec": 60                    // 默认 60 · 图片生成可加到 300
        }
      ],
      "response": {
        "kind": "json|text|binary_save|b64_save",
        "extract": "data[0].b64_json",         // jq-like path · response.kind=json/b64_save 用
        "save": {
          "dir": "data/workshop/outputs/${app_id}",
          "filename": "${ui:output_name:auto}.png"
        },
        "mapping": {                            // output_schema.name → 取值 path
          "image_url": "__saved_path__",        // 特殊值: 保存后的相对 URL
          "revised_prompt": "data[0].revised_prompt"
        }
      }
    }

    设计哲学:
      - **不允许任意表达式** (没有 ternary · 没有 lambda · 没有 eval) ·
        条件分支只能走 routes[].when 的 '<field>==<value>' 简单匹配
      - **不允许嵌套循环** · 不支持 'foreach' / 'map'
      - **只支持变量替换** · ${ui:name} / ${ui:name:default} / ${secret:k} / ${upstream:nid:port}
      - 一句话: 这是配置 · 不是脚本。 需要复杂逻辑请走 agentic + LLM。
    """
    if not isinstance(spec, dict):
        raise ValueError("exec_template must be a dict")

    kind = (spec.get("kind") or "http").strip().lower()
    if kind not in _VALID_EXEC_KINDS:
        raise ValueError(f"exec_template.kind unsupported: {kind} (valid: {_VALID_EXEC_KINDS})")

    raw_routes = spec.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ValueError("exec_template.routes must be a non-empty list")
    if len(raw_routes) > 10:
        raise ValueError(f"exec_template.routes too long: {len(raw_routes)} (max 10)")

    routes_out: list[dict] = []
    has_default = False
    for i, raw in enumerate(raw_routes):
        if not isinstance(raw, dict):
            raise ValueError(f"exec_template.routes[{i}] must be a dict")

        when = (raw.get("when") or "default").strip()
        if when == "default":
            has_default = True
        elif "==" in when:
            field, _, _ = when.partition("==")
            field = field.strip()
            if not field or not field.replace("_", "").isalnum():
                raise ValueError(f"routes[{i}].when invalid: {when!r}")
        else:
            raise ValueError(
                f"routes[{i}].when must be 'default' or '<field>==<value>' · got {when!r}"
            )

        method = (raw.get("method") or "POST").strip().upper()
        if method not in _VALID_HTTP_METHODS:
            raise ValueError(f"routes[{i}].method unsupported: {method}")

        url = (raw.get("url") or "").strip()
        if not url:
            raise ValueError(f"routes[{i}].url is required")
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("${")):
            raise ValueError(f"routes[{i}].url must start with http(s):// or ${{...}}")

        headers = raw.get("headers") or {}
        if not isinstance(headers, dict):
            raise ValueError(f"routes[{i}].headers must be a dict")
        for hk, hv in headers.items():
            if not isinstance(hk, str) or not isinstance(hv, str):
                raise ValueError(f"routes[{i}].headers must be dict[str, str]")

        body_kind = (raw.get("body_kind") or "json").strip().lower()
        if body_kind not in _VALID_BODY_KINDS:
            raise ValueError(f"routes[{i}].body_kind unsupported: {body_kind}")
        body = raw.get("body")
        if body is not None and not isinstance(body, (dict, str)):
            raise ValueError(f"routes[{i}].body must be dict / str / null")

        try:
            timeout_sec = int(raw.get("timeout_sec") or 60)
        except (TypeError, ValueError):
            raise ValueError(f"routes[{i}].timeout_sec must be int")
        if timeout_sec < 1 or timeout_sec > 600:
            raise ValueError(f"routes[{i}].timeout_sec must be 1..600 · got {timeout_sec}")

        routes_out.append({
            "when": when,
            "method": method,
            "url": url,
            "headers": dict(headers),
            "body": body,
            "body_kind": body_kind,
            "timeout_sec": timeout_sec,
        })

    if not has_default and len(routes_out) == 1:
        routes_out[0]["when"] = "default"
        has_default = True
    if not has_default:
        raise ValueError("exec_template.routes 必须包含一条 when='default' 兜底路由 (避免所有条件都不匹配时挂掉)")

    response = spec.get("response") or {}
    if not isinstance(response, dict):
        raise ValueError("exec_template.response must be a dict")
    resp_kind = (response.get("kind") or "json").strip().lower()
    if resp_kind not in _VALID_RESPONSE_KINDS:
        raise ValueError(f"response.kind unsupported: {resp_kind} (valid: {_VALID_RESPONSE_KINDS})")

    extract = response.get("extract") or ""
    if not isinstance(extract, str):
        raise ValueError("response.extract must be a string")

    save = response.get("save") or {}
    if save and not isinstance(save, dict):
        raise ValueError("response.save must be a dict")
    save_dir = (save.get("dir") or "data/workshop/outputs/${app_id}").strip()
    save_filename = (save.get("filename") or "output-${ts}").strip()

    mapping = response.get("mapping") or {}
    if not isinstance(mapping, dict):
        raise ValueError("response.mapping must be a dict")
    for mk, mv in mapping.items():
        if not isinstance(mk, str) or not isinstance(mv, str):
            raise ValueError("response.mapping must be dict[str, str]")

    if resp_kind in {"binary_save", "b64_save"}:
        if not save:
            raise ValueError(f"response.kind={resp_kind} requires response.save.{{dir,filename}}")

    return {
        "kind": kind,
        "routes": routes_out,
        "response": {
            "kind": resp_kind,
            "extract": extract,
            "save": {"dir": save_dir, "filename": save_filename} if save else None,
            "mapping": dict(mapping),
        },
    }


def _validate_output_schema(schema: object) -> list[dict]:
    """规范化 + 校验 output_schema · 返回清洗后的 list[dict]

    给工作流引擎用 · 决定 LiteGraph node 的 output ports。 比 ui_form_schema 宽松——
    output 形态太自由 · 不能硬约束。

    限制:
        - 最多 10 个输出 (一般 app 1-3 个就够 · 多了画布乱)
        - name 必须是合法变量名 · 保留字 (output 默认/input/app/opus) 不能用
        - type 不在白名单 · 静默退化为 'string'
    """
    if schema is None or schema == "":
        return []
    if not isinstance(schema, list):
        raise ValueError("output_schema must be a list of field dicts")
    if len(schema) > 10:
        raise ValueError(f"output_schema too long: {len(schema)} fields (max 10)")

    reserved = {"input", "app", "opus"}
    seen_names: set[str] = set()
    out: list[dict] = []

    for i, raw in enumerate(schema):
        if not isinstance(raw, dict):
            raise ValueError(f"output_schema[{i}] must be a dict")

        name = str(raw.get("name") or "").strip()
        if not name:
            raise ValueError(f"output_schema[{i}].name is required")
        if not name.replace("_", "").isalnum() or name[0].isdigit():
            raise ValueError(
                f"output_schema[{i}].name '{name}' invalid · "
                "must match [a-zA-Z_][a-zA-Z0-9_]*"
            )
        if name in reserved:
            raise ValueError(
                f"output_schema[{i}].name '{name}' is reserved"
            )
        if name in seen_names:
            raise ValueError(f"output_schema duplicate name: {name}")
        seen_names.add(name)

        ftype = (raw.get("type") or "string").strip().lower()
        if ftype not in _VALID_OUTPUT_TYPES:
            ftype = "string"

        field = {"name": name, "type": ftype, "label": str(raw.get("label") or name)}
        if raw.get("help"):
            field["help"] = str(raw["help"])
        out.append(field)

    return out


def _validate_ui_form_schema(schema: object) -> list[dict]:
    """规范化 + 校验 ui_form_schema · 返回清洗后的 list[dict]

    不接受的: 抛 ValueError · 让 save_app 拒绝落盘。
    宽容的:   缺 type 默认 text · 缺 label 用 name · 缺 required 默认 false。

    限制 (防滥用):
        - 最多 20 个字段 (form 不该太复杂 · 复杂的应该走 NLP)
        - name 必须是 [a-zA-Z_][a-zA-Z0-9_]*  (变量名规范 · 给 ${ui:<name>} 模板用)
        - name 不能撞内置变量名 (input / output / app / opus / now / today)
    """
    if schema is None or schema == "":
        return []
    if not isinstance(schema, list):
        raise ValueError("ui_form_schema must be a list of field dicts")
    if len(schema) > 20:
        raise ValueError(f"ui_form_schema too long: {len(schema)} fields (max 20)")

    reserved = {"input", "output", "app", "opus", "now", "today"}
    seen_names: set[str] = set()
    out: list[dict] = []

    for i, raw in enumerate(schema):
        if not isinstance(raw, dict):
            raise ValueError(f"ui_form_schema[{i}] must be a dict")

        name = str(raw.get("name") or "").strip()
        if not name:
            raise ValueError(f"ui_form_schema[{i}].name is required")
        if not name.replace("_", "").isalnum() or name[0].isdigit():
            raise ValueError(
                f"ui_form_schema[{i}].name '{name}' invalid · "
                "must match [a-zA-Z_][a-zA-Z0-9_]*"
            )
        if name in reserved:
            raise ValueError(
                f"ui_form_schema[{i}].name '{name}' is reserved · pick another"
            )
        if name in seen_names:
            raise ValueError(f"ui_form_schema duplicate field name: {name}")
        seen_names.add(name)

        ftype = (raw.get("type") or "text").strip().lower()
        if ftype not in _VALID_FIELD_TYPES:
            raise ValueError(
                f"ui_form_schema[{i}].type '{ftype}' invalid · "
                f"must be one of {sorted(_VALID_FIELD_TYPES)}"
            )

        field = {
            "name": name,
            "type": ftype,
            "label": str(raw.get("label") or name),
            "required": bool(raw.get("required") or False),
        }
        if "default" in raw and raw["default"] is not None:
            field["default"] = raw["default"]
        if raw.get("help"):
            field["help"] = str(raw["help"])

        if ftype in ("text", "textarea") and raw.get("max_chars"):
            try:
                field["max_chars"] = int(raw["max_chars"])
            except (TypeError, ValueError):
                pass

        if ftype == "number":
            if "min" in raw and raw["min"] is not None:
                field["min"] = float(raw["min"])
            if "max" in raw and raw["max"] is not None:
                field["max"] = float(raw["max"])

        if ftype == "select":
            opts = raw.get("options") or []
            if not isinstance(opts, list) or not opts:
                raise ValueError(
                    f"ui_form_schema[{i}] type=select requires non-empty options"
                )
            cleaned: list[dict] = []
            for j, op in enumerate(opts):
                if isinstance(op, dict):
                    val = op.get("value")
                    lbl = op.get("label") or val
                elif isinstance(op, (str, int, float, bool)):
                    val = op
                    lbl = str(op)
                else:
                    raise ValueError(
                        f"ui_form_schema[{i}].options[{j}] invalid"
                    )
                if val is None:
                    raise ValueError(
                        f"ui_form_schema[{i}].options[{j}].value missing"
                    )
                cleaned.append({"value": val, "label": str(lbl)})
            field["options"] = cleaned

        if ftype == "file" and raw.get("accept"):
            field["accept"] = str(raw["accept"])

        out.append(field)

    return out


def _sanitize_app(data: dict) -> dict:
    """补字段 · 防老 json 缺字段"""
    return {
        "id": data.get("id") or "",
        "kind": "app",
        "name": data.get("name") or "(未命名)",
        "description": data.get("description") or "",
        "icon": data.get("icon") or '<i class="ri-puzzle-fill"></i>',
        "system_prompt": data.get("system_prompt") or "",
        "tools": list(data.get("tools") or []),
        "model_hint": data.get("model_hint") or "",
        "ui_form_schema": list(data.get("ui_form_schema") or []),
        "output_schema": list(data.get("output_schema") or []),
        "exec_kind": data.get("exec_kind") or "agentic",
        "exec_template": data.get("exec_template"),
        # 沉淀闭环 v2 · 新字段必须过 sanitize · 否则 update_app (load→改→save) 会把它们洗掉
        "asset_slots": list(data.get("asset_slots") or []),
        "version": int(data.get("version") or 1),
        "updated_at": data.get("updated_at") or "",
        "spec_version": int(data.get("spec_version") or 1),
        "changelog": list(data.get("changelog") or []),
        "created_at": data.get("created_at") or "",
        "created_by": data.get("created_by") or "AI",
        "runs": int(data.get("runs") or 0),
        # 沉淀闭环 v2 刀⑤修正 (2026-06-10): shipped=True 标记自带 app · 随 DK 出厂 · UI 隐藏删按钮
        "shipped": bool(data.get("shipped") or False),
    }


def _sanitize_flow(data: dict, *, with_graph: bool) -> dict:
    base = {
        "id": data.get("id") or "",
        "kind": "flow",
        "name": data.get("name") or "(未命名)",
        "description": data.get("description") or "",
        "flow_kind": data.get("flow_kind") or ("steps" if data.get("steps") else "litegraph"),
        "steps": list(data.get("steps") or []),
        "node_count": _count_nodes(data.get("litegraph_json")),
        "created_at": data.get("created_at") or "",
        "created_by": data.get("created_by") or "AI",
        "runs": int(data.get("runs") or 0),
        # 0.2.0 · 信任账本字段 (UI 卡显示 trust badge 用)
        "trust_level": int(data.get("trust_level") or 0),
        "success_runs": int(data.get("success_runs") or 0),
        "last_failure_at": data.get("last_failure_at"),
        "trusted_by": data.get("trusted_by"),
    }
    if with_graph:
        base["litegraph_json"] = data.get("litegraph_json") or {}
    return base


def _count_nodes(graph: object) -> int:
    if not isinstance(graph, dict):
        return 0
    nodes = graph.get("nodes")
    if isinstance(nodes, list):
        return len(nodes)
    return 0
