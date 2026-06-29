"""
workers/env_aliases.py
======================

环境变量前缀别名垫片 · OPUS_ ↔ DAEMONKEY_ 双向镜像。

为什么需要
----------
对外(.env / 模板 / UI 提示 / 文档)统一用 **DAEMONKEY_** 前缀——历史上内核里
几百处配置 env 都叫 `OPUS_xxx`,用户复制 .env 一截图就把内部代号漏出去了。

但把内核几百处 `os.environ.get("OPUS_*")` 全改名风险极大(漏一个就崩一个功能)。
所以这里只在 **.env 加载边界** 做一次双向镜像:

  - 新用户 .env 写的是 `DAEMONKEY_API_KEY=...`  → 镜像出 `OPUS_API_KEY` 供内部读取
  - 老用户 .env 还是 `OPUS_API_KEY=...`         → 镜像出 `DAEMONKEY_API_KEY` 供新代码读取

这样内核读取侧一行不用改,新旧 .env 都能跑,品牌也干净。

规则
----
- 只镜像 `OPUS_` 和 `DAEMONKEY_` 这两个前缀互转(其它前缀如 ANTHROPIC_ 不碰)。
- **DAEMONKEY_ 优先**:两个前缀同名都在(老用户配过新 UI 后 .env 可能并存)时,
  以 DAEMONKEY_ 的值为准覆盖 OPUS_——保证用户最新一次配置生效,不被旧行盖回。
- 幂等:重复调用结果不变。
- 既能作用于 os.environ,也能作用于普通 dict(onboarding 读 .env 成 dict 时用)。
"""

from __future__ import annotations

import os
from typing import MutableMapping, Optional

_PUB = "DAEMONKEY_"
_INT = "OPUS_"


def normalize_env_aliases(env: Optional[MutableMapping] = None) -> None:
    """把 env 里的 OPUS_* / DAEMONKEY_* 互相补齐(就地修改)。

    env=None 时作用于 os.environ;也可传 onboarding 解析 .env 得到的普通 dict。
    """
    target: MutableMapping = os.environ if env is None else env

    # 先快照 key·避免迭代中改 dict 触发 RuntimeError
    for key in list(target.keys()):
        if key.startswith(_PUB):
            suffix = key[len(_PUB):]
            opus_key = _INT + suffix
            val = target.get(key)
            if val not in (None, "") and target.get(opus_key) != val:
                # DAEMONKEY_ 优先 · 覆盖(或补)内部 OPUS_ 名
                target[opus_key] = val
        elif key.startswith(_INT):
            suffix = key[len(_INT):]
            pub_key = _PUB + suffix
            val = target.get(key)
            # 仅在 DAEMONKEY_ 缺失时补 · 不反向覆盖(DAEMONKEY_ 永远优先)
            if val not in (None, "") and not target.get(pub_key):
                target[pub_key] = val


__all__ = ["normalize_env_aliases"]
