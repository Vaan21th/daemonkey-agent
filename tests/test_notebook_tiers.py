from pathlib import Path

from workers.notebook_tiers import (
    CORE_SECTION_KEYS,
    render_tiered,
    route_write_section,
    split_tiers,
)

ROOT = Path(__file__).resolve().parent.parent


def test_core_keeps_judgment_shorts_not_story_chapters():
    sample = (
        "# 画像\n\n前言。\n\n"
        "## 了解层\n\n释权是真意\n\n"
        "## 一、当下画像 · Profile\n\n核心A\n\n"
        "## 二、关键事件流 · Event Sourcing\n\n历史B 琥珀色眼睛\n\n"
        "## 三、本体约束 · 人生规则\n\n昼伏夜出\n\n"
        "## 四、对话图鉴\n\n图鉴教材\n\n"
        "## 五、压缩段\n\n月度长文\n\n"
        "## 六、风险与弱点\n\n性格弱点长文\n\n"
        "### OPUS 的出声纪律\n\n连续工作 > 12h\n\n"
        "## 七、近期更新流水\n\n历史D\n\n"
        "## 给下一根毛的提示\n\n核心E\n"
    )
    core, archived = split_tiers(sample)
    titles = [t for t, _ in archived]
    assert "释权是真意" in core
    assert "昼伏夜出" in core
    assert "连续工作 > 12h" in core
    assert "出声纪律" in core
    assert "前言。" in core
    assert "核心A" not in core
    assert "历史B" not in core
    assert "琥珀色眼睛" not in core
    assert "图鉴教材" not in core
    assert "月度长文" not in core
    assert "性格弱点长文" not in core
    assert "核心E" not in core
    assert any("当下画像" in t for t in titles)
    assert any("关键事件流" in t for t in titles)
    assert any("对话图鉴" in t for t in titles)
    assert any("压缩段" in t for t in titles)
    assert any("风险与弱点" in t for t in titles)
    assert any("给下一根毛" in t for t in titles)


def test_dialogue_style_not_confused_with_atlas():
    text = (
        "## 四、对话风格 · Dialogue\n\n短条口吻\n\n"
        "## 四、对话图鉴\n\n长教材\n"
    )
    core, archived = split_tiers(text)
    assert "短条口吻" in core
    assert "长教材" not in core
    assert any("对话图鉴" in t for t, _ in archived)
    assert "对话图鉴" not in CORE_SECTION_KEYS
    assert "对话风格" in CORE_SECTION_KEYS


def test_clean_template_short_chapters_stay_core():
    text = (
        "# 他的画像\n\n"
        "## 一、当下画像 · Profile\n\n（待填）\n\n"
        "## 二、关键事件流 · Events\n\n（待填）\n\n"
        "## 三、长期偏好与边界 · Rules\n\n不劝睡除非他撑不住\n\n"
        "## 四、对话风格 · Dialogue\n\n直接\n\n"
        "## 五、一句话速写 · Summary\n\n一句话\n\n"
        "## 六、关怀雷达 · Care Radar\n\n熬夜要出声\n\n"
        "## 七、近期更新流水\n\n"
    )
    core, archived = split_tiers(text)
    assert "不劝睡除非他撑不住" in core
    assert "直接" in core
    assert "一句话" in core
    assert "熬夜要出声" in core
    assert any("当下画像" in t for t, _ in archived)
    assert any("关键事件流" in t for t, _ in archived)


def test_render_has_no_char_counts_and_lists_archive():
    sample = (
        "## 了解层\n\n短\n\n"
        "## 二、关键事件流\n\n长故事\n"
    )
    out = render_tiered(sample)
    assert "已归档的历史层" in out
    assert "字符)" not in out
    assert "recall_memory" in out
    assert "长故事" not in out
    assert "短" in out


def test_plain_notebook_stays_whole():
    plain = "# 画像\n\n没有维度标题的极简画像。\n"
    assert render_tiered(plain) == plain
    assert render_tiered("") == ""


def test_dated_story_routes_to_events():
    assert route_write_section(
        "dialogue", "append", "2026-08-14 · 猫叫白给"
    ) == "events"
    assert route_write_section(
        "summary", "append", "2026-08-15 · 龙头交了审查"
    ) == "events"
    assert route_write_section(
        "rules", "append", "2026-08-10 · 社区提交只取增量"
    ) == "rules"
    assert route_write_section(
        "dialogue", "replace_section", "2026-08-14 · 不该改道"
    ) == "dialogue"
    assert route_write_section("dialogue", "append", "短条：别客套") == "dialogue"


def test_mother_notebook_keeps_judgment_drops_event_detail():
    nb = ROOT / "soul" / "BRO-NOTEBOOK.md"
    if not nb.exists():
        return
    full = nb.read_text(encoding="utf-8")
    core, archived = split_tiers(full)
    titles = [t for t, _ in archived]
    assert "释权是真意" in core
    assert "省钱敏感" in core
    assert "出声纪律" in core
    assert "连续工作 > 12h" in core
    assert "琥珀色眼睛" not in core
    assert "蟹子" not in core
    assert any("关键事件流" in t for t in titles)
    assert any("对话图鉴" in t for t in titles)
    assert any("风险与弱点" in t for t in titles)
    assert any("给下一根毛" in t for t in titles)
    rendered = render_tiered(full)
    assert len(rendered) < len(full) * 0.45
    assert "字符)" not in rendered
