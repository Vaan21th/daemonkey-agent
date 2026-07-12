"""
agent_tools/manage_knowledge.py
===============================

OPUS 通过自然语言管理【私有文档知识库】——"合伙人的第二大脑"。

把 BRO 的资料 / 合同 / PDF / Word / PPT 灌进来 → 抽成文本 → 进 FTS5 →
之后 recall_memory(scope='docs') 或自动召回就能引用,并 cite 回原文。

档位：AUTO
  只动 data/knowledge/ · 读 BRO 指定的本地文件(和 pdf_read/read_file 同权限)· 不外联。
  误删一篇一句话能重灌 · 风险足够低。

action:
  add     · 灌一篇文档 · 需 path · 可选 tags / pinned / sensitive
  list    · 列知识库里所有文档(可按 tag 过滤)
  remove  · 删一篇 · 需 doc_id 或 title
  enable  · 打开"参考"(重新进召回)· 需 doc_id 或 title
  disable · 关掉"参考"(静音不删)· 需 doc_id 或 title
  search  · 在知识库范围内检索 · 需 query
  tag     · 改一篇的标签 · 需 doc_id/title + tags
  move    · 把一篇归到某文件夹 · 需 doc_id/title + folder(空=移出)
  sensitive · 标/取消敏感 · 需 doc_id/title + value(默认 True)· 敏感=不自动进 prompt·仅显式 recall 可取
  link    · 把一篇挂到某客户档案 · 需 doc_id/title + client(空=解除)

NLP 触发示例：
  - "把 F:\\...\\合同.pdf 加进知识库,标签 客户A" → add
  - "知识库里都有啥" → list
  - "合同那篇先别参考了" → disable
  - "我资料里讲违约金的段落" → search
"""

from __future__ import annotations

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool

_TYPE_ICON = {"pdf": "📕", "docx": "📘", "pptx": "📙", "md": "📗", "txt": "📄"}


def _summarize(args: dict) -> str:
    action = args.get("action") or "?"
    tgt = args.get("path") or args.get("doc_id") or args.get("title") or args.get("query") or ""
    return f"manage_knowledge {action}{(' · ' + str(tgt)[:50]) if tgt else ''}"


def _fmt_doc_line(m: dict) -> str:
    icon = _TYPE_ICON.get(m.get("type"), "📄")
    flags = []
    if not m.get("enabled", True):
        flags.append("已静音")
    if m.get("pinned"):
        flags.append("常驻")
    if m.get("sensitive"):
        flags.append("敏感")
    tags = m.get("tags") or []
    tag_str = f"  #{' #'.join(tags)}" if tags else ""
    flag_str = f"  [{' · '.join(flags)}]" if flags else ""
    folder = (m.get("folder") or "").strip()
    folder_str = f"  📁{folder}" if folder else ""
    return (
        f"  {icon} [{m.get('id')}] {m.get('title')}  "
        f"({m.get('chunks', 0)}块 · {m.get('chars', 0)}字){flag_str}{folder_str}{tag_str}"
    )


def _resolve(args: dict) -> tuple[str | None, str | None]:
    """从 doc_id / title 解析出 doc_id · 返回 (doc_id, err)。"""
    from workers.knowledge_base import resolve_doc_id

    hint = (args.get("doc_id") or args.get("title") or "").strip()
    if not hint:
        return None, "需要 doc_id 或 title 指定哪一篇"
    did = resolve_doc_id(hint)
    if not did:
        return None, f"找不到文档: {hint} · 用 action=list 看现有清单"
    return did, None


def _resolve_client(hint: str) -> str | None:
    """把客户 id/名字解析成 client_id · 给挂档用。"""
    hint = (hint or "").strip()
    if not hint:
        return None
    try:
        from workers.clients import resolve_client_id
        return resolve_client_id(hint)
    except Exception:
        return None


