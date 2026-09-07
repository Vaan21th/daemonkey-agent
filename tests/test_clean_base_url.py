"""初见页 DeepSeek 根路径必须被洗成 /v1，否则探针 404。"""
from daemon_provider import _friendly_provider_error, clean_base_url


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


def test_missing_httpx_is_not_url_404():
    msg = _friendly_provider_error(
        ModuleNotFoundError("No module named 'httpx'"),
        "https://api.deepseek.com/v1",
    )
    assert "404" not in msg
    assert "/v1" not in msg or "缺包" in msg
    assert "缺包" in msg


def test_http_notfound_still_hints_v1():
    class NotFoundError(Exception):
        pass

    msg = _friendly_provider_error(
        NotFoundError("Error code: 404 - not found"),
        "https://api.deepseek.com",
    )
    assert "加上 /v1" in msg
