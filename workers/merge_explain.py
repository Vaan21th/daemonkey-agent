"""
workers/merge_explain.py · 合并 LLM 兜底审计闸 (wish-bb743b6c)

两闸模型（2026-08-15 设计定稿）：
  闸1 = verify（机器规则闸）：建 app + 140 路由 smoke + 前端 JS 语法。
        失败 → 直接拦（原始机器报告）。 过 → 进闸2。
  闸2 = LLM 兜底审计（本模块）：审 diff，判定"这分支合进来会不会导致
        daemon 无法启动 / 正常使用链路出错"。 会 → 拦 + 人话日志（为什么不合并）；
        不会 → 放行。 两闸都过才 merge。

LLM 是拦截层不是解读层：verdict=blocked 会真的拦住合并，且日志通过 merge
返回 note 回到发起合并的会话（safe_merge 显示 / wish_update error / collect_to_master note）。

设计约束：
- 只判一件事：会不会导致【无法启动】或【正常使用链路出错】。 不是 code review ·
  不评风格 · 不做"潜在 bug"泛化预警。
- 核心链路显式定义（CORE_CHAIN_HINTS）· 未命中核心链路 → 直接放行（省成本）。
- fail-open：LLM 不可用 / 超时 / 解析失败 → 放行 + 提示（verify 已确认能跑 ·
  闸的基建故障不卡死正当上线）。 逃生门 allow_override=True 保留。
- 成本可控：未命中核心链路不调 LLM · 命中才调 · 输出限 800 tokens。
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# 核心链路文件前缀/片段 · 命中才触发 LLM 审计。
# 与 daemon_rules 场景索引的域同源：启动装载 / tool_loop / 消息通道 / 记忆 / UI / 定时。
CORE_CHAIN_HINTS = [
    # 启动装载
    "daemon_api.py", "soul_loader.py", "daemon_session.py", "tool_loop.py",
    "main.py", "daemon_entry", "/start.py",
    # 工具注册/执行层
    "agent_tools/", "tool_registry",
    # worker 层（消息通道 / 记忆 / 状态机 / 调度）
    "workers/feishu_", "workers/wechat", "workers/memory_", "workers/wishlist.py",
    "workers/git_ops.py", "workers/task_scheduler.py", "workers/closure_check.py",
    "workers/model_io.py", "workers/provider_configs.py", "workers/env_utils.py",
    # 目录级兜底：workers/ 与 api_routes/ 下任何新模块都算核心链路
    "workers/", "api_routes/",
    # 前端 UI
    "static/",
]

# 明确非核心的前缀 · 命中任一（且未命中核心清单）→ 直接放行不调 LLM
NON_CORE_PREFIXES = ("docs/", "data/", "soul/", "sessions/", ".cursor/", ".mcp/")

_SYSTEM_PROMPT = """你是 daemon 代码合并安全审计员，处在第二道兜底闸。

背景：一个 wish 分支要 merge 回 master。第一道闸（verify：建 app + 140 路由
smoke + 前端 JS 语法）已经通过——代码能跑起来。现在轮到你：在合进主干前，
判断这个分支的改动【会不会导致 daemon 无法启动，或正常使用的链路出错】。

判定纪律（必须严格遵守）：
1. 只判一件事：会不会导致【无法启动】或【正常使用链路出错】。不是 code review，
   不评代码风格，不做"潜在 bug"泛化预警。 verify 已经确认代码能跑，
   你的价值是抓 verify 抓不到的【语义级破坏】——比如：改了核心函数的返回值
   结构但调用方还在按老格式解析、改了 provider 配置的字段名导致启动读不到、
   改了消息通道的初始化顺序导致链路断。没有这类明确风险 → 放行。
2. 核心链路清单（命中才深判）：启动装载（daemon_api / soul_loader /
   daemon_session / tool_loop / main 入口）、工具层（agent_tools/）、消息通道
   （feishu / wechat）、记忆系统（memory）、状态机
   （wishlist / git_ops / closure_check）、调度（task_scheduler）、模型配置
   （provider_configs / model_io）、前端 UI（static/）。改动不碰这些 → 直接 ok。
