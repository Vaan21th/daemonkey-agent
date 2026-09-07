"""初见页 DeepSeek 根路径必须被洗成 /v1，否则探针 404。"""
from daemon_provider import clean_base_url


def test_deepseek_root_gets_v1():
    assert clean_base_url("https://api.deepseek.com") == "https://api.deepseek.com/v1"


def test_deepseek_already_v1_stays():
    assert clean_base_url("https://api.deepseek.com/v1") == "https://api.deepseek.com/v1"


def test_deepseek_full_endpoint_stripped_then_v1():
    got = clean_base_url("https://api.deepseek.com/chat/completions")
    assert got == "https://api.deepseek.com/v1"


def test_other_hosts_untouched():
    u = "https://open.bigmodel.cn/api/paas/v4"
    assert clean_base_url(u) == u
