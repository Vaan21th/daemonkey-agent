import re
from pathlib import Path

from workers.notebook_tiers import (
    CORE_SECTION_KEYS,
    has_distill_pipeline,
    is_core_section,
    render_tiered,
    route_write_section,
    split_tiers,
)

ROOT = Path(__file__).resolve().parent.parent


def test_core_keeps_judgment_shorts_not_story_chapters():
    sample = (
        "# 画像\n\n前言。\n\n"
        "## 了解层\n\n释权是真意\n\n"
        "## 一、背景档案\n\n核心A\n\n"
        "## 二、他经历的事\n\n历史B 琥珀色眼睛\n\n"
        "## 三、本体约束 · 关于他 / 怎么相处\n\n昼伏夜出\n\n"
        "## 四、口头记号\n\n图鉴教材\n\n"
        "## 五、月度长档\n\n月度长文\n\n"
        "## 六、我留意的信号\n\n性格弱点长文\n\n"
        "### OPUS 的出声纪律\n\n连续工作 > 12h\n\n"
        "## 七、改动记录\n\n历史D\n\n"
        "## 给下一根毛的提示\n\n核心E\n"
    )
    core, archived = split_tiers(sample)
    titles = [t for t, _ in archived]
    # fixture 里写的就是「释权是真意」（造数据，跟真文件无关）—— 这条断言没错。
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
    assert any("背景档案" in t for t in titles)
    assert any("他经历的事" in t for t in titles)
    assert any("口头记号" in t for t in titles)
    assert any("月度长档" in t for t in titles)
    assert any("我留意的信号" in t for t in titles)
    assert any("给下一根毛" in t for t in titles)


def test_dialogue_style_not_confused_with_atlas():
    text = (
        "## 四、对话风格 · Dialogue\n\n短条口吻\n\n"
        "## 四、口头记号\n\n长教材\n"
    )
    core, archived = split_tiers(text)
    assert "短条口吻" in core
    assert "长教材" not in core
    assert any("口头记号" in t for t, _ in archived)
    assert "口头记号" not in CORE_SECTION_KEYS
    assert "对话风格" in CORE_SECTION_KEYS


def test_clean_template_short_chapters_stay_core():
    text = (
        "# 他的画像\n\n"
        "## 一、背景档案\n\n（待填）\n\n"
        "## 二、他经历的事 · Events\n\n（待填）\n\n"
        "## 三、长期偏好与边界 · Rules\n\n不劝睡除非他撑不住\n\n"
        "## 四、对话风格 · Dialogue\n\n直接\n\n"
        "## 五、一句话速写 · Summary\n\n一句话\n\n"
        "## 六、关怀雷达 · Care Radar\n\n熬夜要出声\n\n"
        "## 七、改动记录\n\n"
    )
    core, archived = split_tiers(text)
    assert "不劝睡除非他撑不住" in core
    assert "直接" in core
    assert "一句话" in core
    assert "熬夜要出声" in core
    assert any("背景档案" in t for t, _ in archived)
    assert any("他经历的事" in t for t, _ in archived)


