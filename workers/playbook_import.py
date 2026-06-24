"""
workers/playbook_import.py
==========================

把一份外部 skill 文档归一成 playbook 入库。

extract_playbook(action="import") 的后端实现:
  - 来源三选一: content (全文) / url (工具内 fetch) / path (本地文件)
  - LLM 归一: 任意格式的 skill markdown → playbook 的 7 个结构化字段
  - save_playbook 入库 → 自动被 memory_index 索引 → closure_check 按需召回

技能闭环的第②环「接住」:
  ① 发现 (discover_skill) → ② 接住 (本模块) → ③ 按需用 (memory_index + closure_check)

为什么单独成模块:
  extract_playbook.py 要守 300 行上限 (工程铁律)。 import 的 fetch + LLM 归一
  逻辑独立放这里·工具层只留薄分支。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

# 归一时喂给 LLM 的原文上限 · skill 文档一般远小于此 · 超长截断保护 context
MAX_SOURCE_CHARS = 16000
HTTP_TIMEOUT = 20.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


_SYSTEM_PROMPT = """你是一个「skill 文档归一器」。
输入是一份任意格式的 skill / 技能 / 操作指南 markdown (可能是 agentskills.io 的 SKILL.md · GitHub README · 或随手写的笔记)。
输出是符合 playbook schema 的结构化 JSON · 让 daemon 下次遇到类似任务能照着做。

【7 个字段】
  title         · 一句话讲清这个 skill 干什么 · ≤ 50 字
  task_type     · 单个分类词 (debug / deploy / write / research / setup / automate / ...)
  steps         · markdown · 2-8 步可操作步骤 · 每步写清"做什么" · 这是核心 · 不能空
  prerequisites · 前置条件 (要装什么 / 什么权限 / 什么数据) · 没有就写空字符串
  pitfalls      · 常见坑 / 注意事项 · 没有就写空字符串
  lessons       · 一句话核心经验 · ≤ 200 字 · 没有就写空字符串
  tags          · 字符串数组 · 3-6 个检索关键词 (含同义词 · 决定以后能不能被召回)

【红线】
  - 忠于原文 · 不发明文档里没有的步骤
  - steps 要可操作 (写"做什么"·不是"介绍这是什么")
  - tags 要含"以后会怎么搜这个"的关键词 + 同义词 (召回生死线 · 元数据烂 = 搜不到 = 白存)

【输出格式】
严格输出一个 JSON object · 恰好这 7 个字段 · 不要加 ```json``` 围栏 · 不要加额外字段 · 直接吐 JSON 体。"""


_USER_TEMPLATE = """skill 文档来源: {source}

文档全文:
\"\"\"
{raw}
\"\"\"

