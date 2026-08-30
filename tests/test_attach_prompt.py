from workers.attach_prompt import extract_prompt, for_llm, for_ui

DUMP = (
    "[用户上传了 1 个附件 · 下面每个都给了『已存』路径]\n"
    "直接 look_at(path=对应『已存』路径, question=...)\n"
    "图1 (image.png) · 已存: F:/tmp/data/runtime/attachments/x_image.png\n"
    "路径 B · 当前模型 (deepseek-ai/DeepSeek-V4-Flash) 不支持视觉\n"
    "竞速池 winner → glm-5v-turbo (glm-5v-turbo) · attempts: glm-5v-turbo=9.19s\n"
    "图片: image/png · ~21 KB (base64)\n"
    "───\n"
    "图上写着缓存 84%。\n---\n"
    "好像有点低？？"
)


def test_for_ui_strips_path_b():
    assert for_ui(DUMP) == "好像有点低？？"


def test_for_ui_leaves_plain():
    assert for_ui("今天天气怎么样") == "今天天气怎么样"


def test_for_llm_prepends_meta():
    out = for_llm("好像有点低？？", {"attach_prompt": "PREFIX\n---\n"})
    assert out.startswith("PREFIX")
    assert out.endswith("好像有点低？？")


def test_for_llm_no_double_on_old_row():
    assert for_llm(DUMP, {"attach_prompt": "PREFIX\n---\n"}) == DUMP


def test_extract_prompt_keeps_header():
    p = extract_prompt(DUMP)
    assert p.startswith("[用户上传了")
    assert p.endswith("---\n")
    assert "好像有点低" not in p