3. 输出严格 JSON（不要多余文字）：
{
  "verdict": "blocked" | "ok",
  "reason": "判定理由（人话 · 50-200字 · 说清影响哪条链路 / 为什么安全）",
  "affected_links": ["启动链路", "消息通道"],
  "suggestion": "怎么修（verdict=blocked 时必填 · 一句话）"
}
verdict=blocked 只在"会导致无法启动或核心链路出错"时给；其余一律 ok。
拿不准时倾向 ok（不要误伤正常合并）——你是兜底闸，不是吹毛求疵的审查员。"""


def _run_git(cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    """跑 git · 返回 (returncode, stdout)。"""
    try:
        kw = dict(cwd=str(ROOT), capture_output=True, text=True,
                  encoding="utf-8", errors="replace", timeout=timeout)
        try:
            from agent_tools._subprocess_helper import no_window_kwargs
            kw.update(no_window_kwargs())
        except Exception:
            pass
        r = subprocess.run(["git"] + cmd, **kw)
        return r.returncode, (r.stdout or "")
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


def _diff_stat(branch: str) -> str:
    """master...branch 的文件清单（--stat · 控 token · 不拉全文 diff）。"""
    rc, out = _run_git(["diff", "--stat", f"master...{branch}"], timeout=15)
    if rc != 0:
        return "(git diff --stat 失败)"
    return out.strip() or "(无差异)"


def _diff_detail(branch: str, files: list[str], max_chars: int = 4000) -> str:
    """master...branch 的 diff 详情（限量 · 只拉命中核心链路的文件）。

    为什么只拉命中文件：全量 diff 按文件名排序，核心链路文件可能排在
    4000 字符截断之外 → LLM 看不到核心改动 = 白审。 精确拉命中文件，
    保证 LLM 的判断依据完整。
    """
    if not files:
        return "(无命中文件)"
    rc, out = _run_git(
        ["diff", f"master...{branch}", "--"] + files, timeout=20)
    if rc != 0:
        return "(git diff 失败)"
    return out.strip()[:max_chars] or "(无差异)"


def _norm_path(path_part: str) -> str:
    """规范化 stat 行里的路径：剥 `{old => new}` 重命名，取最终路径。

    注意保留目录前缀：`workers/{old => new}_file.py` 的 stat 行 split(' => ')
    后新路径只剩 `new_file.py`（丢目录）→ 回退用旧路径 `workers/old`，
    否则核心目录的重命名文件会漏审（不调 LLM）。
    """
    p = path_part.strip()
    if " => " in p:
        pre, post = p.split(" => ", 1)
        new_p = post.strip().replace("{", "").replace("}", "").strip()
        old_p = pre.strip().replace("{", "").replace("}", "").strip()
        return new_p if "/" in new_p else old_p
    return p.replace("{", "").replace("}", "").strip()


def _hit_core_chain(stat_text: str) -> list[str]:
    """从 --stat 文本里找命中的核心链路文件。"""
    hits: list[str] = []
    for line in stat_text.splitlines():
        path_part = _norm_path(line.strip().split("|")[0].strip())
        low = path_part.lower()
        # 非核心前缀（且未命中核心清单）→ 跳过
        if any(path_part.startswith(p) for p in NON_CORE_PREFIXES):
            continue
        for hint in CORE_CHAIN_HINTS:
            if hint.startswith("/"):
                # 路径段精确匹配（如 /start.py）· 防 test_start.py 误命中
                if low == hint[1:] or low.endswith(hint):
                    hits.append(path_part)
                    break
            elif hint.lower() in low:
                hits.append(path_part)
                break
    return hits


def _pick_cfg(cfgs: list) -> Optional[dict]:
    """选 LLM 通道：优先非推理模型（deepseek-chat/glm 类）。

    推理模型（deepseek-v4-pro/kimi-k3/r1 等）max_tokens 被 thinking 吃掉 →
    最终输出易空/截断 → JSON 解析失败 → 闸 fail-open 变摆设。
    非推理模型便宜 + 输出稳 · 更适合做审计闸。
    """
    REASONING_HINTS = ("pro", "reason", "think", "r1", "o1", "k3", "kimi")
    for c in cfgs:
        if c.get("api_key") and c.get("base_url"):
            m = (c.get("model") or "").lower()
            if not any(h in m for h in REASONING_HINTS):
                return c
    for c in cfgs:  # 没有非推理 → 用第一个可用（fail-open 兜底）
        if c.get("api_key") and c.get("base_url"):
            return c
    return None


def _llm_analyze(diff_stat_text: str, diff_detail_text: str) -> Optional[dict]:
    """调 LLM 审计 · 失败返 None（调用方 fail-open）。

    通道发现（通用）：读取本地 provider_configs.json · 优先 OpenAI 兼容通道
    （chat.completions API）· 实际使用的 provider/model 由本地配置决定，
    不在代码里写死。 未配置 → fallback daemon 运行时 client（若同为
    OpenAI 兼容）。 均不可用 → fail-open。
    """
    try:
        from openai import OpenAI
        client = model = None
        try:
            d = json.load(open(DATA_DIR / "provider_configs.json", encoding="utf-8"))
            cfg = _pick_cfg(d.get("configs", []))
            if cfg:
                client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"], timeout=15)
                model = cfg.get("model") or "default"
        except Exception:
            pass
        if client is None or model is None:
            # fallback：daemon 运行时 client —— 只接受 OpenAI 兼容通道（chat.completions）
            try:
                from daemon_runtime import RUNTIME
                if (getattr(RUNTIME, "client", None) is not None
                        and hasattr(RUNTIME.client, "chat")
                        and hasattr(RUNTIME.client.chat, "completions")
                        and getattr(RUNTIME, "model", None)):
                    client, model = RUNTIME.client, RUNTIME.model
            except Exception:
                pass
        if client is None or model is None:
            logger.warning("merge_explain: 无可用 LLM 通道（或兜底通道不兼容）· 放行（verify 已过）")
            return None

        user = (
            "【该分支改动的文件清单】\n"
            f"{diff_stat_text}\n\n"
            "【该分支改动详情（限量）】\n"
            f"{diff_detail_text}"
        )
        resp = client.chat.completions.create(
            model=model,
            max_tokens=2000,
            temperature=0.1,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            timeout=15,
        )
        content = (resp.choices[0].message.content or "").strip()
        # 剥代码块（只剥首尾标签 · 防 reason 内含反引号被截断）
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.S).strip()
        start, end = content.find("{"), content.rfind("}")
        if start >= 0 and end > start:
            content = content[start:end + 1]
        data = json.loads(content)
        if not isinstance(data, dict):
            return None
        links = data.get("affected_links") or []
        if isinstance(links, str):
            links = [links]
        links = [str(x) for x in links if isinstance(x, str) and x.strip()][:6]
        return {
            "verdict": "blocked" if data.get("verdict") == "blocked" else "ok",
            "reason": str(data.get("reason") or "").strip(),
            "affected_links": links,
            "suggestion": str(data.get("suggestion") or "").strip(),
        }
    except Exception as e:
        logger.warning("merge_explain: LLM 审计失败: %s", e)
        return None


def audit_merge(branch: str) -> dict:
    """闸2 入口 · verify 通过后调用。 返回统一 dict：

    {ok: bool, blocked: bool, note: str}
      ok=True      · 放行（未命中核心链路 / LLM 判 ok / LLM 不可用 fail-open）
      blocked=True · LLM 判会影响启动/核心链路 → 拦
      note         · 给调用方拼进 merge 返回 / error 的人话日志
    """
    stat_text = _diff_stat(branch)
    if stat_text == "(git diff --stat 失败)":
        return {"ok": True, "blocked": False,
                "note": "⚠️ LLM 审计未执行（git diff --stat 失败）· verify 已过 · 放行"}
    hits = _hit_core_chain(stat_text)
    if not hits:
        return {"ok": True, "blocked": False,
                "note": "LLM 审计：改动未命中核心链路清单 · 放行"}
    detail = _diff_detail(branch, hits)
    try:
        au = _llm_analyze(stat_text, detail)
    except Exception:
        au = None
    if au is None:
        # fail-open：LLM 不可用/失败 → 放行（verify 已确认能跑 · 不因闸故障卡死上线）
        return {"ok": True, "blocked": False,
                "note": "⚠️ LLM 兜底审计未执行（通道不可用）· verify 已过 · 放行"}
    if au["verdict"] == "blocked":
        reason = au.get("reason") or "LLM 判定会影响启动/核心链路"
        links = "、".join(au.get("affected_links") or []) or "未知链路"
        sug = f"\n  建议: {au['suggestion']}" if au.get("suggestion") else ""
        return {
            "ok": False, "blocked": True,
            "note": ("🛑 LLM 合并审计拦截 · 该分支可能影响核心链路"
                     f"（{links}）· 不建议合入 master\n"
                     f"  判定: {reason}{sug}\n"
                     "  （LLM 兜底判断 · 人工确知可强合: allow_override=True）"),
        }
    return {"ok": True, "blocked": False,
            "note": "LLM 审计通过 · 判定不影响启动/核心链路 · 放行"}
