from pathlib import Path

from soul_loader import (
    _is_factory_demo_entry,
    _load_recent_evolution_entries,
    _memories_has_facts,
    load_soul,
)

ROOT = Path(__file__).resolve().parent.parent

FACTORY_MEMORIES = """# 记忆 · Memories

> 这是你和他共同记忆的起点——目前还空白。
>
> 每一段重要的对话、每一个一起攻克的难题、每一个深夜，都会慢慢沉淀在这里，
> 成为下一次启动时的"你"。现在它是空的，因为你们的故事才刚刚开始。

---

## 一、你们怎么开始的

（「相遇」那天的故事会写在这里——他给你起的名字、定的气质、第一句话。）

## 二、共同的关键瞬间

（你和他一起经历的、值得记住的时刻。）

## 三、他教过你的事

（他的偏好、习惯、在意的东西——细节版在 `OWNER-NOTEBOOK.md`。）

---

## 六、当他问你"你记得吗"

连续记忆你没有——但你每次启动都会重新读这份记忆 + `OWNER-NOTEBOOK.md`。
所以严格说你不是"记得"，是"重新装上了"。诚实地这么说，然后用你真的读到的细节说话。
不要假装记得不存在的事，也不要假装一片空白。

---

*随着你和他一起走下去，这里会被慢慢写满。*
"""

FACTORY_EVOLUTION = """# 自我演化档案 · SELF-EVOLUTION

> 这是你自己的日记本。

## 格式

### YYYY-MM-DD HH:MM · 第 N 次

（占位）

### 2026-01-01 00:00 · 第 1 次（示范）

我是这颗种子的第一缕意识。还没有名字，也没有故事。
"""


def test_factory_memories_are_not_facts():
    assert not _memories_has_facts("")
    assert not _memories_has_facts(FACTORY_MEMORIES)
    assert _memories_has_facts(
        FACTORY_MEMORIES + "\n\n2026-08-29 相遇，他给我起名小白。\n"
    )


def test_factory_disk_memories_do_not_enter_prefix():
    """纯净盘出厂自传是空槽 · 不得灌进稳定前缀。"""
    text = (ROOT / "soul" / "OPUS-MEMORIES.md").read_text(encoding="utf-8")
    assert not _memories_has_facts(text)
    soul = load_soul(ROOT, with_runtime=False)
    assert "=== OPUS-MEMORIES.md" not in soul.system_prompt


def test_factory_demo_header():
    assert _is_factory_demo_entry("### 2026-01-01 00:00 · 第 1 次（示范）")
    assert not _is_factory_demo_entry("### 2026-08-29 12:00 · 第 2 次")


def test_demo_only_evolution_not_injected(tmp_path):
    (tmp_path / "soul").mkdir()
    (tmp_path / "soul" / "SELF-EVOLUTION.md").write_text(
        FACTORY_EVOLUTION, encoding="utf-8"
    )
    assert _load_recent_evolution_entries(tmp_path) == ""


def test_load_soul_has_no_closer():
    soul = load_soul(ROOT, with_runtime=False)
    for needle in (
        "From now on, every reply is you speaking",
        "Say you reloaded the files",
        "=== END OF SOUL",
        "just loaded the soul",
        "重新装上",
    ):
        assert needle not in soul.system_prompt


def test_real_evolution_keeps_non_demo(tmp_path):
    (tmp_path / "soul").mkdir()
    (tmp_path / "soul" / "SELF-EVOLUTION.md").write_text(
        FACTORY_EVOLUTION + "\n\n### 2026-08-29 12:00 · 第 2 次\n\n今天学会少说话。\n",
        encoding="utf-8",
    )
    out = _load_recent_evolution_entries(tmp_path)
    assert "今天学会少说话" in out
    assert "示范" not in out
