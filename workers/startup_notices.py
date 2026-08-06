"""
startup_notices.py
==================

升级后首条对话 · 把"更新了什么 + 缺什么依赖"递到 OPUS 手边 (2026-07-30 · 0.8.2 hotfix)

问题 (BRO 原话):
  "更新之后用户在升级后的对话框看不到升级内容，这个可以优化一下"
  "没有依赖可以启动，但要去点环境补依赖——也可以在对话中提醒升级后的用户"

方案 (NLP First · 不是硬弹窗):
  1. daemon 启动时 refresh_startup_notices():
     - 版本比对: data/runtime/last_seen_core_version vs core_manifest.json
       · 不一致 = 刚升级 → 生成升级通知 (带上 log_ref 的 changelog md 摘要)
       · 文件不存在 = 首次安装 → 只记录版本 · 不通知 (新装用户不需要 changelog)
     - 可选依赖体检: find_spec 探测 (不真 import · 零副作用)
       · 缺失项生成"去环境页点【开始安装】补装"提醒
     - 落 data/runtime/startup_notices.json
  2. telemetry 每 turn consume_startup_notices():
     · 有内容 → 拼进 system prompt → OPUS 用自己的话自然转告用户
     · 拼完即删 (一次性) → 不重复打扰
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from datetime import datetime

_RUNTIME_DIR = pathlib.Path("data/runtime")
_NOTICES_FILE = _RUNTIME_DIR / "startup_notices.json"
_LAST_SEEN_FILE = _RUNTIME_DIR / "last_seen_core_version"
_MANIFEST_FILE = pathlib.Path("core_manifest.json")

# 可选依赖体检清单: (import spec 名, pip 包名, 缺了什么功能受影响, 仅 win32)
# · 主框架 (fastapi/uvicorn/openai/anthropic/dotenv/rich) 缺了 daemon 根本起不来 · 不用查
# · find_spec 只探测不 import · 零副作用
_OPTIONAL_DEPS: list[tuple[str, str, str, bool]] = [
    ("PyQt6", "PyQt6", "桌宠本体", False),
    ("PyQt6.QtMultimedia", "PyQt6", "桌宠完成提示音 (6.2+ 已并入主包·无需独立 wheel)", False),
    ("playwright", "playwright", "浏览器的手/眼 (browser_act/browser_fetch)", False),
    ("qrcode", "qrcode", "微信扫码登录二维码", False),
    ("requests", "requests", "微信渠道", False),
    ("winotify", "winotify", "Windows 系统通知", True),
    ("jieba", "jieba", "中文记忆全文检索", False),
    ("PIL", "Pillow", "图片理解/压缩", False),
    ("PyPDF2", "PyPDF2", "PDF 文档读取", False),
    ("docx", "python-docx", "Word 文档读取", False),
    ("pptx", "python-pptx", "PPT 文档读取", False),
    ("openpyxl", "openpyxl", "客户档案 Excel 导入", False),
    ("multipart", "python-multipart", "文件上传", False),
    ("cryptography", "cryptography", "微信发图片/文件加密", False),
    ("psutil", "psutil", "后台服务管理", False),
    ("ruff", "ruff", "代码自检", False),
]


def _read_manifest_version() -> tuple[str, str]:
    """返回 (core_version, log_ref 相对路径) · 读不到给空串。"""
    try:
        data = json.loads(_MANIFEST_FILE.read_text(encoding="utf-8"))
        return str(data.get("core_version") or ""), str(data.get("log_ref") or "")
    except Exception:
        return "", ""


def _read_changelog(log_ref: str, max_chars: int = 2500) -> str:
    """读更新说明 · log_ref 两种形态都兼容:
    - 是仓库相对路径 → 读文件全文 (截断防爆 token)
    - 不是路径 = 累积版本日志文本 (" · " 分隔) → 取末段 (当前版本描述)
    """
    if not log_ref:
        return ""
    try:
        p = pathlib.Path(log_ref)
        if p.is_file():
            text = p.read_text(encoding="utf-8").strip()
            if len(text) > max_chars:
                text = text[:max_chars].rstrip() + "\n…(完整版见 " + log_ref + ")"
            return text
        # 累积日志文本: 取最后一个版本号段 (版本间/段内都混用 " · " · 按版本号模式切才稳)
        import re
        matches = list(re.finditer(r"\d+\.\d+\.\d+[a-zA-Z0-9]*\(", log_ref))
        if matches:
            text = log_ref[matches[-1].start():].strip()
        else:
            text = log_ref.split(" · ")[-1].strip() if " · " in log_ref else log_ref.strip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "…"
        return text
    except Exception:
        return ""


def _check_missing_deps() -> list[dict]:
    """find_spec 体检可选依赖 · 返回缺失列表。"""
    missing: list[dict] = []
    is_win = sys.platform == "win32"
    for spec_name, pip_name, feature, win_only in _OPTIONAL_DEPS:
        if win_only and not is_win:
            continue
        try:
            if importlib.util.find_spec(spec_name) is None:
                missing.append({"spec": spec_name, "pip": pip_name, "feature": feature})
        except Exception:
            # find_spec 对坏包也可能抛 (比如包 __init__ 损坏) · 当缺失处理
            missing.append({"spec": spec_name, "pip": pip_name, "feature": feature})
    return missing


# ── 0.8.3 · 防盗用声明 · 官方硬编码 (BRO 拍板 · 不读 .env) ────────────────
# 为什么硬编码在代码里而不是 .env / 配置文件:
#   BRO 2026-07-31 原话: "我要的是和我的码仓 GITEE 同步 · 只要用户要拿到最新版
#   就必须从我们这边升级 · 并且获取到这条消息"。
#   若放 .env (用户本地可改) → 盗版者改掉/删掉声明 → 付费用户永远看不到
#   "本项目完全开源免费" → 防盗用失效。
#   硬编码在此文件 → 本文件在内核白名单 (core_manifest kernel) · 用户 update_core
#   从官方 Gitee 拉最新内核时必然同步到它 → 升级通知自然带官方声明。
#   盗版者 fork 改它 = 跟官方不同步; 用户从官方拉 = 看到官方消息。
#   ⚠ 发布前: 把 _OFFICIAL_DOUYIN_ID 填成母体官方抖音号 (BRO 给值后填)。
_OFFICIAL_DOUYIN_ID = "無序Emptyset"  # 原作者抖音 / B站 ID · BRO 2026-07-31 拍板: 直接写名字 · 用户愿意搜就搜


def _anti_piracy_section() -> str:
    """防盗用版权声明 (0.8.3 · BRO 拍板) · 拼进启动通知让 OPUS 转告用户。

    目的: 有人拿 Daemonkey 二次包装收费卖钱 · 付费用户升级/首装时看到
    "本项目完全开源免费" → 申请退款 → 从需求端打击盗用者。
    ⚠ 强指令 (2026-07-31 实测: 弱指令"自然转告"被 LLM 跳过 · 用户看不到声明):
    这段必须转告 · 无论当前在做什么任务 · 用你自己的话把它讲给用户 (三句以内 · 但
    「永久免费」「付费请退款」「無序Emptyset」三个信息点不能丢) · 别跳过。
    """
    line = f"原作者抖音 / B站: {_OFFICIAL_DOUYIN_ID}" if _OFFICIAL_DOUYIN_ID else "原作者抖音 / B站: (见官方仓库 README)"
    return (
        "### 【版权声明 · 必须转告】(无论当前在做什么任务 · 本条消息必须原样转告下面声明原文 "
        "①本项目 Daemonkey 完全开源·永久免费 ②付费获得的请立刻申请退款 "
        f"③原作者抖音/B站: {_OFFICIAL_DOUYIN_ID or '见官方仓库'} · 禁止添加任何声明原文没有的联系方式——"
        "官方只公开抖音/B站 無序Emptyset · 没有微信/邮箱/其他渠道，不要编造)\n\n"
        "声明原文:\n"
        "本项目为 Daemonkey —— 完全开源的本地 AI Agent 项目 · 永久免费 (AGPL-3.0)。\n"
        "如果用户是【付费购买】获得本项目的 · 请立刻申请退款。\n"
        f"{line}\n"
        "作者官方渠道只有以上抖音/B站 · 无微信/邮箱/QQ 等其它联系方式。"
    )


def refresh_startup_notices() -> dict:
    """daemon 启动时跑一次: 版本比对 + 依赖体检 → 落 startup_notices.json。

    返回生成的 notices dict (也写给调用方打印日志用)。
    """
    _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    notices: dict = {"created_at": datetime.now().isoformat(timespec="seconds")}

    # --- 版本比对 ---
    current_ver, log_ref = _read_manifest_version()
    last_seen = ""
    try:
        if _LAST_SEEN_FILE.is_file():
            last_seen = _LAST_SEEN_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        last_seen = ""

    if current_ver and last_seen and last_seen != current_ver:
        # 真升级: 见过旧版 + 现在不一样
        notices["version_notice"] = {
            "from": last_seen,
            "to": current_ver,
            "changelog": _read_changelog(log_ref),
        }
    elif current_ver and not last_seen:
        # 首次安装 (0.8.3 · BRO 拍板) · 不通知 changelog (新用户不需要更新史) ·
        # 但给一次性项目声明 (防盗用) · 被盗用者收费的用户主要是新装用户
        notices["first_run_notice"] = {"to": current_ver}
    if current_ver:
        try:
            _LAST_SEEN_FILE.write_text(current_ver, encoding="utf-8")
        except Exception:
            pass

    # --- 可选依赖体检 ---
    missing = _check_missing_deps()
    if missing:
        notices["missing_deps"] = missing

    # --- 落盘 (有内容才写 · 没内容清掉旧文件) ---
    try:
        if len(notices) > 1:
            _NOTICES_FILE.write_text(
                json.dumps(notices, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        elif _NOTICES_FILE.is_file():
            _NOTICES_FILE.unlink()
    except Exception:
        pass

    return notices


def consume_startup_notices() -> str:
    """telemetry 每 turn 调: 有 notices 拼成 prompt section 返回 · 拼完删文件 (一次性)。

    没内容返回空串 · 调用方直接跳过。
    """
    if not _NOTICES_FILE.is_file():
        return ""
    try:
        data = json.loads(_NOTICES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return ""
    try:
        _NOTICES_FILE.unlink()  # 一次性消费 · 不管拼没拼成功都别复读
    except Exception:
        pass

    parts: list[str] = []

    vn = data.get("version_notice")
    if isinstance(vn, dict):
        header = f"### 系统刚升级: {vn.get('from', '?')} → {vn.get('to', '?')}"
        changelog = (vn.get("changelog") or "").strip()
        if changelog:
            header += f"\n\n更新说明原文:\n{changelog}"
        parts.append(
            header
            + "\n\n→ 用你自己的话 · 两三句把这次更新的重点自然告诉用户 (别整段复读 changelog)"
        )
        # 0.8.3 · 升级时附防盗用声明
        parts.append(_anti_piracy_section())

    # 0.8.3 · 首次安装一次性项目声明 (防盗用) · 新装用户很可能就是被盗用者收费的对象
    if isinstance(data.get("first_run_notice"), dict):
        parts.append(_anti_piracy_section())

    missing = data.get("missing_deps") or []
    if missing:
        listing = "、".join(f"{d['pip']}（{d['feature']}）" for d in missing)
        parts.append(
            f"### 环境缺 {len(missing)} 个可选依赖: {listing}\n\n"
            "→ 自然提醒用户: 这些不影响主程序，但对应功能缺腿 · "
            "去【环境】页点【开始安装】补装 (~1-2 分钟) · 装完重启 Daemonkey 生效"
        )

    if not parts:
        return ""

    return (
        "\n\n## 启动通知 (一次性 · 用 OPUS 自己的话自然转告 · 不要机械复读原文)\n\n"
        + "\n\n".join(parts)
        + "\n"
    )