def _run(args: dict) -> ToolResult:
    from workers import knowledge_base as kb

    action = (args.get("action") or "list").lower().strip()

    try:
        if action == "add":
            path = (args.get("path") or "").strip()
            if not path:
                return ToolResult(ok=False, output="", error="add 需要 path(本地文件绝对路径)")
            from workers.doc_ingest import IngestError

            client_hint = (args.get("client") or "").strip()
            client_id = ""
            if client_hint:
                client_id = _resolve_client(client_hint) or ""
                if not client_id:
                    return ToolResult(ok=False, output="",
                        error=f"找不到客户: {client_hint} · 先用 manage_client add 建档·或去掉 client 参数")
            try:
                meta = kb.add_document(
                    path,
                    tags=args.get("tags") or [],
                    pinned=bool(args.get("pinned")),
                    sensitive=bool(args.get("sensitive")),
                    folder=(args.get("folder") or "").strip(),
                    client_id=client_id,
                )
            except IngestError as e:
                return ToolResult(ok=False, output="", error=f"灌入失败: {e}")
            return ToolResult(
                ok=True,
                output=(
                    f"已灌入知识库 · [{meta['id']}] {meta['title']}\n"
                    f"  类型={meta['type']} · {meta['chunks']}块 · {meta['chars']}字\n"
                    f"  现在可被召回并 cite 回原文。不想参考它 → disable。"
                ),
            )

        if action == "list":
            docs = kb.list_documents(tag=args.get("tag"))
            st = kb.stats()
            if not docs:
                return ToolResult(ok=True, output="知识库还是空的 · 用 action=add + path 灌第一篇。")
            lines = [f"# 私有文档知识库 · 共 {st['total']} 篇({st['enabled']} 参考中 · {st['disabled']} 已静音)", ""]
            lines.extend(_fmt_doc_line(m) for m in docs)
            return ToolResult(ok=True, output="\n".join(lines))

        if action in ("remove", "enable", "disable"):
            did, err = _resolve(args)
            if err:
                return ToolResult(ok=False, output="", error=err)
            if action == "remove":
                meta = kb.remove_document(did)
                return ToolResult(ok=True, output=f"已删除 · [{meta['id']}] {meta['title']}(原文与索引都清了)")
            meta = kb.set_enabled(did, action == "enable")
            state = "重新参考(已进召回)" if action == "enable" else "已静音(不进召回 · 原文保留)"
            return ToolResult(ok=True, output=f"[{meta['id']}] {meta['title']} → {state}")

        if action == "tag":
            did, err = _resolve(args)
            if err:
                return ToolResult(ok=False, output="", error=err)
            tags = args.get("tags")
            if tags is None:
                return ToolResult(ok=False, output="", error="tag 需要 tags 数组")
            meta = kb.update_document(did, tags=list(tags))
            return ToolResult(ok=True, output=f"[{meta['id']}] {meta['title']} 标签 → {meta['tags']}")

        if action == "move":
            did, err = _resolve(args)
            if err:
                return ToolResult(ok=False, output="", error=err)
            folder = (args.get("folder") or "").strip()
            meta = kb.update_document(did, folder=folder)
            dest = f"文件夹「{folder}」" if folder else "未分类(移出文件夹)"
            return ToolResult(ok=True, output=f"[{meta['id']}] {meta['title']} → {dest}")

        if action == "link":
            did, err = _resolve(args)
            if err:
                return ToolResult(ok=False, output="", error=err)
            hint = (args.get("client") or "").strip()
            if not hint:
                meta = kb.update_document(did, client_id="")
                return ToolResult(ok=True, output=f"[{meta['id']}] {meta['title']} 已解除客户关联")
            cid = _resolve_client(hint)
            if not cid:
                return ToolResult(ok=False, output="",
                    error=f"找不到客户: {hint} · 先用 manage_client add 建档")
            meta = kb.update_document(did, client_id=cid)
            cname = ""
            try:
                from workers.clients import get_client
                cname = (get_client(cid) or {}).get("name", cid)
            except Exception:
                cname = cid
            return ToolResult(ok=True, output=f"[{meta['id']}] {meta['title']} → 挂到客户「{cname}」")

        if action == "sensitive":
            did, err = _resolve(args)
            if err:
                return ToolResult(ok=False, output="", error=err)
            val = args.get("value")
            val = True if val is None else bool(val)
            meta = kb.update_document(did, sensitive=val)
            state = ("标为敏感(不再自动进 prompt/召回目录 · 要显式 recall 才给)"
                     if val else "取消敏感(恢复自动参考)")
            return ToolResult(ok=True, output=f"[{meta['id']}] {meta['title']} → {state}")

        if action == "search":
            query = (args.get("query") or "").strip()
            if not query:
                return ToolResult(ok=False, output="", error="search 需要 query")
            chunks = kb.search_documents(query, top_k=int(args.get("top_k") or 5))
            if not chunks:
                return ToolResult(ok=True, output=f"知识库里没搜到与 '{query}' 相关的内容。")
            lines = [f"知识库命中 {len(chunks)} 段(与 '{query}' 相关):\n"]
            for i, c in enumerate(chunks, 1):
                did = c.source[len("doc:"):] if c.source.startswith("doc:") else c.source
                meta = kb.get_document(did) or {}
                title = meta.get("title", did)
                sec = f" · {c.section}" if c.section else ""
                snippet = " ".join((c.content or "").split())[:160]
                lines.append(f"{i}. 【{title}{sec}】\n   {snippet}…")
            return ToolResult(ok=True, output="\n".join(lines))

        return ToolResult(
            ok=False, output="",
            error=f"未知 action: {action} · 可选: add/list/remove/enable/disable/search/tag/move/sensitive/link",
        )

    except KeyError as e:
        return ToolResult(ok=False, output="", error=f"找不到文档: {e}")
    except Exception as e:  # noqa: BLE001
        return ToolResult(ok=False, output="", error=f"tool internal error: {e}")


