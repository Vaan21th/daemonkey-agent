"""
test_tier_demo.py
=================

\u4e09\u6863\u4fe1\u4efb\u7cfb\u7edf\u00b7\u7eaf\u672c\u5730\u6f14\u793a\u3002

**\u4e0d\u8c03 LLM\u3002\u4e0d\u70e7\u94b1\u3002\u4e0d\u771f\u7684\u6267\u884c\u4efb\u4f55\u5de5\u5177**\u3002
\u53ea\u662f\u8ba9 BRO \u4e00\u773c\u770b\u6e05\u4e09\u4e2a\u68a3\u4f4d\u5728 daemon \u91cc\u5230\u5e95\u9577\u4ec0\u9ebc\u6a23\u3001\u8981\u4ec0\u9ebc\u6309\u9375\u3002

\u8dd1\u6cd5:
    .\\.venv\\Scripts\\python.exe tools\\test_tier_demo.py

\u5176\u5be6 confirm \u52a8\u4f5c\u4e0d\u4f1a\u53eb spec.run(args)\u2014\u2014\u6240\u4ee5\u5373\u4f7f\u4f60\u5728\u300c\u8a66\u6539 .env\u300d\u90a3\u4e00\u6b65\u8f38\u5165\u4e86 do it\uff0c
.env \u4e5f\u4e0d\u6703\u88ab\u52d5\u3002\u9019\u662f\u4e00\u500b\u300c\u770b\u63d0\u793a\u300d\u811a\u672c\uff0c\u4e0d\u662f\u300c\u52d5\u4f5c\u300d\u811a\u672c\u3002
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console
from rich.rule import Rule

from agent_tools import REGISTRY
from daemon_ui import YoloState, make_confirm


def main() -> int:
    console = Console()
    yolo = YoloState()
    confirm = make_confirm(console, yolo)

    shell = REGISTRY["shell_exec"]
    write = REGISTRY["write_file"]
    read = REGISTRY["read_file"]

    demos = [
        (
            "\u6f14\u793a 1\uff1a\u7da0\u6846 AUTO\u2014\u2014\u81ea\u52d5\u8dd1\uff0c\u4e0d\u554f\u4f60\u3002OPUS \u8c03 git status",
            shell, {"command": "git status"},
        ),
        (
            "\u6f14\u793a 2\uff1a\u7da0\u6846 AUTO\u2014\u2014OPUS \u8b80 README.md",
            read, {"path": "README.md"},
        ),
        (
            "\u6f14\u793a 3\uff1a\u9ec4\u6846 CONFIRM\u2014\u2014OPUS \u8c03 mkdir test_dir\uff0c\u4f1a\u7b49\u4f60\u8f93\u5165 y/n/a",
            shell, {"command": "mkdir test_dir"},
        ),
        (
            "\u6f14\u793a 4\uff1a\u9ec4\u6846 CONFIRM\u2014\u2014OPUS \u5728 sessions/ \u4e0b\u5beb\u4e2a note.md\uff0c\u8b93\u4f60\u8f93\u5165 y/n/a",
            write, {"path": "sessions/note.md", "content": "hello", "mode": "create"},
        ),
        (
            "\u6f14\u793a 5\uff1a\u7d05\u6846 GUARD\u2014\u2014OPUS \u8a66\u6539 .env\uff0c\u5fc5\u9808\u8f38 'do it'\u3002y \u4e0d\u7b97\uff0c\u7a7a\u56de\u8eca\u4e0d\u7b97\u3002",
            write, {"path": ".env", "content": "OPUS_MODEL=test", "mode": "overwrite"},
        ),
        (
            "\u6f14\u793a 6\uff1a\u7d05\u6846 GUARD\u2014\u2014OPUS \u8a66 rm -rf \u67d0\u500b\u76ee\u9304\uff0c\u540c\u6a23\u5fc5\u9808\u8f93 'do it'",
            shell, {"command": "rm -rf foo/bar"},
        ),
    ]

    console.print(
        Rule("[bold]\u4e09\u6863\u4fe1\u4efb\u7cfb\u7d71 \u00b7 \u672c\u5730\u6f14\u793a[/] \u00b7 "
             "\u4e0d\u70d2\u9322 \u00b7 \u4e0d\u771f\u8dd1\u5de5\u5177", style="#9F7AEA")
    )
    console.print(
        "\n  [dim]\u4e0b\u9762 6 \u500b\u6a21\u62df\u8c03\u7528\uff0cdaemon \u4e2d OPUS \u8b66\u9047\u5230\u8fd9\u4e9b args \u6642\u4f60\u4f1a\u770b\u5230\u4ec0\u9ebc\u3002"
        "\u4e0d\u6703\u771f\u6539\u4efb\u4f55\u6587\u4ef6\u3002[/]\n"
    )

    for label, spec, args in demos:
        console.print()
        console.print(f"[bold]{label}[/]")
        decision = confirm(spec, args)
        verdict_color = {"go": "#48BB78", "skip": "#ECC94B", "abort": "#F56565"}.get(decision, "white")
        console.print(
            f"  \u2192 confirm \u8fd4\u56de: [bold {verdict_color}]{decision}[/]   "
            f"[dim](\"go\" = \u771f\u8dd1 / \"skip\" = \u4e0d\u8dd1\u4f46\u7ee7\u7eed\u5bf9\u8bdd / \"abort\" = OPUS \u6574\u4e2a\u4e2d\u65ad)[/]"
        )

    console.print()
    console.print(Rule("[bold]\u6f14\u793a\u5b8c\u6210[/]", style="#9F7AEA"))
    console.print(
        "\n  [bold]\u4f60\u770b\u5230\u4e86\u4ec0\u4e48[/]\n"
        "    \u00b7 \u7da0\u6846\u51fa\u73b0 \u2192 daemon \u76f4\u63a5\u8dd1\uff0c\u4f60\u4e0d\u9700\u8981\u52a8\n"
        "    \u00b7 \u9ec4\u6846\u51fa\u73b0 \u2192 daemon \u505c\u4e0b\u6765\u7b49\u4f60\u8f93 y/n/a\u3002\u7a7a\u56de\u8f66\u4f1a\u88ab\u53cd\u590d\u63d0\u9192\uff0c\u4e0d\u4f1a\u9ed8\u8ba4 skip\u3002\n"
        "    \u00b7 \u7ea2\u6846\u51fa\u73b0 \u2192 daemon \u505c\u4e0b\u6765\u7b49\u4f60\u8f93 'do it'\u3002y \u4e0d\u7b97\u3002yolo \u5bf9\u5b83\u4e5f\u65e0\u6548\u3002\n\n"
        "  [dim]\u9019\u4e2a\u811a\u672c\u4e0d\u4f1a\u771f\u6539\u4efb\u4f55\u6587\u4ef6 / \u4e0d\u4f1a\u8dd1\u4efb\u4f55\u547d\u4ee4 / \u4e0d\u4f1a\u8c03 LLM\u3002"
        "\u53ef\u4ee5\u91cd\u8dd1\u591a\u6b21\u770b\u4e09\u6863\u53cd\u5e94\u3002[/]\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
