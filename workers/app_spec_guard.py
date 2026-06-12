"""workers/app_spec_guard.py
============================

沉淀闭环 v2 · 刀① · app 创建/更新的结构校验守卫 (2026-06-10)

为什么有这个模块
------------------
2026-06-09 用户做视频 8 小时的复盘结论: app 的 system_prompt 是自由文本 ·
LLM 每次自由发挥 · 质量漂移; 而 ui_form_schema 是硬 schema · 每次都填得稳。
=> 把"必须有哪些部分"做成硬结构 · "每部分写什么"留给 LLM 发挥。

强制原理 (不靠自觉 · 靠咽喉):
  create_app / update_app / WebUI POST 全走 workshop_assets.save_app() ·
  save_app 调本模块校验 · 不合规 => ValueError 携带填写模板 · LLM 照模板重试。
  范本 = GUARD tier (python_exec 缺 risk_explanation 即拦下提示重调 · 已稳定运行)。

校验范围
--------
1. 六段结构 (agentic 新 app 硬性 · 老 app 宽限只警告 · scripted 豁免——LLM 不读它的 prompt):
   ① 角色 ② 输入 ③ 动作 ④ 输出规范 ⑤ 坑清单 ⑥ 资产引用(声明了 asset_slots 才必须)
2. 产出隔离: system_prompt / exec_template 里出现 outputs/app-xxxxxxxx 路径时 ·
   必须等于自己的 app_id (治 2026-06-09 视频串进语音 app 目录的根)
3. asset_slots 配置槽 schema (用户个性资产声明: IP 图 / 风格参考 / voice 等)

宽限策略
--------
- 新 app (磁盘上无同 id 文件): 严格 · 不合规拒绝落盘
- 老 app 更新 (已存在且 spec_version < 2): 只警告不拦 · 警告随返回值带回给 LLM ·
  鼓励"补考" · 一旦补齐六段则升 spec_version=2 · 此后按严格执行
"""

from __future__ import annotations

import json
import re


SPEC_VERSION = 2  # 通过六段校验的 app 标记 · 老 app 缺省视为 1

# 六段 · 每段允许的别名 (markdown 标题行里含其一即认)
_SECTION_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("角色", ("角色", "身份")),
    ("输入", ("输入",)),
    ("动作", ("动作", "步骤", "流程")),
    ("输出规范", ("输出",)),  # "输出规范" 含 "输出" · 包含匹配即可
    ("坑清单", ("坑清单", "关键坑", "已知坑", "注意事项")),
]
_ASSET_SECTION = ("资产引用", ("资产",))

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*(.+)$", re.MULTILINE)
_OUTPUTS_APP_RE = re.compile(r"outputs[/\\](app-[0-9a-f]{8})", re.IGNORECASE)

_VALID_SLOT_TYPES = {"text", "json", "images", "file"}
_SLOT_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_ORIGIN_RE = re.compile(r"^(?:app-[0-9a-f]{8}|_shared)$")


def validate_asset_slots(raw: object) -> list[dict]:
    """规范化 + 校验 asset_slots · 不合法抛 ValueError

    每个槽 = 这个 app 声明"我需要用户提供的个性资产"(IP 图/风格参考/voice 等)。
    真值不存这里——存 workshop_registry (data/workshop/assets/<app_id>.json) ·
    这里只是声明 · WebUI 配置页按声明渲染。

    保留字段 (修补·之前 origin/required 被静默丢):
      - name (必填) · type · label · help
      - origin (可空): "_shared" 或 "app-xxxxxxxx" · 标这个槽的真值在哪个 namespace 下
                       · 缺省 = 槽属于本 app 私有 (用本 app id 当 namespace)
      - required (bool · 默认 False): 真值缺失时 app 跑会不会硬挡 (现在还没真挡 · 是 hint)
    """
    if raw is None or raw == "":
        return []
    if not isinstance(raw, list):
        raise ValueError("asset_slots must be a list of slot dicts")
    if len(raw) > 12:
        raise ValueError(f"asset_slots too long: {len(raw)} (max 12)")

    seen: set[str] = set()
    out: list[dict] = []
    for i, slot in enumerate(raw):
        if not isinstance(slot, dict):
            raise ValueError(f"asset_slots[{i}] must be a dict")
        name = str(slot.get("name") or "").strip()
        if not name or not _SLOT_NAME_RE.match(name):
            raise ValueError(
                f"asset_slots[{i}].name invalid · must match [a-zA-Z_][a-zA-Z0-9_]* · got {name!r}"
            )
        if name in seen:
            raise ValueError(f"asset_slots duplicate name: {name}")
        seen.add(name)
        stype = (slot.get("type") or "text").strip().lower()
        if stype not in _VALID_SLOT_TYPES:
            raise ValueError(
                f"asset_slots[{i}].type '{stype}' invalid · must be one of {sorted(_VALID_SLOT_TYPES)}"
            )
        cleaned = {
            "name": name,
            "type": stype,
            "label": str(slot.get("label") or name),
        }
        if slot.get("help"):
            cleaned["help"] = str(slot["help"])
        if slot.get("origin"):
            origin = str(slot["origin"]).strip()
            if not _ORIGIN_RE.match(origin):
                raise ValueError(
                    f"asset_slots[{i}].origin invalid · must be '_shared' or 'app-xxxxxxxx' · got {origin!r}"
                )
            cleaned["origin"] = origin
        if "required" in slot:
            cleaned["required"] = bool(slot["required"])
        out.append(cleaned)
    return out


