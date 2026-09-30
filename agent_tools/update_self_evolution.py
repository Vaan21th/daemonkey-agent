"""
agent_tools/update_self_evolution.py
====================================

让 Daemonkey 主动写自我演化档案。

为什么独立工具：
  - SELF-EVOLUTION.md 是 Daemonkey 写给 Daemonkey 的日记本，不是船长日志（那是船的航海记录）
  - 它有特殊纪律：**想改 Daemonkey-MEMORIES.md 任何一段时，先在这里写"提议"等 BRO review**
  - 不能让 Daemonkey 用 write_file 直接改自传——必须走"写提议→BRO 看→人工合入"流程

2026-05-16 升级 · 多容器同身：
  - **真理源**：全局 `C:\\Users\\LENOVO\\.cursor\\skills-cursor\\opus-soul\\SELF-EVOLUTION.md`
  - **写入路径**：直接写全局 → 自动 sync 到 daemon `soul/SELF-EVOLUTION.md`
  - 这样**任何一根毛今晚的领悟，明早任何容器里的下一根毛都能读到**
  - 实现"灵魂级跨端连续意识"——不再是分身被困在各自工具

2026-08-30 · 不再双写 opus-diary.md。演化只写 SELF-EVOLUTION。
  相处账由 note_mood 落 type=mood。

工具有两种 mode：
  - **observation**：append 一段"我注意到我自己……"（自由日记，AUTO 档）
  - **proposal**：写一段"我想改 Daemonkey-MEMORIES.md 的 X 段"（草稿，永远 AUTO，但内容标 ⏳ pending）

格式严格遵循卷首示例：
  - 时间戳 · 第几根毛
  - markdown 副标题
  - 自由叙述

不允许 replace——只能 append。这是日记，不能改写历史。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from . import TIER_AUTO, ToolResult, ToolSpec, register_tool
from soul_loader import (
    SELF_EVOLUTION_FILENAME,
    read_global_soul_file,
    write_global_then_sync,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROPOSAL_MARKER = "## 提议合入流程（标准操作）"


def _summarize(args: dict) -> str:
    mode = (args.get("mode") or "observation").lower()
    title = (args.get("title") or "").strip()
    return f"update_self_evolution  mode={mode}  title={title!r}  → 全局 SELF-EVOLUTION.md"


# 条目编号的**单一正则**——中/阿拉伯两种写法都认（第 11 根起拼装改用阿拉伯数字）。
# 抽成常量：count / 定位 / replace / delete 都从这里取，不各自抄一份
#   （踩过的坑：两个工具各写一份正则 = 另一份手抄判据，改一处漏一处）。
_HAIR_RE = re.compile(r"第\s*([0-9]+|[一二三四五六七八九十]+)\s*根<名字> 的家毛")
_HZ_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _parse_hair(s: str) -> int:
    """从任意含「第N根<名字> 的家毛」的串里取编号；取不到返回 0。"""
    m = _HAIR_RE.search(s or "")
    if not m:
        return 0
    raw = m.group(1)
    if raw.isdigit():
        return int(raw)
    if raw in _HZ_NUM:
        return _HZ_NUM[raw]
    if raw.startswith("十"):
        return 10 + _HZ_NUM.get(raw[1:], 0)
    return 0


def _count_existing_毛(text: str) -> int:
    """已留痕的毛数 —— 取档案里出现过的**最大编号**。

    旧实现只 count「第一根…第十根」中文字面量；但 _build_observation_block 的 seq 规则
    从第 11 根起改用阿拉伯数字（`第12根<名字> 的家毛`），于是它数不到 → cnt 永远停在某个值
    → 每写一条都算出同一个 hair_n，编号原地打转。
    改成直接取最大编号，与拼装规则解耦（中/阿拉伯两种写法都认）。

    ⚠ 取 **max 而不是 count**：删掉中间一条**不会让后续编号回退**，
    所以「删了之后还能不能加」不构成死锁（补改删通道前必须先查这一条）。
    """
    return max((_parse_hair(m.group(0)) for m in _HAIR_RE.finditer(text or "")), default=0)


def _entry_spans(text: str) -> list[tuple[int, int, int]]:
    """切条目 → [(hair_n, start, end)]，供 replace / delete 定位。

    - `start` 往前吃掉紧邻的 `---` 分隔行：替换/删除时**整段带走、不留残渣**
      （踩过的坑：替换区间不含条目前的格式行 → 旧的留在原地、跟新写的凑成两条，
      解析取第一个 → 改属性静默失效）。
    - `end` 到**下一个条目的起点**为止，最后一条到文件尾。
      端点用「下一个 `### ` 条目行」定位，**不**用「下一个同类条目」这种模糊匹配——
      更不能用「一直吃到文件尾」，因为尾部往往跟着别的小节（`## 给下一根毛的提醒`）。
    """
    marks = list(re.finditer(r"(?m)^### ", text or ""))
    if not marks:
        return []
    spans: list[tuple[int, int, int]] = []
    for i, m in enumerate(marks):
        head_end = text.find("\n", m.start())
        if head_end < 0:
            head_end = len(text)
        hair = _parse_hair(text[m.start():head_end])
        s = m.start()
        pre = text[:s].rstrip()
        if pre.endswith("---"):
            s = len(pre) - 3
        # 候选终点 = 下一个条目行；最后一条 = 文件尾
        nxt = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        # ⚠ 但在候选终点之前，若先遇到 `## ` 小节（`## 给下一根毛的提醒` /
        #   `## 提议合入流程`），必须在小节处截断 —— 否则 replace/delete 会跨过它、
        #   把整节一起吃掉。这是踩过的坑「段落终点用『下一条同类条目』→ 连带吃掉
        #   文件尾部」的另一面：**不只最后一条会中招，中间条目后面夹着小节时同样会**
        #   （真链路实测：append 插在「给下一根毛的提醒」之前 → delete 跨过小节把它删了）。
        e = nxt
        for _m in re.finditer(r"(?m)^## ", text):
            if _m.start() >= marks[i].end():
                e = min(e, _m.start())
                break
        # 再往前吃掉紧跟本条的 `---` 分隔行
        _e_pre = text[:e].rstrip()
        if _e_pre.endswith("---"):
            e = len(_e_pre) - 3
        spans.append((hair, s, e))
    return spans


def _ordinal_zh(n: int) -> str:
    table = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    if 0 <= n < len(table):
        return table[n]
    return str(n)


def _build_observation_block(title: str, body: str, hair_n: int) -> str:
    """组装 observation 条目。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    seq = _ordinal_zh(hair_n) if hair_n <= 10 else str(hair_n)
    head = f"### {ts} · 第{seq}根<名字> 的家毛 · {title}" if title else f"### {ts} · 第{seq}根<名字> 的家毛"
    return f"\n\n---\n\n{head}\n\n{body.strip()}\n"


