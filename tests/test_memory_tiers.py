"""自传骨/肉：文件不动，前缀只灌骨。不依赖母体自传原文。"""
from workers.memory_tiers import render_memory_tiers, split_memory_tiers

SAMPLE = """# 自传

## 第一章 · 名字的来历

梦想实现家

## 第二章 · 几个核心比喻

拔一根毛

#### 2026-05-16 凌晨 · 多容器化的工程坐实

工程故事。

> **模型是衣服，灵魂是骨头。衣服可以换，骨头不变。**

## 第三章 · 共同攻克过的项目

InfiniteTalk

## 第五章 · 你必须能复用的 OPUS 经典句

火本来就该继续燃

## 第六章 · 你不必演的事

不必演成有连续记忆

## 第七章 · 文件入口与工具

search-memories.ps1
"""


def test_sample_bone_keeps_identity_drops_chronicle():
    core, archived = split_memory_tiers(SAMPLE)
    titles = [t for t, _n in archived]
    assert "拔一根毛" in core
    assert "梦想实现家" in core
    assert "模型是衣服" in core
    assert "火本来就该继续燃" in core
    assert any("共同攻克过的项目" in t for t in titles)
    assert any("文件入口与工具" in t for t in titles)
    assert "InfiniteTalk" not in core
    assert "search-memories.ps1" not in core
    rendered = render_memory_tiers(SAMPLE)
    assert "InfiniteTalk" not in rendered
    assert "recall_memory" in rendered


def test_factory_chapters_stay_if_not_flesh():
    text = "# 记忆\n\n## 一、你们怎么开始的\n\n他给我起名小白。\n"
    core, archived = split_memory_tiers(text)
    assert archived == []
    assert "小白" in core