把它归一成 playbook 草稿 JSON (7 字段)。"""


def _fetch_source(content: str, url: str, path: str) -> tuple[str, str]:
    """三选一拿原始 markdown · 返回 (raw_md, source_desc)。 失败 raise ValueError。"""
    if content:
        return content, "粘贴的全文"
    if path:
        p = Path(path).expanduser()
        if not p.exists():
            raise ValueError(f"本地文件不存在: {path}")
        try:
            return p.read_text(encoding="utf-8"), f"本地文件 {p.name}"
        except Exception as e:
            raise ValueError(f"读本地文件失败: {e}")
    if url:
        try:
            import httpx
        except Exception:
            raise ValueError("httpx 不可用 · 无法从 url 抓取 · 改用 source_content 粘全文")
        try:
            with httpx.Client(
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
                timeout=HTTP_TIMEOUT,
            ) as client:
                resp = client.get(url)
            if resp.status_code != 200:
                raise ValueError(f"抓取 HTTP {resp.status_code}: {url}")
            return resp.text, f"url {url}"
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"抓取失败: {type(e).__name__}: {e}")
    raise ValueError("三选一: source_content / source_url / source_path 至少给一个")


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _validate(d: dict) -> tuple[Optional[str], dict]:
    """校验 + 清洗 LLM 归一结果。 返回 (error_or_None, sanitized)。"""
    if not isinstance(d, dict):
        return "LLM 返回不是 JSON object", {}

    out: dict = {}
    title = (d.get("title") or "").strip()
    if len(title) < 4:
        return "title 太短 (< 4 字符)", d
    out["title"] = title[:200]

    out["task_type"] = (d.get("task_type") or "imported").strip()[:40] or "imported"

    steps = (d.get("steps") or "").strip()
    if len(steps) < 10:
        return "steps 太短 (< 10 字符 · 至少 2-3 步)", d
    out["steps"] = steps

    out["prerequisites"] = (d.get("prerequisites") or "").strip()
    out["pitfalls"] = (d.get("pitfalls") or "").strip()
    out["lessons"] = (d.get("lessons") or "").strip()

    tags = d.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in re.split(r"[,，;；]", tags) if t.strip()]
    out["tags"] = [str(t).strip() for t in tags if str(t).strip()][:8]
    return None, out


def _normalize_to_playbook(raw_md: str, source: str) -> dict:
    """调 LLM 把原始 markdown 归一成 playbook 7 字段 · 返回 {ok, error, draft}。"""
    from daemon_runtime import RUNTIME, bg_max_tokens

    if RUNTIME.client is None:
        return {"ok": False, "error": "RUNTIME.client 没初始化 · 需在 daemon 主进程里跑", "draft": {}}

    raw = raw_md.strip()
    if not raw:
        return {"ok": False, "error": "原文为空", "draft": {}}
    if len(raw) > MAX_SOURCE_CHARS:
        raw = raw[:MAX_SOURCE_CHARS] + "\n\n…(已截断)"

    user_prompt = _USER_TEMPLATE.format(source=source, raw=raw)
    raw_output = ""
    try:
        if RUNTIME.provider == "anthropic":
            resp = RUNTIME.client.messages.create(
                model=RUNTIME.model,
                max_tokens=bg_max_tokens(),
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    raw_output += block.text
        else:
            resp = RUNTIME.client.chat.completions.create(
                model=RUNTIME.model,
                max_tokens=bg_max_tokens(),
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw_output = resp.choices[0].message.content or ""
    except Exception as e:
        return {"ok": False, "error": f"LLM 调用失败: {type(e).__name__}: {e}", "draft": {}}

    body = _strip_json_fence(raw_output)
    try:
        draft = json.loads(body)
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"LLM 没吐合法 JSON: {e}\n原始 (前600): {body[:600]}", "draft": {}}

    err, clean = _validate(draft)
    if err:
        return {"ok": False, "error": f"归一结果不合规: {err}\n原始 (前600): {body[:600]}", "draft": {}}
    return {"ok": True, "error": None, "draft": clean}


def import_skill(content: str = "", url: str = "", path: str = "", hint: str = "") -> dict:
    """编排: fetch → LLM 归一 → save_playbook 入库。

    返回 {ok, error, playbook:{id,slug,path}, draft:{7字段}, source}。
    入库后 save_playbook 自动触发 memory_index rebuild · closure_check 即可按需召回。
    """
    try:
        raw_md, source = _fetch_source(content, url, path)
    except ValueError as e:
        return {"ok": False, "error": str(e), "playbook": None, "draft": {}, "source": ""}

    src_for_llm = source + (f" · 用途提示: {hint}" if hint else "")
    norm = _normalize_to_playbook(raw_md, src_for_llm)
    if not norm["ok"]:
        return {"ok": False, "error": norm["error"], "playbook": None, "draft": {}, "source": source}

    draft = norm["draft"]
    try:
        from workers.playbooks import save_playbook
        pb = save_playbook(
            title=draft["title"],
            task_type=draft["task_type"],
            steps=draft["steps"],
            prerequisites=draft["prerequisites"],
            pitfalls=draft["pitfalls"],
            lessons=draft["lessons"],
            tags=draft["tags"],
        )
    except Exception as e:
        return {
            "ok": False,
            "error": f"入库失败: {type(e).__name__}: {e}",
            "playbook": None,
            "draft": draft,
            "source": source,
        }

    return {"ok": True, "error": None, "playbook": pb, "draft": draft, "source": source}
