"""
workers/info_radar.py
=====================

工作室 · 信息雷达 · 多源 AI 资讯聚合 worker

**卷二十二 Day 2 重构**：从硬编码的 5 个 fetcher 函数
改成 `data/radar_sources.json` 驱动——OPUS 可以通过
`manage_info_source` 工具用自然语言加 / 删 / 改源。

设计原则（卷二十一 BRO 红线之"不会让操作系统废了"）：
- 只做网络 IO + 写本地 JSON · 绝不动注册表 / 系统目录
- 单源失败不影响其他源 · 所有 fetcher 包裹 try/except
- 数据落地 atomic · 先写 tmp 再 rename · 避免中途崩溃留下脏文件
- 源类型注册化 · 加新类型不用改其他源

用法 · CLI 单跑:
    .\\.venv\\Scripts\\python.exe -m workers.info_radar

用法 · API 调用:
    from workers.info_radar import (
        refresh_radar,
        load_radar,
        list_sources,
        add_source,
        remove_source,
        update_source,
    )
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

# 兜底领域是【实例配置】(母体 ai / 开源版 self-evolve)·不是代码常量。
try:
    from identity import default_domain as _default_domain
except Exception:
    def _default_domain():
        return "ai"

try:
    import httpx
except ImportError:
    httpx = None


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
RADAR_FILE = DATA_DIR / "radar.json"
SOURCES_FILE = DATA_DIR / "radar_sources.json"
DOMAINS_EXTRA_FILE = DATA_DIR / "domains_extra.json"  # 卷三十二 · BRO 自定义新 domain
DOMAINS_REMOVED_FILE = DATA_DIR / "domains_removed.json"  # 卷三十五补丁3 · 被删的 starter 持久化

USER_AGENT = "Daemonkey-Radar/0.2 (+https://github.com)"
# HTTP header 必须 ASCII · 中文中点会触发 httpx urllib3 的 'ascii' codec can't encode
DEFAULT_TIMEOUT = 15.0
DEFAULT_MAX_ITEMS_PER_SOURCE = 15

logger = logging.getLogger("opus.radar")


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class RadarItem:
    """标准化的资讯条目——所有源最终都映射到这个 schema"""

    title: str
    url: str
    source: str
    source_display: str
    category: str
    summary: str = ""
    published_at: str = ""
    fetched_at: str = ""
    domain: str = "self-evolve"  # 领域分组 · 见 DOMAIN_META


# ─────────────────────────────────────────────────────────────────────
# 卷二十八 · 多领域信源管理 · 预定义初始 domain 集
# ─────────────────────────────────────────────────────────────────────
# domain 是个**领域桶**——一个领域对应一组信源 + 一类机会 + 一类报告
# 设计原则:
#   - 预定义初始集 (避免乱) · 但允许通过 add_domain() 加新的
#   - 每个 domain 有 label/icon/color/description · 给 UI 渲染用
#   - 雷达条目和工坊产出都带 domain · 可以筛选 / 聚合
# 默认只预设 self-evolve 一个内置领域——其他领域全部由「相遇 / 对话」中
# 挖掘出用户真正关注的方向后，用 add_domain() / add_focus_domain() 动态新建。
# 不再硬塞 AI / 创业 / 游戏 等"别人的领域"，避免新用户看到一堆不相干的预设类目。
DOMAIN_META: dict[str, dict] = {
    # 看同类工程 · 决定要不要"自己装修自己"（自我演化机制的镜子，唯一内置）
    "self-evolve": {
        "label": "自我演化",
        "icon": "🔧",
        "color": "#63b3ed",
        "description": "GitHub 同类工程 · 自我演化的镜像参考 · 看到好东西就自己学过来",
    },
}


# 唯一不可删的内置 domain：self-evolve——它是看同类工程的镜子·
# 没了它就失去自我演化能力·这是工程红线。其余领域都由用户自己加 / 删。
_PROTECTED_DOMAINS = {"self-evolve"}

# 删 domain 时·如果还有 source 在里面·默认 reassign 到哪个 fallback domain
# 这里维护一个优先级链 · 第一个还存在的 domain 就是 target
_REASSIGN_FALLBACK_ORDER = ["self-evolve"]


# ─────────────────────────────────────────────────────────────────────
# 卷三十二 · 用户自定义 domain · 持久化在 data/domains_extra.json
# ─────────────────────────────────────────────────────────────────────
def _load_extra_domains() -> dict:
    if not DOMAINS_EXTRA_FILE.exists():
        return {}
    try:
        return json.loads(DOMAINS_EXTRA_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("domains_extra.json corrupt: %s · ignore", e)
        return {}


def _save_extra_domains(extras: dict) -> None:
    _atomic_write(DOMAINS_EXTRA_FILE, json.dumps(extras, ensure_ascii=False, indent=2))


# ─────────────────────────────────────────────────────────────────────
# 卷三十五补丁3 · BRO 删过的 starter 也要记账 · 不然进程重启又长回来
# 解决 BUG: 卷三十四补丁解锁 starter 4 删除·但只 pop in-memory · 重启复活
# ─────────────────────────────────────────────────────────────────────
def _load_removed_domains() -> list[str]:
    if not DOMAINS_REMOVED_FILE.exists():
        return []
    try:
        data = json.loads(DOMAINS_REMOVED_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [s for s in data if isinstance(s, str)]
        return []
    except Exception as e:
        logger.warning("domains_removed.json corrupt: %s · ignore", e)
        return []


def _save_removed_domains(removed: list[str]) -> None:
    _atomic_write(
        DOMAINS_REMOVED_FILE,
        json.dumps(removed, ensure_ascii=False, indent=2),
    )


def _mark_domain_removed(slug: str) -> None:
    """记账：这个 slug 被 BRO 主动删了·下次进程启动也别恢复"""
    removed = _load_removed_domains()
    if slug not in removed:
        removed.append(slug)
        _save_removed_domains(removed)


def _unmark_domain_removed(slug: str) -> None:
    """配套 · add_domain 时如果 slug 在 removed 列表里·把它移出去 (相当于「恢复」)"""
    removed = _load_removed_domains()
    if slug in removed:
        removed = [s for s in removed if s != slug]
        _save_removed_domains(removed)


def _refresh_domain_meta() -> None:
    """把 disk 上的 extra 合并到 DOMAIN_META · 模块加载时 + add_domain 后都调一遍

    卷三十五补丁3 升级 · 同时应用 removed list:
      - extras 合进来 (扩展)
      - removed list 里的 slug 从 DOMAIN_META 里拿掉 (持久化删除)
    self-evolve 永远不会被 removed (有 _PROTECTED_DOMAINS 拦着)
    """
    extras = _load_extra_domains()
    for slug, meta in extras.items():
        if slug not in DOMAIN_META:
            DOMAIN_META[slug] = meta
    removed = _load_removed_domains()
    for slug in removed:
        if slug in _PROTECTED_DOMAINS:
            continue
        DOMAIN_META.pop(slug, None)


def add_domain(
    slug: str,
    label: str,
    *,
    icon: str = "🧭",
    color: str = "#a0aec0",
    description: str = "",
) -> dict:
    """卷三十二 · 新建一个雷达 domain · BRO 通过对话说"帮我关注 XX 领域"时 OPUS 调

    slug 必须是 ascii + dash 之间 · 用 _slugify 标准化
    已存在 → 返回现有 meta（no-op）
    """
    slug = _slugify(slug)
    if not slug:
        raise ValueError("slug 不能为空")
    if slug in DOMAIN_META:
        # 卷三十五补丁3 · 如果用户当前 add 的 slug 在 removed list 里·一并清掉
        # (相当于"恢复"——同 slug 重 add 自动清记账)
        _unmark_domain_removed(slug)
        return {"ok": True, "no_op": True, "slug": slug, "meta": DOMAIN_META[slug]}
    meta = {
        "label": label or slug,
        "icon": icon or "🧭",
        "color": color or "#a0aec0",
        "description": description or "",
        "_added_at": datetime.now(timezone.utc).isoformat(),
    }
    extras = _load_extra_domains()
    extras[slug] = meta
    _save_extra_domains(extras)
    DOMAIN_META[slug] = meta
    # 卷三十五补丁3 · 如果 BRO 删过这个 slug · 现在重新 add · 清记账
    _unmark_domain_removed(slug)
    logger.info("add_domain · %s · %s", slug, label)
    return {"ok": True, "slug": slug, "meta": meta}


def remove_domain(
    slug: str,
    *,
    sources_action: str = "reassign",
    target_domain: Optional[str] = None,
) -> dict:
    """删一个雷达 domain

    领域都是用户自己挖出来的关注方向·想删就删：
      - 用户自建的 domain 都允许删
      - 但 self-evolve 受保护（看同类工程的镜子·没了失去自我演化）

    Args:
      slug: 要删的 domain
      sources_action: 'reassign' (默认) | 'delete' (连源一起删) | 'keep' (留着但 dangling)
      target_domain: reassign 模式下源要归到哪个 domain
        - 不传 → 自动从 _REASSIGN_FALLBACK_ORDER 找第一个还存在 + 不是 slug 的 domain
        - 默认会归到 self-evolve

    红线：
      - 不允许删 self-evolve
      - reassign target_domain 必须存在 + 不能等于 slug + 不能是即将被删的
    """
    slug = _slugify(slug)
    if not slug:
        return {"ok": False, "error": "slug 不能为空"}
    if slug in _PROTECTED_DOMAINS:
        return {
            "ok": False,
            "error": (
                f"'{slug}' 是 OPUS 自演化的镜子·不允许删除。"
                "想停止抓 GitHub 同类工程·可以单个 source update enabled=False 暂停"
            ),
        }
    if slug not in DOMAIN_META:
        return {"ok": False, "error": f"domain 不存在: {slug}"}

    # 卷三十四补丁 · starter 4 个不在 extras 里·也允许删·不再要求 extras 里有
    extras = _load_extra_domains()

    # 处理这个 domain 下的源
    sources = _load_sources_file()
    affected: list[dict] = []

    if sources_action == "delete":
        kept = []
        for s in sources:
            if s.get("domain") == slug:
                affected.append({"id": s.get("id"), "name": s.get("name")})
            else:
                kept.append(s)
        if affected:
            _save_sources(kept)

    elif sources_action == "reassign":
        # 决定 target_domain · 不传就走 fallback order
        if target_domain:
            target = _slugify(target_domain)
            if target == slug:
                return {"ok": False, "error": "target_domain 不能跟要删的 domain 相同"}
            if target not in DOMAIN_META:
                return {
                    "ok": False,
                    "error": f"target_domain '{target}' 不存在·可选: {list(DOMAIN_META.keys())}",
                }
        else:
            # 自动选 fallback · 跳过 slug 本身 · 跳过不存在的
            target = None
            for cand in _REASSIGN_FALLBACK_ORDER:
                if cand == slug:
                    continue
                if cand in DOMAIN_META:
                    target = cand
                    break
            if target is None:
                # 极端情况：除了 self-evolve 啥都没了·而 BRO 在删唯一的非 self-evolve
                # 实际上不会发生·因为 self-evolve 永远在 fallback list
                # 但兜底返回错误
                return {
                    "ok": False,
                    "error": (
                        "找不到合适的 reassign target·所有候选 domain 都不存在或被排除。"
                        "请显式传 target_domain 或改用 sources_action=delete"
                    ),
                }

        changed = False
        for s in sources:
            if s.get("domain") == slug:
                affected.append({"id": s.get("id"), "name": s.get("name")})
                s["domain"] = target
                changed = True
        if changed:
            _save_sources(sources)

    elif sources_action == "keep":
        for s in sources:
            if s.get("domain") == slug:
                affected.append({"id": s.get("id"), "name": s.get("name")})

    else:
        return {"ok": False, "error": f"未知 sources_action: {sources_action}"}

    # 删 extras (如果有) + 内存 DOMAIN_META
    if slug in extras:
        extras.pop(slug, None)
        _save_extra_domains(extras)
    DOMAIN_META.pop(slug, None)

    # 卷三十五补丁3 · BUG fix · starter 4 删了进程重启又长回来
    # 不在 extras 的 slug (= starter 4 个) · 记到 removed list · 下次启动不复活
    _mark_domain_removed(slug)

    logger.info(
        "remove_domain · %s · sources_action=%s · 影响 %d 源",
        slug, sources_action, len(affected),
    )
    return {
        "ok": True,
        "slug": slug,
        "sources_action": sources_action,
        "target_domain": target if sources_action == "reassign" else None,
        "affected_sources": affected,
    }


def list_domains() -> list[dict]:
    """返回所有领域元信息·带每个领域的信源数 + 雷达条目数（如果有抓取数据）"""
    sources = _load_sources_file()
    src_counts: dict[str, int] = {}
    for s in sources:
        d = s.get("domain", _default_domain())
        src_counts[d] = src_counts.get(d, 0) + 1

    # 卷五十八续 X · 分类计数走唯一真相源 radar_counts (扣 hidden)·
    # 否则分类 tab 加总 (含 hidden) ≠ "全部" (已扣 hidden)·就是 139≠133 那个坑。
    item_counts: dict[str, int] = {}
    try:
        from workers.radar_counts import count_by_domain
        item_counts = count_by_domain()
    except Exception:
        try:
            if RADAR_FILE.exists():
                radar = json.loads(RADAR_FILE.read_text(encoding="utf-8"))
                for it in radar.get("items") or []:
                    d = it.get("domain", _default_domain())
                    item_counts[d] = item_counts.get(d, 0) + 1
        except Exception:
            pass

    out: list[dict] = []
    for did, meta in DOMAIN_META.items():
        out.append({
            "id": did,
            "label": meta["label"],
            "icon": meta["icon"],
            "color": meta["color"],
            "description": meta["description"],
            "sources_count": src_counts.get(did, 0),
            "items_count": item_counts.get(did, 0),
        })
    return out


# ---------------------------------------------------------------------------
# 默认源清单（Daemonkey 开源版 · 只预设「自我演化」一个领域）
# ---------------------------------------------------------------------------

DEFAULT_SOURCES: list[dict] = [
    # ─────────────────────────────────────────────────────────────────────
    # Daemonkey 开源版 · 唯一预设领域 = self-evolve（自我演化）· system_required 不可删
    #   只预设「自我演化」——daemon 盯同类 agent 工程·看到好东西自己学过来。
    #   AI / 学术 / 科技资讯等都不预设：那是「他」的兴趣·由相遇收集或他手动添加，
    #   而不是替他先入为主地塞一堆 OPUS 自己关心的 AI 源。
    # ─────────────────────────────────────────────────────────────────────
    {
        "id": "gh-trending-python",
        "name": "GitHub Trending · Python",
        "display": "GH Trending Py",
        "category": "tech",
        "type": "rss",
        "url": "https://mshibanami.github.io/GitHubTrendingRSS/daily/python.xml",
        "max_items": 12,
        "enabled": True,
        "tags": ["EN", "github", "trending"],
        "domain": "self-evolve",
        "system_required": True,
        "_origin": "default",
    },
    {
        "id": "gh-trending-ts",
        "name": "GitHub Trending · TypeScript",
        "display": "GH Trending TS",
        "category": "tech",
        "type": "rss",
        "url": "https://mshibanami.github.io/GitHubTrendingRSS/daily/typescript.xml",
        "max_items": 10,
        "enabled": True,
        "tags": ["EN", "github", "trending"],
        "domain": "self-evolve",
        "system_required": True,
        "_origin": "default",
    },
    {
        "id": "gh-openhands",
        "name": "OpenHands · Release",
        "display": "OpenHands",
        "category": "tech",
        "type": "rss",
        "url": "https://github.com/All-Hands-AI/OpenHands/releases.atom",
        "max_items": 8,
        "enabled": True,
        "tags": ["EN", "github", "agent-peer"],
        "domain": "self-evolve",
        "system_required": True,
        "_origin": "default",
    },
    {
        "id": "gh-anthropic-sdk",
        "name": "Anthropic SDK · Release",
        "display": "Anthropic SDK",
        "category": "tech",
        "type": "rss",
        "url": "https://github.com/anthropics/anthropic-sdk-python/releases.atom",
        "max_items": 6,
        "enabled": True,
        "tags": ["EN", "github", "claude-sdk"],
        "domain": "self-evolve",
        "system_required": True,
        "_origin": "default",
    },
    {
        "id": "gh-autogen",
        "name": "Microsoft AutoGen · Release",
        "display": "AutoGen",
        "category": "tech",
        "type": "rss",
        "url": "https://github.com/microsoft/autogen/releases.atom",
        "max_items": 6,
        "enabled": True,
        "tags": ["EN", "github", "agent-peer"],
        "domain": "self-evolve",
        "system_required": True,
        "_origin": "default",
    },
]


# ---------------------------------------------------------------------------
# sources.json 读写
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, content: str) -> None:
    """卷四十六 III · wish-badd4 收编到 safe_write
    radar.json / sources.json 高频抓取写入·backup=False 不占空间"""
    from .safe_write import atomic_write_text
    atomic_write_text(path, content, backup=False)


def _load_sources_file() -> list[dict]:
    """读 sources.json · 不存在则写入默认 + 返回

    卷三十四 · 自动迁移：检查 DEFAULT_SOURCES 里 system_required=True 的源
    如果在用户的 sources.json 里缺失·自动补上（避免 BRO 升级后 GitHub 源没出现）
    """
    if not SOURCES_FILE.exists():
        _atomic_write(
            SOURCES_FILE,
            json.dumps(
                {"version": 1, "sources": DEFAULT_SOURCES},
                ensure_ascii=False,
                indent=2,
            ),
        )
        logger.info("created default sources.json with %d sources", len(DEFAULT_SOURCES))
        return list(DEFAULT_SOURCES)
    try:
        data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
        sources = list(data.get("sources", []))

        # ── 迁移 · 补 system_required 源 ──
        existing_ids = {s.get("id") for s in sources}
        added = []
        for d in DEFAULT_SOURCES:
            if d.get("system_required") and d["id"] not in existing_ids:
                sources.append(dict(d))  # copy
                added.append(d["id"])
        if added:
            _save_sources(sources)
            logger.info("system_required 源迁移 · 自动补 %d 个: %s", len(added), added)

        return sources
    except Exception as e:
        logger.error("sources.json corrupt; falling back to defaults: %s", e)
        return list(DEFAULT_SOURCES)


def _save_sources(sources: list[dict]) -> None:
    _atomic_write(
        SOURCES_FILE,
        json.dumps({"version": 2, "sources": sources}, ensure_ascii=False, indent=2),
    )


def list_sources(
    *,
    enabled_only: bool = False,
    category: Optional[str] = None,
    domain: Optional[str] = None,
) -> list[dict]:
    """返回当前源清单 · 可选过滤

    domain (卷二十八)：按领域过滤 · 见 DOMAIN_META 预定义集
    """
    sources = _load_sources_file()
    if enabled_only:
        sources = [s for s in sources if s.get("enabled", True)]
    if category:
        sources = [s for s in sources if s.get("category") == category]
    if domain:
        sources = [s for s in sources if s.get("domain", _default_domain()) == domain]
    return sources


_ID_RE = re.compile(r"[^a-z0-9-]")


def _slugify(name: str) -> str:
    """把任意 name 转成稳定 id · 仅 a-z0-9-"""
    s = name.lower().strip()
    s = _ID_RE.sub("-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:40] or "src"


def add_source(
    name: str,
    url: str,
    *,
    source_type: str = "rss",
    category: str = "tech",
    display: Optional[str] = None,
    max_items: int = 10,
    tags: Optional[list[str]] = None,
    source_id: Optional[str] = None,
    domain: str = "self-evolve",
) -> dict:
    """加新源 · 返回新建的源记录 · 同 id 会抛 ValueError

    domain (卷二十八)：必须是 DOMAIN_META 里预定义的 · 否则 ValueError
    """
    if source_type not in ("rss", "html"):
        raise ValueError(f"unsupported source_type: {source_type}")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"url must start with http(s)://: {url}")
    if domain not in DOMAIN_META:
        raise ValueError(
            f"unknown domain: {domain!r} · "
            f"可选: {', '.join(DOMAIN_META.keys())}"
        )
    sid = source_id or _slugify(name)
    sources = _load_sources_file()
    if any(s["id"] == sid for s in sources):
        raise ValueError(f"source id already exists: {sid}")
    new = {
        "id": sid,
        "name": name,
        "display": display or name[:20],
        "domain": domain,
        "category": category,
        "type": source_type,
        "url": url,
        "max_items": max_items,
        "enabled": True,
        "tags": tags or [],
        "_origin": "user",
        "_added_at": datetime.now(timezone.utc).isoformat(),
    }
    sources.append(new)
    _save_sources(sources)
    logger.info("added source: %s (%s) in domain %s", sid, url, domain)
    return new


def remove_source(source_id: str, *, force: bool = False) -> dict:
    """删源 · 返回被删的源记录 · 找不到抛 KeyError

    卷三十四 · system_required=True 的源不允许删·除非 force=True
    （force 一般不开放给 LLM·只在 BRO 显式强制时才能传）
    """
    sources = _load_sources_file()
    for i, s in enumerate(sources):
        if s["id"] == source_id:
            if s.get("system_required") and not force:
                raise PermissionError(
                    f"source '{source_id}' 是 system_required · 不允许删除 · "
                    "这些源是 OPUS 监控同类工程必需的 · 想停用可以 update enabled=False"
                )
            removed = sources.pop(i)
            _save_sources(sources)
            logger.info("removed source: %s", source_id)
            return removed
    raise KeyError(f"source not found: {source_id}")


def update_source(source_id: str, **changes) -> dict:
    """改源属性 · 返回更新后的源记录 · 找不到抛 KeyError"""
    ALLOWED = {"name", "display", "category", "url", "max_items",
               "enabled", "tags", "type", "domain"}
    bad = set(changes) - ALLOWED
    if bad:
        raise ValueError(f"cannot update fields: {bad}")
    if "domain" in changes and changes["domain"] not in DOMAIN_META:
        raise ValueError(
            f"unknown domain: {changes['domain']!r} · "
            f"可选: {', '.join(DOMAIN_META.keys())}"
        )
    sources = _load_sources_file()
    for s in sources:
        if s["id"] == source_id:
            s.update(changes)
            _save_sources(sources)
            logger.info("updated source %s: %s", source_id, list(changes.keys()))
            return s
    raise KeyError(f"source not found: {source_id}")


# ---------------------------------------------------------------------------
# 网络抓取
# ---------------------------------------------------------------------------


def _fetch(url: str) -> Optional[str]:
    """抓单个 URL · 失败返回 None · **绝不抛异常**"""
    if httpx is None:
        logger.error("httpx not installed; cannot fetch %s", url)
        return None
    try:
        with httpx.Client(
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            r = client.get(url)
            if r.status_code == 200:
                return r.text
            logger.warning("%s returned %s", url, r.status_code)
    except Exception as e:
        logger.warning("fetch %s failed: %s", url, e)
    return None


def _parse_rss_or_atom(
    xml_text: str,
    source: dict,
) -> list[RadarItem]:
    """解析 RSS 2.0 或 Atom · 单条目失败跳过"""
    items: list[RadarItem] = []
    if not xml_text:
        return items

    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("XML parse failed for %s: %s", source["id"], e)
        return items

    max_items = source.get("max_items", DEFAULT_MAX_ITEMS_PER_SOURCE)

    # Atom namespace (Hugging Face / Wordpress 等用)
    NS = {"atom": "http://www.w3.org/2005/Atom"}

    # 先尝试 RSS 2.0
    rss_items = list(root.iter("item"))
    if rss_items:
        for it in rss_items:
            if len(items) >= max_items:
                break
            try:
                title = (it.findtext("title") or "").strip()
                url = (it.findtext("link") or "").strip()
                desc = (it.findtext("description") or "").strip()
                pub = (it.findtext("pubDate") or "").strip()
            except Exception:
                continue
            if not (title and url):
                continue
            items.append(
                RadarItem(
                    title=title,
                    url=url,
                    source=source["id"],
                    source_display=source.get("display", source["id"]),
                    category=source.get("category", "tech"),
                    summary=(desc[:400] if desc else ""),
                    published_at=pub,
                    fetched_at=fetched_at,
                    domain=source.get("domain", _default_domain()),
                )
            )
        return items

    # Atom feed
    for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
        if len(items) >= max_items:
            break
        try:
            title_el = entry.find("atom:title", NS)
            link_el = entry.find("atom:link", NS)
            summary_el = entry.find("atom:summary", NS) or entry.find(
                "atom:content", NS
            )
            updated_el = entry.find("atom:updated", NS) or entry.find(
                "atom:published", NS
            )
            title = (title_el.text or "").strip() if title_el is not None else ""
            url = (link_el.get("href") or "").strip() if link_el is not None else ""
            summary = (summary_el.text or "").strip() if summary_el is not None else ""
            pub = (updated_el.text or "").strip() if updated_el is not None else ""
        except Exception:
            continue
        if not (title and url):
            continue
        items.append(
            RadarItem(
                title=title,
                url=url,
                source=source["id"],
                source_display=source.get("display", source["id"]),
                category=source.get("category", "tech"),
                summary=summary[:400],
                published_at=pub,
                fetched_at=fetched_at,
                domain=source.get("domain", _default_domain()),
            )
        )

    return items


# 源类型注册表 · 加新 type 在这扩
SOURCE_HANDLERS: dict[str, Callable[[str, dict], list[RadarItem]]] = {
    "rss": lambda xml_text, source: _parse_rss_or_atom(xml_text, source),
    "atom": lambda xml_text, source: _parse_rss_or_atom(xml_text, source),
}


def _fetch_source(source: dict) -> list[RadarItem]:
    """抓单个源 · 调度到对应 handler"""
    handler = SOURCE_HANDLERS.get(source.get("type", "rss"))
    if handler is None:
        logger.warning("unknown source type: %s", source.get("type"))
        return []
    raw = _fetch(source["url"])
    if not raw:
        return []
    return handler(raw, source)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def refresh_radar(progress=None, translate: bool = True) -> dict:
    """跑一次完整抓取 · 写 data/radar.json · 返回汇总元数据

    progress: 可选回调 (step, msg) · 串行巡源时按『信源 i/N』实时回报·
    给 auto_pipeline 传 push_tool_progress 用·让前端别干等 (卷六十一续)。
    translate: 是否逐条翻译英文标题 (走 LLM·首次最慢的一步)。首启热数据时传 False
    可省下大半时间——中文源本就不用译·英文源(自我演化)留待后续 refresh 再补译。
    """
    logger.info("info_radar refresh started")
    sources = list_sources(enabled_only=True)
    all_items: list[RadarItem] = []
    sources_meta: list[dict] = []
    started = time.time()
    n_src = len(sources)

    def _p(step: str, msg: str = "") -> None:
        if progress is not None:
            try:
                progress(step, msg)
            except Exception:
                pass

    for i, src in enumerate(sources, 1):
        _p(f"📡 巡信源 {i}/{n_src}", src.get("display", src["id"]))
        t0 = time.time()
        try:
            items = _fetch_source(src)
            sources_meta.append(
                {
                    "source": src["id"],
                    "display": src.get("display", src["id"]),
                    "domain": src.get("domain", _default_domain()),
                    "fetched": len(items),
                    "ok": bool(items),
                    "elapsed_ms": int((time.time() - t0) * 1000),
                }
            )
            all_items.extend(items)
        except Exception as e:
            logger.exception("source %s crashed: %s", src["id"], e)
            sources_meta.append(
                {
                    "source": src["id"],
                    "display": src.get("display", src["id"]),
                    "domain": src.get("domain", _default_domain()),
                    "fetched": 0,
                    "ok": False,
                    "error": str(e),
                    "elapsed_ms": int((time.time() - t0) * 1000),
                }
            )

    # 卷五十六 信源审计 · 跨源去重 (实测 Cyera/Uber 等被多源抓到重复·价值密度会虚高)
    # 按 url 精确去重 (同 url = 必然同一条) · 保留先到的那条
    _seen_urls: set[str] = set()
    _deduped: list[RadarItem] = []
    for it in all_items:
        u = (it.url or "").strip()
        if u and u in _seen_urls:
            continue
        if u:
            _seen_urls.add(u)
        _deduped.append(it)
    _dropped = len(all_items) - len(_deduped)
    if _dropped:
        logger.info("radar dedup · 去掉 %d 条重复 url", _dropped)
    all_items = _deduped

    all_items.sort(key=lambda x: x.published_at, reverse=True)

    # 卷二十七：抓完后立即调 translator 给英文条目加 title_zh/summary_zh
    # 翻译挂了也不影响雷达正常返回——translator 内部已保证容错
    items_dicts = [asdict(i) for i in all_items]
    _p("🌐 翻译 + 整理条目…", f"{len(all_items)} 条")
    translation_meta: dict = {"attempted": False, "translated": 0, "skipped": 0}
    if translate and os.environ.get("OPUS_RADAR_TRANSLATE", "1") != "0":
        try:
            from workers.translator import cache_stats, translate_items
            before_cache = cache_stats().get("total_cached", 0)
            items_dicts = translate_items(items_dicts)
            after_cache = cache_stats().get("total_cached", 0)
            translation_meta = {
                "attempted": True,
                "translated": sum(1 for it in items_dicts if it.get("_translated")),
                "newly_cached": after_cache - before_cache,
                "total_cached": after_cache,
            }
        except Exception as e:
            logger.warning("translator integration failed: %s", e)
            translation_meta = {"attempted": True, "error": str(e)}

    domains_breakdown: dict[str, int] = {}
    for it in items_dicts:
        d = it.get("domain", _default_domain())
        domains_breakdown[d] = domains_breakdown.get(d, 0) + 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": int((time.time() - started) * 1000),
        "total_items": len(all_items),
        "total_sources": len(sources),
        "sources_meta": sources_meta,
        "translation": translation_meta,
        "domains_breakdown": domains_breakdown,
        "items": items_dicts,
    }

    _atomic_write(
        RADAR_FILE,
        json.dumps(payload, ensure_ascii=False, indent=2),
    )
    # 卷五十八续 X · 登记首次见到 · 只给新 url 记当天·让"今日新增"是真新增 (BRO 拍板)
    try:
        from workers.radar_seen import record_seen
        _seen = record_seen(items_dicts)
        logger.info("radar_seen · 新增首见 %d 条 · 台账共 %d 条", _seen.get("added", 0), _seen.get("total", 0))
    except Exception as e:
        logger.warning("record_seen failed: %s", e)
    ok_sources = sum(1 for s in sources_meta if s["ok"])
    logger.info(
        "info_radar refresh done · %d/%d sources ok · %d items · %dms · translated=%d",
        ok_sources,
        len(sources),
        len(all_items),
        payload["elapsed_ms"],
        translation_meta.get("translated", 0),
    )
    return {
        "total": len(all_items),
        "sources": len(sources),
        "ok_sources": ok_sources,
        "elapsed_ms": payload["elapsed_ms"],
        "translated": translation_meta.get("translated", 0),
    }


def backfill_radar_translation() -> dict:
    """给现有 radar.json 补翻——不重新抓 RSS · 只把还没翻的英文条目翻一遍

    用于:
      - 第一次接入 translator (现有 radar.json 里的英文条目都没 title_zh)
      - cache 被清空后想恢复
      - 翻译模型升级后想重翻
    """
    if not RADAR_FILE.exists():
        return {"error": "radar.json not found · run refresh_radar first"}

    try:
        data = json.loads(RADAR_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"failed to load radar.json: {e}"}

    items = data.get("items") or []
    if not items:
        return {"note": "radar empty · nothing to translate"}

    from workers.translator import cache_stats, translate_items
    before = cache_stats().get("total_cached", 0)
    started = time.time()
    new_items = translate_items(items)
    after = cache_stats().get("total_cached", 0)

    data["items"] = new_items
    data["translation"] = {
        "attempted": True,
        "translated": sum(1 for it in new_items if it.get("_translated")),
        "newly_cached": after - before,
        "total_cached": after,
        "backfilled_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write(RADAR_FILE, json.dumps(data, ensure_ascii=False, indent=2))

    return {
        "ok": True,
        "items_processed": len(items),
        "translated": data["translation"]["translated"],
        "newly_cached": after - before,
        "total_cached": after,
        "elapsed_ms": int((time.time() - started) * 1000),
    }


def backfill_radar_domain() -> dict:
    """卷二十八 · 给现有 radar.json 补 domain 字段
    从 sources.json 反查每个 source 的 domain · 写回 item.domain。

    用于：
      - 第一次升级到 v2 schema (现有 radar.json 里都没 domain)
      - 改了 source domain 后想立刻反应到 UI 上而不重新抓 RSS
    """
    if not RADAR_FILE.exists():
        return {"error": "radar.json not found · run refresh_radar first"}
    try:
        data = json.loads(RADAR_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"failed to load radar.json: {e}"}

    items = data.get("items") or []
    if not items:
        return {"note": "radar empty · nothing to backfill"}

    sources = _load_sources_file()
    source_domain_map = {s["id"]: s.get("domain", _default_domain()) for s in sources}

    updated = 0
    for it in items:
        new_domain = source_domain_map.get(it.get("source", ""), _default_domain())
        if it.get("domain") != new_domain:
            it["domain"] = new_domain
            updated += 1

    # 顺便重算 domains_breakdown
    breakdown: dict[str, int] = {}
    for it in items:
        d = it.get("domain", _default_domain())
        breakdown[d] = breakdown.get(d, 0) + 1
    data["items"] = items
    data["domains_breakdown"] = breakdown
    data["_domain_backfilled_at"] = datetime.now(timezone.utc).isoformat()

    # 同步 sources_meta 里也带上 domain
    for m in data.get("sources_meta") or []:
        m["domain"] = source_domain_map.get(m.get("source", ""), _default_domain())

    _atomic_write(RADAR_FILE, json.dumps(data, ensure_ascii=False, indent=2))

    return {
        "ok": True,
        "items_updated": updated,
        "total_items": len(items),
        "domains_breakdown": breakdown,
    }


# 卷三十二 · 模块加载时合并 disk 上 BRO 自定义的 extra domains
try:
    _refresh_domain_meta()
except Exception as _e:  # noqa: BLE001
    logger.debug("refresh_domain_meta on import failed: %s", _e)


def load_radar() -> dict:
    """读 data/radar.json · 不存在返回空 stub"""
    if not RADAR_FILE.exists():
        return {
            "generated_at": None,
            "total_items": 0,
            "sources_meta": [],
            "items": [],
            "note": "radar not yet generated · run `python -m workers.info_radar` "
                    "or 跟 OPUS 说 \u300c刷新雷达\u300d",
        }
    try:
        return json.loads(RADAR_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"failed to load radar.json: {e}"}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    result = refresh_radar()
    print(
        f"\n[radar] {result['ok_sources']}/{result['sources']} sources ok · "
        f"{result['total']} items · {result['elapsed_ms']}ms"
    )
    print(f"[radar] file: {RADAR_FILE}")
