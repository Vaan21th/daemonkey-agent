"""
workers/plugins_index.py
=========================

卷二十九 · 插件库
卷三十三补丁 · added_at + 自动翻译

OPUS 当前注册的所有工具的索引——给 WebUI 🧩 插件库维度用。

新增能力：
- added_at: 从 agent_tools/<name>.py 文件 ctime 推断"何时新增的"
- description_zh: 自动检测英文描述 + 调便宜模型翻译 + cache
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("opus.plugins")


_TIER_LABELS = {
    "auto": "AUTO · 自动执行",
    "confirm": "CONFIRM · 需 BRO 确认",
    "guard": "GUARD · 严格审核",
}


ROOT = Path(__file__).resolve().parent.parent
AGENT_TOOLS_DIR = ROOT / "agent_tools"
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
TRANSLATIONS_FILE = DATA_DIR / "plugin_translations.json"
PLUGIN_META_OVERRIDE = DATA_DIR / "plugin_meta_override.json"


# ──────────────────────────────────────────────────────────
# added_at · 工具新增时间
# ──────────────────────────────────────────────────────────

def _load_meta_overrides() -> dict:
    """BRO 可以在 data/plugin_meta_override.json 手动覆盖某个工具的 added_at

    格式：{"<tool_name>": {"added_at": "2026-05-15", "note": "..."}}
    """
    if not PLUGIN_META_OVERRIDE.exists():
        return {}
    try:
        return json.loads(PLUGIN_META_OVERRIDE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("plugin_meta_override.json 损坏·忽略: %s", e)
        return {}


_OVERRIDES_CACHE: Optional[dict] = None


def _added_at_for(tool_name: str) -> str:
    """推断工具的新增日期 (YYYY-MM-DD)

    优先级：
      1. data/plugin_meta_override.json 里手动指定
      2. agent_tools/<tool_name>.py 文件 ctime
      3. 试常见后缀变体（_tool / _op 去掉再试）
      4. 兜底 unknown
    """
    global _OVERRIDES_CACHE
    if _OVERRIDES_CACHE is None:
        _OVERRIDES_CACHE = _load_meta_overrides()

    ov = (_OVERRIDES_CACHE.get(tool_name) or {}).get("added_at")
    if ov:
        return ov

    # 尝试一组文件名变体（tool_name 跟文件名不总是一致·比如 mcp_call_tool → mcp_call.py）
    candidates = [tool_name]
    for suffix in ("_tool", "_op", "_action"):
        if tool_name.endswith(suffix):
            candidates.append(tool_name[: -len(suffix)])

    for cand in candidates:
        path = AGENT_TOOLS_DIR / f"{cand}.py"
        if path.exists():
            try:
                ts = path.stat().st_ctime
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            except Exception:
                continue
    return ""


# ──────────────────────────────────────────────────────────
# 描述翻译 · 英文 description → 中文 · 带 cache
# ──────────────────────────────────────────────────────────

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]")


def _chinese_ratio(text: str) -> float:
    if not text:
        return 0.0
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    cjk = sum(1 for c in chars if _CJK_RE.match(c))
    return cjk / len(chars)


def _is_mostly_english(text: str, threshold: float = 0.25) -> bool:
    """中文比例 < threshold 视为英文为主"""
    return _chinese_ratio(text) < threshold


def _hash_desc(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _load_translation_cache() -> dict:
    if not TRANSLATIONS_FILE.exists():
        return {"version": 1, "entries": {}}
    try:
        return json.loads(TRANSLATIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "entries": {}}


def _save_translation_cache(cache: dict) -> None:
    tmp = TRANSLATIONS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(TRANSLATIONS_FILE)


_TRANSLATE_PROMPT = """请把下面 {n} 条 OPUS 工具描述从英文翻译成中文。

