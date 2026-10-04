"""会话能力档位 · 解析（wish-16fa5930）· 表在 data/cognition/tool_profiles.json

v2（2026-09-20 · wish-6350cced 装配台）：用户预设 —— 自己存下来的自定义档。
  存 data/cognition/tool_profiles_user.json（与内置分离 · 升级永不覆盖）。
  id 前缀 u- 。profile_list / resolve_profile 自动合并两处。

v3（2026-09-21 · wish-0571fd96 选档卡）：新对话「默认档」—— 用户可把任意档
  （含自设预设）钉为默认，新对话开局自动亮它。存 user 文件顶层 default_id；
  standard = 出厂默认（钉回 standard 即清除）。profile_list 的 default 字段
  动态反映当前默认（前端据此画钉）。
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "data" / "cognition" / "tool_profiles.json"
_USER_PATH = Path(__file__).resolve().parent.parent / "data" / "cognition" / "tool_profiles_user.json"
DEFAULT_ID = "standard"

# wish-e1178ade · 层配置：预设可选「装哪几段」（键与 soul_loader.SECTION_MARKS 一致）
_SOUL_SEG_KEYS = ("structure", "identity", "rules", "const_common", "const_local",
                  "runtime", "catalog", "memories", "notebook", "evolution")


def _load() -> dict:
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _load_user() -> dict:
    try:
        d = json.loads(_USER_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _valid_pid(pid) -> bool:
    """这个 id 在内置或用户预设里存在？（默认档校验用）"""
    if not isinstance(pid, str) or not pid:
        return False
    return pid in (_load().get("profiles") or {}) or pid in (_load_user().get("presets") or {})


def get_user_default():
    """用户钉的「新对话默认档」id · 没钉过 / 已失效 → None（调用方回落 standard）。"""
    pid = _load_user().get("default_id")
    return pid if _valid_pid(pid) else None


def set_user_default(pid: str):
    """钉「新对话默认档」→ (ok, error)。钉回 standard = 恢复出厂默认（清掉自定义）。"""
    if not _valid_pid(pid):
        return False, "没找到这个档位"
    ud = _load_user()
    if pid == DEFAULT_ID:
        ud.pop("default_id", None)
    else:
        ud["default_id"] = pid
    ud.setdefault("note", "用户自定义预设（装配台存下）· 与内置分离 —— 升级永不覆盖")
    ud["updated"] = date.today().isoformat()
    _USER_PATH.write_text(json.dumps(ud, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, None


def _prefix_tok(pid) -> int:
    """该档每轮前缀 ≈ tok（灵魂+目录 sp → tiktoken + 工具块按真实 API 序列化计数）。
    BRO 2026-09-21：选档卡悬停看「前缀数值」用。口径与 /context-prefix 生成器一致（wish-811eb5f5）。
    失败返 0（前端不显示）——不缓存：sp_for_profile 自带 _SP_CACHE，覆盖/预设改了立即反映。"""
    try:
        from daemon_runtime import sp_for_profile
        sp = sp_for_profile(pid or "") or ""
        import tiktoken
        _enc = tiktoken.get_encoding("cl100k_base")

        def _t(s):
            return len(_enc.encode(s)) if s else 0

        tot = _t(sp)
        try:
            _pid2, toolset = resolve_profile(pid or "")
            import json as _json
            from tool_loop import to_openai_tools
            from agent_tools._tool_catalog import visible_specs
            specs = visible_specs(toolset)   # toolset=None → 默认口径（CORE）· 与 chat.py 生成器同调用式
            tot += _t(_json.dumps(to_openai_tools(specs), ensure_ascii=False))
        except Exception:
            pass
        return tot
    except Exception:
        return 0


def profile_list() -> list:
    """给 UI 的档位清单（不带工具名全文）· 内置 + 用户预设（user: true）。
    default 字段 = 当前「新对话默认档」（wish-0571fd96 · 动态，非静态出厂值）。"""
    from agent_tools._tool_catalog import CORE
    cur_def = get_user_default() or DEFAULT_ID
    out = []
    for pid, v in ((_load().get("profiles") or {})).items():
        if not isinstance(v, dict):
            continue
        t = v.get("tools")
        _ov = _pick_override(pid)
        _ov_used = isinstance(_ov, dict) and bool(_ov.get("tools"))
        if _ov_used:
            t = _ov["tools"]
        n = len(CORE) if t == "CORE" else (len(t) if isinstance(t, list) else 0)
        _lay = (_ov.get("layers") if (_ov_used and isinstance(_ov, dict) and "layers" in _ov) else v.get("layers"))
        out.append({"id": pid, "name": v.get("name") or pid,
                    "desc": v.get("desc") or "", "size": v.get("size") or "",
                    "count": n, "default": (pid == cur_def),
                    "layers": _lay, "overridden": bool(_ov_used), "tok": _prefix_tok(pid)})
    for pid, v in ((_load_user().get("presets") or {})).items():
        if not isinstance(v, dict):
            continue
        t = v.get("tools")
        n = len(CORE) if t == "CORE" else (len(t) if isinstance(t, list) else 0)
        out.append({"id": pid, "name": v.get("name") or pid,
                    "desc": v.get("desc") or "", "size": v.get("size") or "",
                    "count": n, "default": (pid == cur_def), "user": True,
                    "layers": v.get("layers"), "tok": _prefix_tok(pid)})
    return out


def resolve_profile(pid):
    """返 (档位 id, 工具集合 | None)。None = 不设限（standard = CORE 全量）。
    查序：内置（含用户覆盖）→ 用户预设 → 兜底 standard。"""
    d = (_load().get("profiles") or {})
    p = d.get(pid) if isinstance(pid, str) and pid else None
    _builtin_hit = isinstance(p, dict)
    if not isinstance(p, dict) and isinstance(pid, str) and pid:
        p = (_load_user().get("presets") or {}).get(pid)
    if _builtin_hit and isinstance(p, dict):
        _ov = _pick_override(pid)
        if isinstance(_ov, dict) and _ov.get("tools"):
            p = {**p, "tools": _ov["tools"]}   # wish-36ef3ea9 续 · 用户覆盖优先
    if not isinstance(p, dict):
        p, pid = d.get(DEFAULT_ID), DEFAULT_ID
    if not isinstance(p, dict):
        return DEFAULT_ID, None
    t = p.get("tools")
    if t == "CORE" or not t:
        return pid, None
    # 2026-09-18 修 (BRO 拍)：原为 `x in CORE` —— 名单里的非核心工具被静默丢掉
    # （闲聊档的 generate_image 出不了图 · 写作档 16 件只摊开 12 件）。
    # 档位名单可以放**任意** REGISTRY 工具。
    # 约束：名单长度须 ≤ _TIGHT_MAX(40)，超了会走 visible_names 的 `CORE ∩ allowed`
    # 分支（那是「权限收窄」通道的有意设计·见 tests/test_tool_catalog.py），档位会被截。
    from agent_tools import REGISTRY as _REG
    names = [x for x in t if isinstance(x, str) and x in _REG]
    return pid, set(names)


def profile_soul_layers(pid):
    """取一个档位的「层配置」（装哪几段 · wish-e1178ade）。

    返回 list[str] = 要装的段；None = 全装 / 未配置 / 档位不存在。
    ⚠ 空列表 [] 合法（全不装 · 实验档）——与 None（全装）严格区分。"""
    d = (_load().get("profiles") or {})
    p = d.get(pid) if isinstance(pid, str) and pid else None
    _builtin_hit = isinstance(p, dict)
    if not isinstance(p, dict) and isinstance(pid, str) and pid:
        p = (_load_user().get("presets") or {}).get(pid)
    if not isinstance(p, dict):
        return None
    if _builtin_hit:
        _ov = _pick_override(pid)
        if isinstance(_ov, dict):   # 有覆盖 → layers 以覆盖为准（缺键 = 全装）
            lay = _ov.get("layers")
            if not isinstance(lay, list):
                return None
            lay = [x for x in dict.fromkeys(str(i) for i in lay) if x in _SOUL_SEG_KEYS]
            if set(lay) >= set(_SOUL_SEG_KEYS):
                return None
            return lay
    lay = p.get("layers")
    if not isinstance(lay, list):
        return None
    lay = [x for x in dict.fromkeys(str(i) for i in lay) if x in _SOUL_SEG_KEYS]
    if set(lay) >= set(_SOUL_SEG_KEYS):
        return None
    return lay


def profile_soul_thickness(pid) -> str:
    """档位的「灵魂厚度」（thin / standard / full）· 没配 = ""（当 standard 处理）。

    BRO 2026-10-05 报：闲聊档写着 thin、实际下发全量 —— 这个字段以前没人读过它。
    """
    d = (_load().get("profiles") or {})
    p = d.get(pid) if isinstance(pid, str) and pid else None
    if not isinstance(p, dict) and isinstance(pid, str) and pid:
        p = (_load_user().get("presets") or {}).get(pid)
    if not isinstance(p, dict):
        return ""
    return str(p.get("soul_thickness") or "").strip().lower()


def suggest_profile() -> dict:
    """按当前模型给一个建议档（原型缺口③ · 本地小模型 → 闲聊档）。

    只在**本机端点**（LM Studio / Ollama 等自跑模型）时建议 chat：这类模型
    窗口小、在 138 件工具前容易选错轨（实测 8B 只给 8 件仍挑错）。
    云端模型不猜（返 {}）—— 弱云端模型要不要也算，等 BRO 拍。

    返回 {} = 不建议；否则 {"id", "why", "model", "local"}。前端只拿它做
    选档卡的**预选**，用户点一下就覆盖，不写 meta、不改行为。
    """
    try:
        from workers.provider_configs import get_active_config
        cfg = get_active_config(include_key=False) or {}
    except Exception:
        return {}
    base = str(cfg.get("base_url") or "").strip().lower()
    if not base:
        return {}
    host = base.split("//", 1)[-1].split("/", 1)[0].rsplit("@", 1)[-1]
    host = host.rsplit(":", 1)[0].strip("[]")
    if host not in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
        return {}
    return {"id": "chat", "why": "检测到本机模型 · 建议闲聊档",
            "model": str(cfg.get("model") or ""), "local": True}


def save_user_preset(d: dict):
    """存一个用户预设 → (id, error)。校验：名字 1-30 · 工具 1-40 件且都在库。"""
    from agent_tools import REGISTRY
    name = str(d.get("name") or "").strip()[:30]
    if not name:
        return None, "给预设起个名字"
    tools, seen = [], set()
    for t in (d.get("tools") or []):
        if isinstance(t, str) and t in REGISTRY and t not in seen:
            tools.append(t)
            seen.add(t)
    if not tools:
        return None, "一件工具都没勾 —— 先勾几件再存"
    if len(tools) > 40:
        return None, f"勾了 {len(tools)} 件 —— 档位最多 40 件（超了会被截断），挑一挑"
    th = d.get("soul_thickness") or "standard"
    if th not in ("thin", "standard", "companion"):
        th = "standard"
    # wish-e1178ade · 层配置：勾了哪几段（None = 全装）。只认 SECTION_MARKS 的键；
    # 全集归一为 None（「全勾」= 跟默认走·不钉死现状）。空列表合法（全不装·实验档）。
    layers = d.get("layers")
    if layers is not None:
        if not isinstance(layers, list):
            return None, "layers 要是列表"
        layers = [x for x in dict.fromkeys(str(i) for i in layers) if x in _SOUL_SEG_KEYS]
        if set(layers) >= set(_SOUL_SEG_KEYS):
            layers = None
    ud = _load_user()
    presets = ud.get("presets")
    if not isinstance(presets, dict):
        presets = {}
    pid = "u-" + uuid.uuid4().hex[:8]
    presets[pid] = {
        "name": name,
        "desc": str(d.get("desc") or "").strip()[:80],
        "tools": tools,
        "soul_thickness": th,
        "based_on": d.get("based_on") or None,
        "size": "小",
        "created": date.today().isoformat(),
    }
    if layers is not None:
        presets[pid]["layers"] = layers
    # wish-36ef3ea9 续 · 初始快照（「回到最初」用 · 创建时的首版，之后不被编辑覆盖）
    _snap = {"tools": list(tools), "name": name}
    if layers is not None:
        _snap["layers"] = list(layers)
    presets[pid]["origin"] = _snap
    ud["presets"] = presets
    ud["version"] = ud.get("version") or 1
    ud["updated"] = date.today().isoformat()
    ud.setdefault("note", "用户自定义预设（装配台存下）· 与内置分离 —— 升级永不覆盖")
    _USER_PATH.write_text(json.dumps(ud, ensure_ascii=False, indent=2), encoding="utf-8")
    return pid, None


def delete_user_preset(pid: str):
    """删一个用户预设 → (ok, error)。内置拒删。"""
    if not isinstance(pid, str) or not pid.startswith("u-"):
        return False, "只能删自己的预设（u- 开头）"
    ud = _load_user()
    presets = ud.get("presets") or {}
    if pid not in presets:
        return False, "没找到这个预设"
    presets.pop(pid, None)
    if ud.get("default_id") == pid:
        ud.pop("default_id", None)   # 钉着的默认被删 → 自动回落出厂默认（wish-0571fd96）
    ud["presets"] = presets
    ud["updated"] = date.today().isoformat()
    _USER_PATH.write_text(json.dumps(ud, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, None


# ── wish-36ef3ea9 续 · 档位/预设编辑（BRO 2026-09-21：「保存当时的状态 + 回到最初的初始状态」）──
# 内置档改不了源文件（升级会覆盖）——修改存 tool_profiles_user.json 的 overrides 区；
# 预设直接更新本体，另留创建时快照 origin（可反复还原）。

def _pick_override(pid):
    """内置档的用户覆盖（有则返回 dict，否则 None）。"""
    ov = (_load_user().get("overrides") or {}).get(pid)
    return ov if isinstance(ov, dict) else None


def _valid_tool_list(tools):
    """工具名校验（同 save_user_preset 口径）→ (clean, error)。"""
    from agent_tools import REGISTRY
    out, seen = [], set()
    for t in (tools or []):
        if isinstance(t, str) and t in REGISTRY and t not in seen:
            out.append(t)
            seen.add(t)
    if not out:
        return None, "一件工具都没勾 —— 先勾几件再存"
    if len(out) > 40:
        return None, f"勾了 {len(out)} 件 —— 档位最多 40 件（超了会被截断），挑一挑"
    return out, None


def _valid_layers(layers):
    """层配置校验（同 save_user_preset 口径）→ (clean|None, error)。None = 全装。"""
    if layers is None:
        return None, None
    if not isinstance(layers, list):
        return None, "layers 要是列表"
    clean = [x for x in dict.fromkeys(str(i) for i in layers) if x in _SOUL_SEG_KEYS]
    if set(clean) >= set(_SOUL_SEG_KEYS):
        return None, None
    return clean, None


def save_builtin_override(pid: str, d: dict):
    """把当前编辑存成对「内置档」的用户覆盖 → (ok, error)。

    存进 tool_profiles_user.json（升级永不覆盖）；读侧 resolve/layers/list 自动优先。"""
    if not isinstance(pid, str) or pid not in (_load().get("profiles") or {}):
        return False, "只有内置档位能存覆盖（预设请直接改本体）"
    tools, err = _valid_tool_list(d.get("tools"))
    if err:
        return False, err
    layers, err = _valid_layers(d.get("layers"))
    if err:
        return False, err
    ov = {"tools": tools, "saved": date.today().isoformat()}
    if layers is not None:
        ov["layers"] = layers
    ud = _load_user()
    ovs = ud.get("overrides")
    if not isinstance(ovs, dict):
        ovs = {}
    ovs[pid] = ov
    ud["overrides"] = ovs
    ud.setdefault("note", "用户自定义预设（装配台存下）· 与内置分离 —— 升级永不覆盖")
    ud["updated"] = date.today().isoformat()
    _USER_PATH.write_text(json.dumps(ud, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, None


def clear_builtin_override(pid: str):
    """还原出厂：删掉内置档的用户覆盖 → (ok, error)。"""
    if not isinstance(pid, str) or pid not in (_load().get("profiles") or {}):
        return False, "只有内置档位有出厂状态"
    ud = _load_user()
    ovs = ud.get("overrides")
    if not isinstance(ovs, dict) or pid not in ovs:
        return False, "这个档没有被改过，本来就是出厂状态"
    ovs.pop(pid, None)
    ud["overrides"] = ovs
    ud["updated"] = date.today().isoformat()
    _USER_PATH.write_text(json.dumps(ud, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, None


def update_user_preset(pid: str, d: dict):
    """编辑一个用户预设：更新当前定义（保留 created；首次编辑自动补 origin 快照）→ (ok, error)。"""
    if not isinstance(pid, str) or not pid.startswith("u-"):
        return False, "只能编辑自己的预设（u- 开头）"
    ud = _load_user()
    presets = ud.get("presets") or {}
    p = presets.get(pid)
    if not isinstance(p, dict):
        return False, "没找到这个预设"
    tools, err = _valid_tool_list(d.get("tools"))
    if err:
        return False, err
    layers, err = _valid_layers(d.get("layers"))
    if err:
        return False, err
    if not isinstance(p.get("origin"), dict):   # 老预设首编 → 把编辑前版本存成初始快照
        _osnap = {"tools": list(p.get("tools") or []), "name": p.get("name") or ""}
        if isinstance(p.get("layers"), list):
            _osnap["layers"] = list(p["layers"])
        p["origin"] = _osnap
    p["tools"] = tools
    if layers is None:
        p.pop("layers", None)
    else:
        p["layers"] = layers
    if isinstance(d.get("name"), str) and d.get("name", "").strip():
        p["name"] = d["name"].strip()[:30]
    if isinstance(d.get("desc"), str):
        p["desc"] = d["desc"].strip()[:80]
    presets[pid] = p
    ud["presets"] = presets
    ud["updated"] = date.today().isoformat()
    _USER_PATH.write_text(json.dumps(ud, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, None


def update_user_preset_meta(pid: str, d: dict):
    """只改预设的名称 / 描述 → (ok, error)。wish-4607fd37（BRO 2026-09-28）。

    窄通道：碰不到 tools / layers / origin —— 「改个名字」不该动勾选名单，
    也不该污染「回到最初」的初始快照（走 update_user_preset 时 tools 为空会被拒）。
    """
    if not isinstance(pid, str) or not pid.startswith("u-"):
        return False, "只能改自己的预设（u- 开头）"
    ud = _load_user()
    presets = ud.get("presets") or {}
    p = presets.get(pid)
    if not isinstance(p, dict):
        return False, "没找到这个预设"
    name = str(d.get("name") or "").strip()
    if not name:
        return False, "名字不能空着"
    p["name"] = name[:30]
    if isinstance(d.get("desc"), str):
        p["desc"] = d["desc"].strip()[:80]
    presets[pid] = p
    ud["presets"] = presets
    ud["updated"] = date.today().isoformat()
    _USER_PATH.write_text(json.dumps(ud, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, None


def restore_user_preset(pid: str):
    """预设回到「最初创建时的状态」（origin 快照）→ (ok, error)。"""
    if not isinstance(pid, str) or not pid.startswith("u-"):
        return False, "只能还原自己的预设（u- 开头）"
    ud = _load_user()
    presets = ud.get("presets") or {}
    p = presets.get(pid)
    if not isinstance(p, dict):
        return False, "没找到这个预设"
    o = p.get("origin")
    if not isinstance(o, dict):
        return False, "这个预设还没有初始快照（它创建之后没被编辑过）"
    p["tools"] = list(o.get("tools") or [])
    if isinstance(o.get("layers"), list):
        p["layers"] = list(o["layers"])
    else:
        p.pop("layers", None)
    if o.get("name"):
        p["name"] = o["name"]
    presets[pid] = p
    ud["presets"] = presets
    ud["updated"] = date.today().isoformat()
    _USER_PATH.write_text(json.dumps(ud, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, None
