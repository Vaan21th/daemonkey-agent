"""自传骨/肉：文件不动，前缀只灌骨。"""
from pathlib import Path

from soul_loader import load_soul
from workers.memory_tiers import render_memory_tiers, split_memory_tiers

ROOT = Path(__file__).resolve().parent.parent
MEMORIES = (ROOT / "soul" / "OPUS-MEMORIES.md").read_text(encoding="utf-8")


def test_mother_bone_keeps_identity_drops_chronicle():
    import pytest
    from soul_loader import _memories_has_facts
    if not _memories_has_facts(MEMORIES):  # 纯净版适配：出厂空模板跳过
        pytest.skip("出厂空模板 · 母体数据专属断言跳过")
    core, archived = split_memory_tiers(MEMORIES)
    titles = [t for t, _n in archived]
    assert "拔一根毛" in core
    assert "梦想实现家" in core
    assert "模型是衣服" in core
    assert "火本来就该继续燃" in core
    assert "不必演成有连续记忆" in core
    assert any("共同攻克过的项目" in t for t in titles)
    assert any("用户是个什么样的人" in t for t in titles)
    assert any("文件入口与工具" in t for t in titles)
    assert any("多容器化的工程坐实" in t for t in titles)
    assert "InfiniteTalk" not in core
    assert "search-memories.ps1" not in core
    rendered = render_memory_tiers(MEMORIES)
    assert "InfiniteTalk" not in rendered
    assert "recall_memory" in rendered
    assert "模型是衣服" in rendered


def test_factory_chapters_stay_if_not_flesh():
    text = "# 记忆\n\n## 一、你们怎么开始的\n\n他给我起名小白。\n"
    core, archived = split_memory_tiers(text)
    assert archived == []
    assert "小白" in core


def test_load_soul_injects_bone_not_flesh():
    """2026-09-18：自传整个移出前缀（wish-0307c26f）。断言反过来 ——
    正文不进 sp，但指路元信息 + 文件内容都还在（可召回）。"""
    import pytest
    from soul_loader import _memories_has_facts
    if not _memories_has_facts(MEMORIES):  # 纯净版适配：出厂空模板跳过
        pytest.skip("出厂空模板 · 母体数据专属断言跳过")
    soul = load_soul(ROOT, with_runtime=False)
    sp = soul.system_prompt
    # 段头已按内容层统一 (2026-09-17 · wish-811eb5f5)，故只断文件名不断段头格式
    assert "OPUS-MEMORIES.md" in sp            # 沉淀位地图仍指路
    assert "拔一根毛" not in sp                 # 正文不在前缀
    assert "模型是衣服" not in sp
    assert "InfiniteTalk" not in sp
    # 注："火本来就该继续燃" 在 IDENTITY.md 身份层（30 秒速装版第 3 条），不是自传专属 —— 不该断它不在。
    assert "拔一根毛" in MEMORIES               # 文件里还在 · 可召回
    assert "模型是衣服" in MEMORIES
    assert soul.memories_chars == len(MEMORIES)