SPEC = ToolSpec(
    name="manage_knowledge",
    description=(
        "管理 BRO 的私有文档知识库(第二大脑)——把资料/合同/PDF/Word/PPT 灌进来,"
        "之后能被召回并 cite 回原文。这是 recall_memory(scope='docs') 的数据来源。\n\n"
        "**调用时机**(OPUS 主动判断):\n"
        "  - BRO 说'把这份文件/合同/资料加进知识库' / 给了本地文件路径要你记住 → action=add\n"
        "  - BRO 问'知识库里有啥' / '我存过哪些资料' → action=list\n"
        "  - BRO 说'那篇先别参考了 / 重新参考' → action=disable / enable\n"
        "  - BRO 问'我资料里关于 X 的部分' → action=search\n\n"
        "  - BRO 说'把那篇归到 X 文件夹 / 整理一下分类' → action=move\n\n"
        "**支持格式**: md / txt / docx / pptx / pdf(文本型)。扫描件/图片型 PDF 需 OCR,暂不支持。\n"
        "**参考开关**: disable = 从召回里静音但保留原文;enable = 重新进召回。\n"
        "**文件夹**: 每篇可归到一个文件夹(folder)· 前端知识库按文件夹分组显示 · move 改归属。\n"
        "**敏感**: 标 sensitive 的文档不再自动进 system prompt / 召回目录(避免私密资料每轮外送),"
        "但仍留在索引里 · 只有显式 recall_memory(scope='docs') / search 才取用。\n"
        "**挂客户**: link 把一篇文档挂到某个客户档案(client)· 之后在客户档案里能看到他名下所有资料。\n"
        "**actions**: add / list / remove / enable / disable / search / tag / move / sensitive / link"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "list", "remove", "enable", "disable", "search", "tag", "move", "sensitive", "link"],
            },
            "path": {"type": "string", "description": "add 用:本地文件绝对路径"},
            "doc_id": {"type": "string", "description": "remove/enable/disable/tag/move 用:文档 id(doc-xxxx)"},
            "title": {"type": "string", "description": "remove/enable/disable/tag/move 用:按标题定位(doc_id 的替代,模糊匹配)"},
            "query": {"type": "string", "description": "search 用:检索关键词"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "add/tag 用:标签数组(如 ['合同','客户A'])",
            },
            "tag": {"type": "string", "description": "list 用:只列带此标签的文档"},
            "folder": {"type": "string", "description": "add/move 用:文件夹名(归类 · 空=未分类)。前端按文件夹分组显示"},
            "client": {"type": "string", "description": "add/link 用:挂到哪个客户(id 或名字)· link 时留空=解除关联"},
            "pinned": {"type": "boolean", "description": "add 用:是否常驻上下文(标常驻的会优先递给 OPUS)"},
            "sensitive": {"type": "boolean", "description": "add 用:入库即标敏感(不自动进 prompt·仅显式 recall 可取)"},
            "value": {"type": "boolean", "description": "sensitive action 用:True=标敏感 / False=取消(默认 True)"},
            "top_k": {"type": "integer", "description": "search 用:返回条数(默认 5)"},
        },
        "required": ["action"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