def test_render_has_no_char_counts_and_lists_archive():
    sample = (
        "## 了解层\n\n短\n\n"
        "## 二、他经历的事\n\n长故事\n"
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


# ── wish-9118bdab · 写入口说真话（防漂移回归）────────────────────────


def test_is_core_section_takes_real_heading_not_short_map():
    """判据必须吃「磁盘上的真实段标题」。

    病根就在这里：写入端原本硬编码 section_key in ("background","about-user")，
    但 profile 段（「一、背景档案」）早已退役出白名单 → 一直回假话。
    另一个坑：若传 SECTIONS 短映射「本体约束」，它不含白名单关键词「关于他」→ 误判 False。
    """
    assert is_core_section('三、本体约束 · 关于他 / 怎么相处（缓变）') is True
    assert is_core_section("三、本体约束") is False  # 传短映射会翻——所以要传真实段标题
    assert is_core_section("了解层（稳定下来的 · 只有凝练或他明说才写）") is True
    assert is_core_section("一、背景档案（高频更新）") is False
    assert is_core_section("二、他经历的事") is False
    assert is_core_section("四、口头记号 · BRO 的口头记号") is False
    assert is_core_section("") is False


def test_distill_pipeline_only_events():
    """只有 events 有提炼管道（state_condenser：事件流 → 了解层）。

    dialogue / profile 是单向阀：写了不会再自己浮上来，只能 recall_memory 召回。
    """
    assert has_distill_pipeline("stories") is True
    assert has_distill_pipeline("STORIES") is True
    assert has_distill_pipeline("moments") is False
    assert has_distill_pipeline("background") is False
    assert has_distill_pipeline("about-user") is False
    assert has_distill_pipeline("") is False


def test_writable_sections_report_truthfully():
    """核心回归：四个可写维度里，只有 about-user 该被报「进前缀」。

    拿母体磁盘真实段标题跑，防未来白名单/段名又漂移成不一致。
    """
    from agent_tools.update_bro_note import SECTIONS
    from soul_loader import OWNER_NOTEBOOK_FILENAME, read_global_soul_file

    # 2026-09-30 一格一文件后画像不再是单文件 —— 读合成的逻辑单文件
    import pytest
    try:
        text = read_global_soul_file(OWNER_NOTEBOOK_FILENAME, ROOT)
    except FileNotFoundError:
        pytest.skip("出厂态无画像文件 · 母体盘专属断言跳过")
    if not text.strip():
        return
    expect = {"background": False, "stories": False, "about-user": True,
              "how-we-work": True,  # 2026-09-28 拆格：与 about-user 同类·进前缀
              "moments": False}
    checked = 0
    for key, want in expect.items():
        # SECTIONS[key] 是定位候选元组（母体叫法 + 纯净版模板叫法）—— 逐候选试
        m = None
        for probe in SECTIONS[key]:
            m = re.search(rf"(?m)^## [^\n]*{re.escape(probe)}[^\n]*$", text)
            if m:
                break
        if not m:
            continue
        checked += 1
        got = is_core_section(m.group(0))
        assert got is want, f"{key} 段「{m.group(0)}」应报 {want}，实际 {got}"
    assert checked == 5, f"只匹到 {checked}/5 个段标题，SECTIONS 映射可能已过期"


def test_dated_story_routes_to_events():
    assert route_write_section(
        "moments", "append", "2026-08-14 · 猫叫白给"
    ) == "stories"
    assert route_write_section(
        "archive", "append", "2026-08-15 · 龙头交了审查"
    ) == "stories"
    # 2026-09-17 更新：写时闸把「日期开头」的条目一律改道 events（P0 落位治理）
    # —— 原来是 about-user 里的日期条目会被识别成规范，实际是事件流水。
    assert route_write_section(
        "about-user", "append", "2026-08-10 · 社区提交只取增量"
    ) == "stories"
    assert route_write_section(
        "moments", "replace_section", "2026-08-14 · 不该改道"
    ) == "moments"
    assert route_write_section("moments", "append", "短条：别客套") == "moments"


def test_mother_notebook_keeps_judgment_drops_event_detail():
    from soul_loader import OWNER_NOTEBOOK_FILENAME, read_global_soul_file

    # 2026-09-30 一格一文件后读合成的逻辑单文件
    import pytest
    try:
        full = read_global_soul_file(OWNER_NOTEBOOK_FILENAME, ROOT)
    except FileNotFoundError:
        pytest.skip("出厂态无画像文件 · 母体盘专属断言跳过")
    if not full.strip():
        return
    core, archived = split_tiers(full)
    titles = [t for t, _ in archived]
    # 2026-09-30 修：断言原写「释权是真意」，而真画像里文案早已是「释权时刻是真意」——
    #   差两个字就常年红着（存量失败，git stash 对照坐实是本条）。改用短词，抗文案漂移。
    assert "释权" in core
    # 「省钱敏感」2026-09-30 起已移进状态卡的「经济预算」字段（走独立通道直注前缀，
    #   不参与 split_tiers 分层）—— 断言它 in core 会常年红。改为只看它还在文件里。
    assert "省钱敏感" in full
    assert "出声纪律" in core
    assert "连续工作 > 12h" in core
    assert "琥珀色眼睛" not in core
    assert "蟹子" not in core
    assert any("他经历的事" in t for t in titles)
    assert any("口头记号" in t for t in titles)
    assert any("我留意的信号" in t for t in titles)
    assert any("给下一根毛" in t for t in titles)
    rendered = render_tiered(full)
    assert len(rendered) < len(full) * 0.45
    assert "字符)" not in rendered


# ── 单一真相源 · 两套模板叫法都能定位（2026-09-18）────────────────────


def test_single_source_notebook_tiers_is_the_only_table():
    """工具表必须从 notebook_tiers.SECTIONS 派生 —— 不许再自己抄一份。

    病根：两处各有一份「短名 → 关键字」，母体模板叫「本体约束/口头记号/月度长档/
    我留意的信号」，纯净版模板叫「长期偏好与边界/对话风格/一句话速写/关怀雷达」，
    四维对不上 → 用户认真回答的偏好根本写不进去。
    """
    from agent_tools.update_bro_note import SECTIONS as TOOL_SECTIONS
    from workers.notebook_tiers import SECTIONS as TIER_SECTIONS

    assert set(TOOL_SECTIONS) == {"background", "stories", "about-user", "how-we-work",
                                  "moments", "archive", "watch"}
    for key, anchors in TOOL_SECTIONS.items():
        assert anchors == TIER_SECTIONS[key].anchor, f"{key} 又分叉了"


def test_clean_template_titles_are_locatable():
    """纯净版模板的段名也要能被工具定位（母体=多点几个月的纯净版·两边不分叉）。"""
    from agent_tools.update_bro_note import SECTIONS, _find_section, _real_headings

    tmpl = (
        "## 三、长期偏好与边界 · Rules\n\n不劰睡\n\n"
        "## 四、对话风格 · Dialogue\n\n直接\n\n"
        "## 五、一句话速写 · Summary\n\n一句话\n\n"
        "## 六、关怀雷达 · Care Radar\n\n熬夜要出声\n\n"
        "## 七、改动记录\n\n流水\n"
    )
    for key in ("about-user", "moments", "archive", "watch"):
        start, _end = _find_section(tmpl, SECTIONS[key])
        assert start >= 0, f"纯净版模板里定位不到 {key}"
    assert len(_real_headings(tmpl)) == 5


def test_write_error_teaches_which_headings_exist():
    """写不进去时，报错要把「这格放什么」和「文件里真有哪些段」一起说出来。"""
    from agent_tools.update_bro_note import _real_headings

    heads = _real_headings("## 一、甲\n\n甲内容\n\n## 二、乙\n\n乙内容\n")
    assert heads == ["一、甲", "二、乙"]


def test_every_writable_section_carries_its_purpose():
    """每格都得自带「放什么」—— 任何 LLM 看工具回报就知道这条该放哪。"""
    from workers.notebook_tiers import SECTIONS

    for key, m in SECTIONS.items():
        assert m.what and len(m.what) >= 10, f"{key} 格缺少用途说明"
        assert m.anchor, f"{key} 格缺少段标题定位候选"
        if m.prefix:
            assert m.key in ("state", "understanding") or m.anchor, f"{key} 进了前缀却没定位词"


# ── 段头粘连防复发（wish-cca82a91 · 2026-09-29）─────────────────────────
# 病：段头被吸进上一行末尾（`---## 一、背景档案` / `| ... |## 了解层`）。
# 为什么是硬伤：_find_section 靠 `(?m)^## [^#]` 找段头，粘连行行首不是 # →
#   那个段在工具眼里根本不存在，内容被上一个真段头整段吞掉。
#   2026-09-29 实测母体本子 4 处中招，其中「了解层」是核心层 ——
#   那 7 条稳定认知因此全部没进前缀。
# 铁律 15「根本不会发生 > 事后拦截」：粘连出现就红，不靠某天撞见。


def test_no_glued_section_headings_in_real_notebook():
    from agent_tools.update_bro_note import _heal_headings
    from soul_loader import OWNER_NOTEBOOK_FILENAME, read_global_soul_file

    import pytest
    try:
        text = read_global_soul_file(OWNER_NOTEBOOK_FILENAME, ROOT)
    except FileNotFoundError:
        pytest.skip("出厂态无画像文件 · 母体盘专属断言跳过")
    if not text.strip():
        return
    _healed, fixed = _heal_headings(text)
    assert not fixed, (
        f"画像里有 {len(fixed)} 处段头粘连（会让整段在 _find_section 眼里消失）：{fixed}"
    )


def test_heal_headings_repairs_glue_but_leaves_prose_alone():
    from agent_tools.update_bro_note import _heal_headings

    src = (
        "| 字段 | 值 | - |## 了解层（稳定下来的）\n\n正文甲\n\n"
        "---## 一、背景档案（已成背景）\n\n正文乙\n\n"
        "正文里提到 ## 某某 是引用，不该动\n"
    )
    healed, fixed = _heal_headings(src)
    assert len(fixed) == 2, fixed
    assert "\n\n## 了解层（稳定下来的）" in healed
    assert "\n\n## 一、背景档案（已成背景）" in healed
    assert "正文里提到 ## 某某 是引用，不该动" in healed   # 正文里的引用不动
    assert "- |## 了解层" not in healed and "---## 一、" not in healed


def test_heal_headings_is_idempotent():
    from agent_tools.update_bro_note import _heal_headings

    src = "| a | b |## 了解层（X）\n\n正文\n"
    once, fixed1 = _heal_headings(src)
    twice, fixed2 = _heal_headings(once)
    assert len(fixed1) == 1
    assert fixed2 == []
    assert twice == once