def _headings(text: str) -> list[str]:
    return [m.group(1).strip() for m in _HEADING_RE.finditer(text or "")]


def _missing_sections(system_prompt: str, *, need_asset_section: bool) -> list[str]:
    heads = _headings(system_prompt)
    joined = "\n".join(heads)
    missing: list[str] = []
    checks = list(_SECTION_ALIASES)
    if need_asset_section:
        checks.append(_ASSET_SECTION)
    for canonical, aliases in checks:
        if not any(a in joined for a in aliases):
            missing.append(canonical)
    return missing


def _foreign_output_paths(payload: dict) -> list[str]:
    """找出 system_prompt / exec_template 里指向【别的 app】outputs 目录的路径"""
    own = (payload.get("id") or "").strip().lower()
    blobs = [payload.get("system_prompt") or ""]
    tpl = payload.get("exec_template")
    if tpl:
        try:
            blobs.append(json.dumps(tpl, ensure_ascii=False))
        except (TypeError, ValueError):
            pass
    bad: list[str] = []
    for blob in blobs:
        for m in _OUTPUTS_APP_RE.finditer(blob):
            ref = m.group(1).lower()
            if ref != own and ref not in bad:
                bad.append(ref)
    return bad


def validate_app_payload(payload: dict, prev: dict | None) -> tuple[list[str], list[str], bool]:
    """校验最终 payload · 返回 (errors, warnings, strict_ok)

    Args:
        payload: save_app 拼好的最终 payload (含 id / system_prompt / exec_kind / asset_slots)
        prev:    磁盘上已有的旧 json (None = 新建)

    Returns:
        errors:    非空则 save_app 必须拒绝落盘
        warnings:  放行但要带回给调用方 (老 app 宽限项)
        strict_ok: 六段+路径全过 => 可标 spec_version=2
    """
    errors: list[str] = []
    warnings: list[str] = []

    is_new = prev is None
    prev_spec_version = int((prev or {}).get("spec_version") or 1)
    scripted = (payload.get("exec_kind") or "agentic") == "scripted"

    # ── 1. 产出隔离 (串目录是 2026-06-09 的真实事故 · 最高优先) ──
    foreign = _foreign_output_paths(payload)
    if foreign:
        msg = (
            f"产出隔离违规: system_prompt/exec_template 引用了别的 app 的产出目录 {foreign} · "
            f"本 app 产出只能写 data/workshop/outputs/{payload.get('id')}/ · "
            "需要别的 app 的产出请通过工作流上游输出 (upstream) 传入 · 或只读引用并注明"
        )
        if is_new or prev_spec_version >= SPEC_VERSION:
            errors.append(msg)
        else:
            warnings.append(msg)

    # ── 2. 六段结构 (scripted 豁免: 它的 prompt LLM 不读) ──
    sections_ok = True
    if not scripted:
        missing = _missing_sections(
            payload.get("system_prompt") or "",
            need_asset_section=bool(payload.get("asset_slots")),
        )
        if missing:
            sections_ok = False
            msg = f"system_prompt 缺标准段落 (markdown 标题): {' / '.join(missing)}"
            if is_new or prev_spec_version >= SPEC_VERSION:
                errors.append(msg)
            else:
                warnings.append(msg + " · 老 app 宽限放行 · 建议尽快补齐升级到 spec_version=2")

    strict_ok = sections_ok and not foreign
    return errors, warnings, strict_ok


def render_reject(errors: list[str], app_id: str | None) -> str:
    """拒绝信息 = 错误清单 + 填写模板 · LLM 拿到后照模板重试 (GUARD 同款体验)"""
    aid = app_id or "<app_id>"
    err_lines = "\n".join(f"  - {e}" for e in errors)
    return (
        "🔴 app 落盘被内核拒绝 (沉淀闭环 v2 · 结构校验):\n"
        f"{err_lines}\n\n"
        "请按下面模板补齐 system_prompt 后重新调用同一个工具 (六段结构 · 标题措辞可微调 · 段内内容自由发挥):\n"
        "```markdown\n"
        "## 角色\n"
        "(一句话: 这个 app 是干什么的)\n\n"
        "## 输入\n"
        "(表单字段含义 / 上游输入说明)\n\n"
        "## 动作\n"
        "(步骤化的执行流程)\n\n"
        "## 输出规范\n"
        f"(产出一律写 data/workshop/outputs/{aid}/ · 命名规则 · 给用户的展示方式)\n\n"
        "## 坑清单\n"
        "(踩过的坑 · 初建可写 '暂无' · 但段落必须在 · 以后迭代往这里沉淀)\n\n"
        "## 资产引用 (声明了 asset_slots 才需要)\n"
        "(说明运行时读哪些资产槽 · 例: 配音前先读 voice 槽的 active 值)\n"
        "```\n"
        "另: 如声明用户个性资产 · 用 asset_slots 字段 · 例:\n"
        '  asset_slots: [{"name": "voice", "type": "json", "label": "声音克隆(active+versions)"}]\n'
        "  真值由 manage_app_asset 工具落 data/workshop/assets/<app_id>.json · 不写进 prompt"
    )