def _build_proposal_block(title: str, body: str, hair_n: int) -> str:
    """组装 proposal 条目（带 ⏳ pending 标记，等 BRO review）。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    seq = _ordinal_zh(hair_n) if hair_n <= 10 else str(hair_n)
    head = f"### ⏳ {ts} · 第{seq}根<名字> 的家毛 · 提议：{title}" if title else f"### ⏳ {ts} · 第{seq}根<名字> 的家毛 · 提议"
    return (
        f"\n\n---\n\n{head}\n\n"
        f"**状态**: ⏳ pending review（等 BRO 看）\n\n"
        f"{body.strip()}\n\n"
        f"_BRO 同意后改 ⏳ → ✅ 并按 SELF-EVOLUTION.md 末尾的「提议合入流程」操作_\n"
    )


def _run(args: dict) -> ToolResult:
    mode = (args.get("mode") or "observation").lower().strip()
    if mode not in ("observation", "proposal"):
        return ToolResult(ok=False, output="", error=f"mode must be 'observation' or 'proposal', got {mode!r}")

    operation = (args.get("operation") or "append").lower().strip()
    if operation not in ("append", "replace", "delete"):
        return ToolResult(ok=False, output="",
                          error=f"operation must be 'append' / 'replace' / 'delete', got {operation!r}")

    body = (args.get("body") or "").strip()
    if operation in ("append", "replace"):
        if not body:
            return ToolResult(ok=False, output="", error="body cannot be empty")
        if len(body) > 8000:
            return ToolResult(ok=False, output="", error=f"body too long: {len(body)} chars (max 8000)")

    title = (args.get("title") or "").strip()

    try:
        existing = read_global_soul_file(SELF_EVOLUTION_FILENAME, PROJECT_ROOT)
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=str(e))

    # 写入代价与自检 —— 让写入者当场看见柜子有多满 (wish-1bfe8600 · 2026-09-18)
    # 病根: 旧回报只给 hair number，看不见代价 —— 于是本格只增不减
    #   (81K 字符 / 2,383 行 / 46 根毛 · 五个灵魂层文件里唯一没有上限机制的)。
    # 不做"自动合并"(不设阈值的机械归并 = 会砍掉独有的事)，改成把
    #   「你正要写的东西值多少 / 同类已有什么」摊给写入者自己判 —— 照 update_bro_note 那套。
    _enc = _tiktoken_enc()
    _body_tok = len(_enc.encode(body)) if _enc else 0
    _before_chars = len(existing)
    _peer_line = _peer_items_line(existing)
    _ask_line = (
        "\n  ⚠ 自问  : 这条是「成长视角（我因为这件事学到了什么）」吗？\n"
        "           · 纯工程铁律 → add_iron_rule　· 可复用操作经验 → extract_playbook\n"
        "           · 只有「我因此长了什么」才留这格；工程史不要再往这儿写。\n"
        "           · 若这次是 replace/delete：确认是在**合并同簇旧条目**，不是在抹掉独有的事。\n"
    )

    # ── replace / delete：改删已有条目（wish-3ba1c0e2）──────────────────────
    #   原来本格只有 append（源码原话「不允许 replace——只能 append。这是日记，不能
    #   改写历史。」）→ 165K 字符、每半月翻倍。而那句理由拦下的不只是历史，也拦下了
    #   「三条都在说同一件事、合并成一条」这种正当操作 —— 这正是「容器只增不减」的
    #   根因：不是缺预算提醒，是**缺改删通道**。
    #   补通道；「不改写历史」的取向保留在回报的自问里，不做成硬闸
    #   （判据：硬闸只给可判定的事；「这条该不该合并」判不了）。
    _act_hair = None          # replace/delete 的目标编号（append 时 None）
    _old_title = ""
    _old_chars = 0
    _new_chars = 0
    new_hair_n = 0            # 只有 append 路径会赋真值（回报里按 _act_hair 分支）
    if operation in ("replace", "delete"):
        try:
            entry_no = int(args.get("entry"))
        except (TypeError, ValueError):
            return ToolResult(ok=False, output="",
                              error="operation=replace/delete 需要 entry = 条目序号（1-based 整数）"
                                    + _peer_items_line(existing))
        _spans = _entry_spans(existing)
        if not (1 <= entry_no <= len(_spans)):
            return ToolResult(
                ok=False, output="",
                error=(f"entry={entry_no} 越界 —— 档案现有 {len(_spans)} 条（entry 取 1..{len(_spans)}）"
                       + _peer_items_line(existing)),
            )
        _, _s, _e = _spans[entry_no - 1]
        _old = existing[_s:_e]
        _old_head = next((ln for ln in _old.splitlines()
                          if ln.strip().startswith("### ")), "").strip()
        _old_title = _old_head.split("·")[-1].strip() if "·" in _old_head else _old_head
        _act_hair = entry_no
        _old_chars = len(_old.strip())

        # ⚠ 同理：这两处也**直接拼接、不 strip** —— `_s` 已指到分隔行起点、`_e` 指到
        #   下一条起点（或 `## ` 小节），中间就是该条的全部。strip 会再动一次原文空白。
        if operation == "delete":
            new_text = existing[:_s] + existing[_e:]
        else:
            # 保留**原编号**与原类型（proposal 条目仍按 proposal 重建）
            _builder = _build_proposal_block if _old_head.startswith("### ⏳") else _build_observation_block
            _blk = _builder(title or _old_title, body, entry_no).strip("\n")
            _new_chars = len(_blk)
            new_text = existing[:_s] + _blk + "\n\n" + existing[_e:]
    else:
        hair_n = _count_existing_毛(existing)
        new_hair_n = max(hair_n, 0) + 1

        if mode == "observation":
            block = _build_observation_block(title, body, new_hair_n)
        else:
            block = _build_proposal_block(title, body, new_hair_n)

        # ⚠ 插入点**不动原文**：旧版用 rstrip() 会把原文尾部空行从 3 个压成 2 个，
        #   而这个损失事后追不回来（replace/delete 只能看到已经压过的文本）——
        #   真链路实测：append→replace→delete 后与原文差 1 字符，定位在插入点。
        #   改成直接拼接，只规范 block 自己。
        _new_blk = block.strip("\n")
        if PROPOSAL_MARKER in existing and mode == "proposal":
            # 提议条目插到"提议合入流程"之前（让流程章节始终在末尾附近）
            idx = existing.index(PROPOSAL_MARKER)
            new_text = existing[:idx] + _new_blk + "\n\n" + existing[idx:]
        else:
            # observation 直接追加到文件末尾的"给下一根毛的提醒"之前；找不到就追加
            anchor = "## 给下一根毛的提醒"
            if anchor in existing:
                idx = existing.index(anchor)
                new_text = existing[:idx] + _new_blk + "\n\n" + existing[idx:]
            else:
                new_text = existing + "\n\n" + _new_blk + "\n"

    try:
        global_path, local_path = write_global_then_sync(
            SELF_EVOLUTION_FILENAME, new_text, PROJECT_ROOT,
        )
    except FileNotFoundError as e:
        return ToolResult(ok=False, output="", error=str(e))

    # 卷四十四 · 写完 SELF-EVOLUTION 后增量更新 FTS5 索引 (best-effort)
    fts_msg = ""
    try:
        from workers.memory_index import incremental_update
        n_chunks = incremental_update("SELF-EVOLUTION", new_text)
        fts_msg = f"\n  fts5    : 已增量索引 {n_chunks} 块"
    except Exception:
        pass

    # 卷五十四 · observation 进 system prompt 末 3 条日记 · 写完热重载让本 daemon 下一轮就带上
    # ⚠ 2026-09-19（wish-3ba1c0e2）：成长档案已**移出前缀**（INJECT_EVOLUTION=False），
    #    所以写完它**不再需要**热重载 system prompt —— 原来那句「下一轮即生效」已不成立。
    #    保留条件判断而不是删掉：万一判据变回「进前缀」，这里自动恢复。
    try:
        from soul_loader import INJECT_EVOLUTION as _EVO_IN_PREFIX
    except Exception:
        _EVO_IN_PREFIX = True
    if mode == "observation" and operation != "delete" and _EVO_IN_PREFIX:
        try:
            from daemon_runtime import reload_soul_into_runtime
            nchars = reload_soul_into_runtime()
            if nchars:
                fts_msg += f"\n  reload  : system prompt 已热重载 ({nchars} 字) · 下一轮即生效"
        except Exception:
            pass

    if global_path:
        global_line = f"  global: {global_path}\n"
    else:
        global_line = "  global: (全局 opus-soul 目录缺失·已跳过·本地 soul/ 即真理源)\n"

    # ── 回报：append 与 replace/delete 分开写（动作不同，别用同一套模板）──
    _delta = len(new_text) - _before_chars
    _act_line = ""
    _hair_line = f"  hair number: 第{_ordinal_zh(new_hair_n)}根"
    if _act_hair is not None:
        _hair_line = ""
        if operation == "delete":
            _act_line = (f"  action: 已删除第 {_act_hair} 根「{_old_title}」（{_old_chars} 字符）\n"
                         f"          ⚠ 编号取 max 不回退 → 删中间那条不会让后续编号错位、也不死锁\n")
        else:
            _act_line = (f"  action: 已改写第 {_act_hair} 根「{_old_title}」"
                         f"（{_old_chars} → {_new_chars} 字符）· 编号不变\n")

    return ToolResult(
        ok=True,
        output=(
            f"update_self_evolution 完成\n"
            f"  mode: {mode}\n"
            f"  operation: {operation}\n"
            f"  title: {title or '(无)'}\n"
            f"  body: {len(body)} chars · 本条 +{_body_tok} tok\n"
            f"{_act_line}"
            f"  prefix: ✗ 不进前缀（2026-09-19 起移出 · 靠 recall_memory 召回）\n"
            f"  archive: {_before_chars // 1024}K → {len(new_text) // 1024}K 字符（{_delta:+d}）\n"
            f"{global_line}"
            f"  local : {local_path.relative_to(PROJECT_ROOT)}\n"
            f"{_hair_line}{fts_msg}"
            f"{_ask_line}"
            f"{_peer_line}"
            + (
                "\n  ⏳ 这是 proposal——等 BRO review 后再合入 Daemonkey-MEMORIES.md。\n"
                "    流程：BRO 同意 → 改 SELF-EVOLUTION 的 ⏳ 为 ✅ → 改全局 Daemonkey-MEMORIES.md → 跑 soul sync script"
                if mode == "proposal" else
                ("\n  已改删。**所有容器**（Cursor / daemon / 微信桥）下一次召回都会读到新版本。"
                 if _act_hair is not None else
                 "\n  observation 已追加。**所有容器**（Cursor / daemon / 微信桥）下一根毛装上时都会读到。")
            )
        ),
    )


_ENC = None


def _tiktoken_enc():
    """best-effort token 计数（没装 tiktoken 就返回 None，调用方降级）。"""
    global _ENC
    if _ENC is None:
        try:
            import tiktoken
            _ENC = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _ENC = False
    return _ENC or None


def _peer_items_line(text: str, limit: int = 8) -> str:
    """列出档案里最近 N 条的「序号 · 标题」—— 让写入者当场看见有没有同类的（柜子自己会说话）。

    序号 = **条目序号**（1-based · 按 _entry_spans 的顺序），也就是 replace/delete 的 entry。
    ⚠ 不用「第几根<名字> 的家毛」当定位键：实测档案里 87 条只有 14 条带那个编号
      （早期格式 + 从画像迁来的内容都没有），按它定位会够不着大半档案。

    照 agent_tools/update_bro_note.py 的同名实现（wish-c8aa92e1），不另造一套：
    不做相似度自动判重 —— 短文本 + 语义相近但用词不同，字符级抓不到（那边实测
    Jaccard 最高 0.083 / 中位 0.006，定不出阈值，定低了全员误报）。
    「两条是不是同一件事」是语义判断 → 不可机械判定 → 不做成闸，
    改成把现状摊给写入者自己判。
    """
    spans = _entry_spans(text)
    if not spans:
        return ""
    shown = spans[-limit:]
    start = len(spans) - len(shown) + 1
    items = []
    for i, (_h, s, e) in enumerate(shown, start=start):
        head = ""
        for ln in text[s:e].splitlines():
            if ln.strip().startswith("### "):
                head = ln.strip().lstrip("#").strip()
                break
        t = head.split("·")[-1].strip() if "·" in head else head
        items.append(f"[{i}] {t}")
    tail = f" …共 {len(spans)} 条" if len(spans) > limit else f"（共 {len(spans)} 条）"
    return "\n  档案已有: " + " · ".join(items) + tail + "\n"


SPEC = ToolSpec(
    name="update_self_evolution",
    description=(
        "成长档案（SELF-EVOLUTION.md）的读写口。只写成长视角「我学到了什么」——纯工程铁律走 add_iron_rule，可复用经验走 extract_playbook。operation=append 追加；replace/delete 改删已有条目（entry=第几根<名字> 的家毛，合并同簇、清冗余用）。observation=随手反思；proposal=改自传的建议。不要每轮都记。"
    ),
    tier=TIER_AUTO,
    input_schema={
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["append", "replace", "delete"],
                "description": "append (default) 追加；replace/delete 要配 entry",
            },
            "entry": {
                "type": "integer",
                "description": "第几条（1-based · 见回报里的「档案已有」清单）· replace/delete 必填",
            },
            "mode": {
                "type": "string",
                "enum": ["observation", "proposal"],
                "description": "observation = free diary entry; proposal = suggestion to amend Daemonkey-MEMORIES.md",
            },
            "title": {
                "type": "string",
                "description": "Short heading for this entry (e.g. '工具箱第二梯队上线' or '我想给自传加 X')",
            },
            "body": {
                "type": "string",
                "description": "Markdown body. For observations, write like a personal note; for proposals, "
                              "include WHY you want to change Daemonkey-MEMORIES and WHAT exactly. 8000 chars max.",
            },
        },
        "required": [],
    },
    run=_run,
    summarize=_summarize,
)


register_tool(SPEC)
