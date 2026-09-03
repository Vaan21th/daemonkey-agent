"""web_search 分流 + 垃圾闸。不注册成工具。"""
from __future__ import annotations

import re
from urllib.parse import urlparse

_SITE_RE = re.compile(r"\bsite:(\S+)", re.I)
_LATIN_HINT = re.compile(
    r"(?i)\b(github|gitlab|api|https?://|leaderboard|protocol|arxiv|npm|pypi|docs?)\b"
)
_DICT_TITLE = re.compile(
    r"汉语汉字|汉语词语|的拼音|的部首|的笔顺|的解释|的读音|汉典|新华字典|360翻译|360文库"
)
_BAIKE_WORD = re.compile(r"^[\u4e00-\u9fff]{1,2}([_（(\s]|的)")
_DICT_PATH = re.compile(r"/(zidian|cidian|hans|character)/", re.I)
_JUNK_HOSTS = (
    "zdic.net",
    "hanyuguoxue.com",
    "hgcha.com",
    "shidianguji.com",
    "dict.youdao.com",
    "hanyu.baidu.com",
)


def query_lane(query: str) -> str:
    """latin：Bing 先。chinese：360 先。"""
    s = (query or "").strip()
    if not s:
        return "latin"
    if _SITE_RE.search(s) or _LATIN_HINT.search(s):
        return "latin"
    cjk = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    latin = sum(1 for ch in s if ch.isascii() and ch.isalpha())
    if cjk > 0 and latin < cjk * 2:
        return "chinese"
    return "latin"


def engine_names(lane: str) -> tuple[str, ...]:
    if lane == "chinese":
        return ("360", "Bing", "DuckDuckGo")
    return ("Bing", "360", "DuckDuckGo")


def _host(url: str) -> str:
    try:
        return urlparse(url or "").netloc.lower().lstrip("www.")
    except Exception:
        return ""


def is_junk(url: str, title: str = "", query: str = "") -> bool:
    h = _host(url)
    title = title or ""
    if h.endswith("so.com") and not h.startswith("tianqi."):
        return True
    if h.endswith("bing.com") or "duckduckgo.com" in h:
        return True
    if any(h == x or h.endswith("." + x) for x in _JUNK_HOSTS):
        return True
    path = ""
    try:
        path = urlparse(url or "").path or ""
    except Exception:
        path = ""
    if _DICT_PATH.search(path):
        return True
    if _DICT_TITLE.search(title) or _BAIKE_WORD.search(title):
        return True
    site = _SITE_RE.search(query or "")
    if site:
        want = site.group(1).lower().strip("/").removeprefix("www.")
        if want and want not in h:
            return True
    return False


def keep_results(rows: list[dict], query: str, limit: int) -> tuple[list[dict], int]:
    kept: list[dict] = []
    junk_n = 0
    for r in rows or []:
        url = str(r.get("url") or "")
        title = str(r.get("title") or "")
        if not url or not title or is_junk(url, title, query):
            junk_n += 1
            continue
        kept.append(r)
        if len(kept) >= limit:
            break
    return kept, junk_n