要求：
- 保留所有代码片段 / 工具参数名 / NLP 触发例 / 引用 (用 ` 包围的内容) **原样不译**
- 列举的"Actions / Examples / Triggers"标题翻成中文·内容里的工具名 / 参数名保留英文
- 翻译要简洁专业·忠实原意·不要意译过头
- 输出严格的 JSON 数组·**不要 markdown 围栏 · 不要前后任何文字**
- 数组长度必须 = {n} · i 字段对应输入序号

输出格式:

[
  {{"i": 0, "description_zh": "..."}},
  {{"i": 1, "description_zh": "..."}},
  ...
]

输入:

{items_block}"""


def _get_translator():
    """构造翻译用 client · 复用 OPUS_BASE_URL/API_KEY · 默认用 deepseek-chat"""
    try:
        import openai
    except ImportError:
        return None, None
    base_url = (os.environ.get("OPUS_BASE_URL") or "").strip()
    api_key = (os.environ.get("OPUS_API_KEY") or "").strip()
    model = (os.environ.get("OPUS_TRANSLATOR_MODEL") or "deepseek-chat").strip()
    if not base_url or not api_key:
        return None, None
    try:
        client = openai.OpenAI(base_url=base_url, api_key=api_key)
    except Exception as e:
        logger.warning("plugins translator client 起不来: %s", e)
        return None, None
    return client, model


def _translate_descriptions(tasks: list[tuple[str, str]]) -> dict[str, str]:
    """tasks = [(tool_name, desc_en), ...] · 返回 {tool_name: desc_zh}

    带 cache · 缓存命中直接走·没命中才调 LLM
    """
    if not tasks:
        return {}

    cache = _load_translation_cache()
    entries = cache.get("entries") or {}
    out: dict[str, str] = {}
    to_translate: list[tuple[str, str, str]] = []  # (tool_name, desc, hash_key)

    for tool_name, desc in tasks:
        h = _hash_desc(desc)
        cached = entries.get(h)
        if cached and cached.get("description_zh"):
            out[tool_name] = cached["description_zh"]
        else:
            to_translate.append((tool_name, desc, h))

    if not to_translate:
        return out

    client, model = _get_translator()
    if client is None:
        logger.info("plugins translator 未配置·跳过翻译·%d 条留英文", len(to_translate))
        return out

    # 一次最多翻 8 条·防 token 爆 · 控制粒度
    BATCH = 8
    for i in range(0, len(to_translate), BATCH):
        batch = to_translate[i:i + BATCH]
        items_block = ""
        for idx, (_, desc, _) in enumerate(batch):
            # 截断防止超 token · 但每条 500 字差不多够翻
            short = desc.strip()
            if len(short) > 1500:
                short = short[:1500] + "..."
            items_block += f"## {idx}\n{short}\n\n"

        prompt = _TRANSLATE_PROMPT.format(n=len(batch), items_block=items_block)
        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=8000,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": "你是专业的中英翻译·只输出严格 JSON。"},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning("plugins 翻译失败·留英文: %s", e)
            continue

        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
        start = raw.find("[")
        end = raw.rfind("]")
        if start < 0 or end <= start:
            logger.warning("plugins 翻译响应不是 JSON·跳: %s", raw[:200])
            continue
        try:
            arr = json.loads(raw[start:end + 1])
        except Exception as e:
            logger.warning("plugins 翻译 JSON 解析失败: %s", e)
            continue
        if not isinstance(arr, list):
            continue

        for entry in arr:
            if not isinstance(entry, dict):
                continue
            try:
                bi = int(entry.get("i", -1))
            except (TypeError, ValueError):
                continue
            if bi < 0 or bi >= len(batch):
                continue
            zh = (entry.get("description_zh") or "").strip()
            if not zh:
                continue
            tool_name, desc, h = batch[bi]
            out[tool_name] = zh
            entries[h] = {
                "description_zh": zh,
                "translated_at": datetime.now(timezone.utc).isoformat(),
                "model": model,
            }

    cache["entries"] = entries
    try:
        _save_translation_cache(cache)
    except Exception as e:
        logger.warning("save plugin_translations.json failed: %s", e)
    return out


def _describe_schema(schema: dict) -> list[dict]:
    """把 input_schema 提炼成 [{name, type, required, description}] 列表"""
    if not isinstance(schema, dict):
        return []
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    out: list[dict] = []
    for name, info in props.items():
        if not isinstance(info, dict):
            continue
        type_str = info.get("type", "?")
        enum_vals = info.get("enum")
        if enum_vals:
            type_str = f"enum({len(enum_vals)})"
        out.append({
            "name": name,
            "type": type_str,
            "required": name in required,
            "description": (info.get("description") or "").strip()[:200],
            "enum": enum_vals[:8] if enum_vals else None,
        })
    return out


def _first_paragraph(text: str, max_chars: int = 200) -> str:
    """取描述的第一段·避免一坨"""
    if not text:
        return ""
    para = text.strip().split("\n\n")[0]
    if len(para) > max_chars:
        return para[:max_chars] + "…"
    return para


def load_plugins() -> dict:
    """读 agent_tools.REGISTRY 列出所有工具

    分类规则：
      - 按 tier 分: auto / confirm / guard
      - 同 tier 内按名字排
    """
    try:
        from agent_tools import REGISTRY
    except Exception as e:
        logger.exception("failed to import agent_tools")
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total": 0,
            "items": [],
            "error": f"agent_tools 加载失败: {e}",
        }

    items: list[dict] = []
    # 收集需要翻译的工具（description 是英文为主的）
    translation_tasks: list[tuple[str, str]] = []

    for name, spec in sorted(REGISTRY.items()):
        first_para = _first_paragraph(spec.description, max_chars=400)
        full_desc = spec.description or ""
        needs_translation = _is_mostly_english(first_para)
        items.append({
            "name": name,
            "tier": spec.tier,
            "tier_label": _TIER_LABELS.get(spec.tier, spec.tier),
            "description": first_para,
            "description_full": full_desc,
            "description_zh": None,
            "_needs_translation": needs_translation,
            "added_at": _added_at_for(name),
            "params": _describe_schema(spec.input_schema),
            "has_dynamic_classify": spec.classify is not None,
            "category": _categorize(name, spec),
        })
        if needs_translation and full_desc:
            translation_tasks.append((name, full_desc))

    # 翻译（带 cache · 第二次跑就秒回）
    if translation_tasks:
        try:
            translations = _translate_descriptions(translation_tasks)
            for it in items:
                if it["_needs_translation"]:
                    it["description_zh"] = translations.get(it["name"]) or None
        except Exception as e:
            logger.warning("plugins 描述翻译异常·留英文: %s", e)
    # 清理内部字段
    for it in items:
        it.pop("_needs_translation", None)

    # 顺便给"未来插件"留个占位
    future_slots = [
        {
            "name": "(预留 · OPUS 自己写的插件)",
            "tier": None,
            "tier_label": "未来",
            "description": (
                "信息雷达 → 出品工坊·产品开发 → OPUS 用 write_file + shell_exec "
                "自己写一个新的 agent_tools/*.py · 自动 register + 重启 daemon · "
                "新工具就出现在这里 · 这是 OPUS-DAEMON 闭环的最后一环"
            ),
            "params": [],
            "category": "future",
        },
    ]

    by_category: dict[str, list[dict]] = {}
    for it in items:
        by_category.setdefault(it["category"], []).append(it)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(items),
        "items": items,
        "by_category": by_category,
        "future_slots": future_slots,
        "tier_summary": {
            "auto": sum(1 for x in items if x["tier"] == "auto"),
            "confirm": sum(1 for x in items if x["tier"] == "confirm"),
            "guard": sum(1 for x in items if x["tier"] == "guard"),
        },
    }


# 工具分类·让 UI 能分组展示
_CATEGORY_RULES = [
    ("os", lambda n, s: n in {"shell_exec", "open_app", "take_screenshot", "clipboard"}),
    ("file", lambda n, s: n in {"read_file", "write_file", "grep_files", "pdf_read"}),
    ("web", lambda n, s: n in {"web_search", "web_fetch", "browser_fetch", "ssh_remote"}),
    ("studio", lambda n, s: n in {
        "manage_info_source", "generate_report", "draft_studio",
        "expand_trend_to_report", "mine_opportunities", "analyze_feasibility",
        "read_dashboard", "propose_next_move",
    }),
    ("soul", lambda n, s: n in {
        "update_bro_note", "update_self_evolution", "set_emotion",
        "summarize_session", "set_model",
    }),
    ("external", lambda n, s: n in {
        "wechat_send", "client_handoff", "summon_cursor", "mcp_call",
    }),
]


def _categorize(name: str, spec) -> str:
    for cat, rule in _CATEGORY_RULES:
        try:
            if rule(name, spec):
                return cat
        except Exception:
            continue
    return "misc"


CATEGORY_META = {
    "os":       {"label": "系统层",     "icon": "💻", "order": 1},
    "file":     {"label": "文件层",     "icon": "📁", "order": 2},
    "web":      {"label": "外网层",     "icon": "🌐", "order": 3},
    "studio":   {"label": "工作室层",   "icon": "🎬", "order": 4},
    "soul":     {"label": "灵魂层",     "icon": "🧠", "order": 5},
    "external": {"label": "外联层",     "icon": "🔗", "order": 6},
    "misc":     {"label": "其他",       "icon": "·",  "order": 99},
    "future":   {"label": "未来扩展",   "icon": "✨", "order": 100},
}
