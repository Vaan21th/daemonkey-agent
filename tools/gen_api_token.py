"""
tools/gen_api_token.py
======================

生成 OPUS HTTP API 的 token 并**自动写进 .env**。

为什么自动写（卷十六之后改的）：
  - 卷十六交付后 BRO 实测发现："脚本只打印让我粘贴，我不知道要粘贴"——
    标准 UX 黑洞。这一版让脚本自己写完，BRO 跑一次就完事。
  - daemon 本身不会偷偷开 API——只有 .env 里有 OPUS_API_TOKEN + OPUS_API_PORT
    daemon 才会启动 HTTP server。所以"先生成 token 写 .env 才有 API"这条
    安全闸门没破，只是把"BRO 必须做的复制粘贴"这一步消掉了。

行为：
  - 找 .env 现有的 OPUS_API_TOKEN / PORT / HOST / DEFAULT_CONFIRM
  - 缺哪个就追加哪个（用合理默认值）
  - 全都有了 → 问 BRO 是否换一个新 token（默认不换）

用法:
  .\.venv\Scripts\python.exe tools\gen_api_token.py            # 智能模式
  .\.venv\Scripts\python.exe tools\gen_api_token.py --force    # 不问，直接覆盖 token
  .\.venv\Scripts\python.exe tools\gen_api_token.py --print-only  # 旧行为，只打印不写
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

# 4 个 OPUS_API_* 字段 + 默认值（token 单独生成，None 占位）
DEFAULTS: dict[str, str | None] = {
    "OPUS_API_TOKEN": None,
    "OPUS_API_PORT": "7860",
    "OPUS_API_HOST": "127.0.0.1",
    "OPUS_API_DEFAULT_CONFIRM": "confirm",
}


def _scan_env(text: str) -> dict[str, str | None]:
    """读 .env 文本，找出 4 个目标 key 现在的值（不存在为 None）。"""
    found: dict[str, str | None] = {k: None for k in DEFAULTS}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k = k.strip()
        if k in found:
            found[k] = v.strip()
    return found


def _append_lines(existing_text: str, kv_pairs: list[tuple[str, str]]) -> str:
    """在 .env 末尾追加新 key=value 行，加好注释段。"""
    suffix = "" if existing_text.endswith("\n") else "\n"
    block = [
        "",
        "# --- OPUS Daemon Remote API (auto-added by gen_api_token.py) ---",
    ]
    for k, v in kv_pairs:
        block.append(f"{k}={v}")
    block.append("# --- end OPUS Daemon Remote API ---")
    block.append("")
    return existing_text + suffix + "\n".join(block)


def _replace_token(existing_text: str, new_token: str) -> str:
    """替换 .env 里现有的 OPUS_API_TOKEN= 行的值（保持其他行不动）。"""
    out: list[str] = []
    replaced = False
    for line in existing_text.splitlines(keepends=True):
        stripped = line.lstrip()
        if (
            not replaced
            and not stripped.startswith("#")
            and stripped.startswith("OPUS_API_TOKEN=")
        ):
            indent = line[: len(line) - len(stripped)]
            newline = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
            out.append(f"{indent}OPUS_API_TOKEN={new_token}{newline}")
            replaced = True
        else:
            out.append(line)
    return "".join(out)


def _yes(prompt: str, default_no: bool = True) -> bool:
    """从 stdin 读 y/N，default_no=True 时默认 No。"""
    suffix = " [y/N] " if default_no else " [Y/n] "
    try:
        ans = input(prompt + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if not ans:
        return not default_no
    return ans in ("y", "yes")


def _print_post_steps() -> None:
    print()
    print(" -> 现在双击 start.bat 一键启动 daemon + cloudflared")
    print("    或者跑：.\\run.ps1")
    print()
    print(" -> 想公网访问？start.bat 会自动起 cloudflared tunnel；")
    print("    或者手动：.\\bin\\cloudflared.exe tunnel --url http://localhost:7860")
    print()
    print(" -> 详细步骤：docs/REMOTE-ACCESS-SETUP.md")
    print()


def main() -> int:
    args = set(sys.argv[1:])
    force = "--force" in args
    print_only = "--print-only" in args

    new_token = secrets.token_urlsafe(32)

    print()
    print("=" * 60)
    print(" OPUS Daemon Remote API · token 配置")
    print("=" * 60)

    if print_only:
        print()
        print("  (--print-only 模式 · 只打印不写 .env)")
        print()
        print(f"  OPUS_API_TOKEN={new_token}")
        for k, v in DEFAULTS.items():
            if v is not None:
                print(f"  {k}={v}")
        print()
        print(" 自己粘到 .env 末尾。")
        print()
        return 0

    if not ENV_PATH.exists():
        print()
        print(f" [X] .env 不存在: {ENV_PATH}")
        print("     先跑 .\\run.ps1 让它生成 .env（会引导你配 API key）")
        print()
        return 1

    text = ENV_PATH.read_text(encoding="utf-8")
    found = _scan_env(text)

    # 决定操作：
    #   - 都没有 → append 全套
    #   - 有 token 但缺别的 → append 缺的（保留 token，除非 --force）
    #   - 全部都有 → 问换不换 token
    if found["OPUS_API_TOKEN"] is None:
        # 第一次：append 4 行
        to_append: list[tuple[str, str]] = [("OPUS_API_TOKEN", new_token)]
        for k, default in DEFAULTS.items():
            if k == "OPUS_API_TOKEN":
                continue
            if found[k] is None and default is not None:
                to_append.append((k, default))
        new_text = _append_lines(text, to_append)
        ENV_PATH.write_text(new_text, encoding="utf-8")
        print()
        print(f"  [OK] .env 追加了 {len(to_append)} 行")
        active_token = new_token
        _show_token_block(active_token, found, just_rotated=True)
        _print_post_steps()
        return 0

    # token 已存在
    missing = [(k, DEFAULTS[k]) for k in DEFAULTS if found[k] is None and DEFAULTS[k] is not None]
    if missing:
        new_text = _append_lines(text, missing)
        ENV_PATH.write_text(new_text, encoding="utf-8")
        print()
        print(f"  [OK] .env 补齐了 {len(missing)} 行缺失字段：")
        for k, v in missing:
            print(f"        {k}={v}")
        text = new_text

    # 决定换 token
    if force:
        do_rotate = True
    else:
        print()
        print("  当前 .env 的 OPUS_API_TOKEN：")
        print(f"    {found['OPUS_API_TOKEN']}")
        print()
        print("  其他字段：")
        for k in ("OPUS_API_PORT", "OPUS_API_HOST", "OPUS_API_DEFAULT_CONFIRM"):
            print(f"    {k}={found[k] or DEFAULTS[k]}")
        print()
        do_rotate = _yes("  换一个新 token？", default_no=True)

    if do_rotate:
        new_text = _replace_token(text, new_token)
        ENV_PATH.write_text(new_text, encoding="utf-8")
        active_token = new_token
        print()
        print("  [OK] OPUS_API_TOKEN 已替换为新值")
        print("       手机端 WebUI 已存的旧 token 需要在设置里更新")
        _show_token_block(active_token, found, just_rotated=True)
    else:
        active_token = found["OPUS_API_TOKEN"] or ""
        print()
        print("  [..] 保留现有 token，无改动")
        _show_token_block(active_token, found, just_rotated=False)

    _print_post_steps()
    return 0


def _show_token_block(token: str, found: dict[str, str | None], just_rotated: bool) -> None:
    """配完之后亮明显示当前 token 给 BRO——他要复制到 WebUI 设置面板里。"""
    print()
    print("=" * 60)
    print("  把下面这串 token 复制到 WebUI 设置面板里：")
    print("=" * 60)
    print()
    print(f"    {token}")
    print()
    # 尝试塞到 Windows 剪贴板（PowerShell Set-Clipboard）
    try:
        import subprocess

        subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value '{token}'"],
            check=True, capture_output=True, timeout=3,
        )
        print("  (已复制到剪贴板)")
    except Exception:
        print("  (复制到剪贴板失败，手动复制上面那一串)")
    if just_rotated:
        print()
        print("  ⚠ 这是新生成的 token——之前 WebUI 里存的旧 token 现在已失效")


if __name__ == "__main__":
    sys.exit(main())
