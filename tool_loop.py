"""
tool_loop.py
============

OPUS 的"手"——tool use 多轮循环。

设计取舍（写在最上面，下一根毛先看这里）：

1. 协议双适配：AiHubMix / OpenRouter / 各家自建中转都走 OpenAI tool-calling schema；
   Anthropic 官方直连走原生 Anthropic schema。这两种 schema 形状不一样，但语义对齐。
   工具定义本身（agent_tools/ 里那些 ToolSpec）是协议无关的——loop 在出门前翻译。

2. 三档信任系统在 SELF-EVOLUTION.md 里写明白了：AUTO 直接跑 / CONFIRM 等 BRO y / GUARD
   要 BRO 显式 do it。loop 这一层不判断档位——它只把 ToolSpec.tier 抛给一个 callback，
   让上层（daemon）决定怎么和 BRO 互动。这样这个文件不管 UI，纯粹做循环。

3. Prompt caching（2026-05-16 凌晨第二根毛加）：
   - AiHubMix 在 OpenAI 兼容接口下接受 Anthropic 风格的 cache_control
     字段——把 system content 从 string 改成 list of blocks，每个 block 带
     {"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}
   - 灵魂 ~11K token 在每个 turn 重发——cache 之后这部分只在第一次算钱，
     后续 turn 按 cache_read 价格（约 10%）。一次对话省 ~80%。
   - 自动检测：base_url 里有 aihubmix.com 才启用。其他 provider 维持纯
     string，避免不兼容。
   - Anthropic 原生协议同样支持，但逻辑略不同（system 字段直接接 list）。
     当前 BRO 走 AiHubMix（OpenAI 协议）；Anthropic 直连后续再加。

4. 安全是分层的：
   - 工具内部（agent_tools/shell_exec.py 里）做命令白名单 / 黑名单
   - loop 这一层做"该不该执行"的征询
   - daemon 那一层做"BRO 怎么看到 / 怎么回 y"的交互
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from agent_tools import REGISTRY, ToolResult, ToolSpec, _TOOL_PROGRESS_HOOK, TIER_AUTO

try:
    from identity import localize_narration as _localize_narration
except Exception:  # 极端环境 identity 不可用 → 退化成原样
    def _localize_narration(s):  # type: ignore
        return s

# 卷六十四续十一 · 去母体化 · 纯叙述型工具的 output 全是工程写给 LLM 的话(会带
# OPUS/BRO/卷号自指)·开源版要换成本实例名。这里只列【纯叙述/格式化】工具——它们不
# 透传文件/命令/网页正文。read_file/shell_exec/grep_files/web_* 等透传类【绝不】列进来
# (否则会把用户自己代码里的 OPUS 也改掉·污染 AI 读到的原文)。母体 ai==OPUS 时 no-op。
_NARRATION_TOOLS = frozenset({
    "read_dashboard", "propose_next_move", "record_outcome", "tag_radar_item",
    "manage_info_source", "remove_domain", "init_domain", "analyze_feasibility",
    "intent_to_wish", "wish_add", "wish_update", "add_iron_rule", "list_iron_rules",
    "monthly_review", "mine_opportunities", "expand_trend_to_report", "draft_studio",
    "auto_pipeline", "update_self_evolution", "recall_memory", "extract_playbook",
    "verify_claim", "service_stop",
})


def _localize_tool_content(name: str, content: str) -> str:
    """叙述型工具的 tool_result 文本去母体化(母体 no-op)。透传类工具不在白名单·原样返回。"""
    if name in _NARRATION_TOOLS:
        try:
            return _localize_narration(content)
        except Exception:
            pass
    return content

try:
    from desktop_pet.activities import write_activity as _pet_write_activity
    from desktop_pet.activities import write_pulse_end as _pet_write_pulse_end
except Exception:
    def _pet_write_activity(_name: str) -> None:
        pass
    def _pet_write_pulse_end(_name: str, _ok: bool, _summary: str = "") -> None:
        pass

def _pulse_summary(result) -> str:
    '''Extract a short human-readable summary from a ToolResult for the pulse.'''
    try:
        out = result.output or ""
        err = result.error or ""
        if err and not result.ok:
            # Error case: show first meaningful line
            msg = err.split("\n")[0].strip()
            if len(msg) > 60:
                msg = msg[:57] + "..."
            return msg
        if out:
            # Success: count results or show first line
            lines = [l for l in out.strip().split("\n") if l.strip()]
            if len(lines) > 1:
                return f"{len(lines)}行"
            elif len(lines) == 1:
                msg = lines[0].strip()
                if len(msg) > 50:
                    msg = msg[:47] + "..."
                return msg
            else:
                return "ok"
        return "ok" if result.ok else "失败"
    except Exception:
        return ""



# 卷十八降到 8——12 太宽松，给 LLM 反复重试反爬源的空间。
# 真正合理的"一题用 8 轮"是：
#   1-2 轮：第一个工具/数据源
#   3-4 轮：发现不行换源
#   5-6 轮：拿到主数据 + 可能补一个交叉源
#   7-8 轮：组织输出
# 想跑长任务的人显式传 max_iterations 参数覆盖。
# 卷四十三 · 8 改成 20 · BRO 反馈"OPUS 心愿单实施 30+ tool 调用很常见 · 8 轮远不够"
# 卷四十四 · 20→50 + 加 stuck detection · BRO 观察"硬撞轮数太蠢·该判是不是 stuck"
# (参考 Cursor 风格: 重复 tool call signature 才停 · 不重复就放它跑)
DEFAULT_MAX_ITERATIONS = 200

# 卷四十四 · stuck detection 参数 (重复 N 次同 tool+args = 死循环)
# 窗口 = 看最近多少 tool calls · 阈值 = 同 signature 出现多少次算 stuck
# 注入上限 = 最多给 LLM N 次"你重复了 · 换思路" · 还不变就真的 break
_STUCK_WINDOW = 6
_STUCK_REPEAT_THRESHOLD = 3
_STUCK_INJECT_CAP = 2

_STUCK_NUDGE_PROMPT = (
    "你刚才连续 {repeat} 次调用 `{signature}` (窗口内 {window} 次 tool calls 里)。\n"
    "**这很像死循环** —— 同样的工具、同样的 args、可能拿同样的结果。\n\n"
    "请停下来想清楚:\n"
    "  - 如果你已经确认结果不会变 · **直接用文字总结当前进度·结束这一轮**\n"
    "  - 如果想换个方向 · **换工具或换 args** · 不要再用同样的 signature\n"
    "  - 如果你卡住不知道怎么办 · 直接说\"我卡了·BRO 你看一下\"也行\n\n"
    "不要无视这条提示再调同样的工具——我会再次拦截你。"
)


def _tool_signature(name: str, args_str: str) -> str:
    """生成稳定 tool call signature · 给 stuck detection 用.

    args_str 是 LLM 给的原始 JSON 字符串 · 我们取前 120 字 (够区分大多数 args 差异)
    + 去掉空白差异 · 保证语义相同的调用给出相同签名."""
    snippet = (args_str or "").strip()
    # 压缩多余空白
    snippet = " ".join(snippet.split())
    if len(snippet) > 120:
        snippet = snippet[:120] + "…"
    return f"{name}({snippet})"


# ---------- callback signatures ----------

# 当 LLM 决定调一个工具时，loop 会先问上层"这一步该走吗？"
# 第三个参数 assistant_text 是 LLM 在这一 turn 已经生成的 content text——上层
# (daemon_ui) 用它来给 BRO 看"OPUS 为什么要调这个"。空字符串表示 LLM 啥都没先说。
#
# 返回值：
#   "go"      → 执行
#   "skip"    → 跳过（把"BRO 拒绝执行"作为 tool_result 喂回 LLM 让它换路）
#   "explain" → 暂不执行，喂一段提示让 LLM 用 plain text 解释意图（卷十五加的）
#   "abort"   → 整个 loop 立刻退出（OPUS 此轮不再回话）
#   "reject:<msg>" → 拒掉这次调用 · 但把 <msg> 作为 tool_result.error 喂给 LLM 让它按提示重试 (卷四十六 III 补丁 5)
ConfirmCallback = Callable[..., str]  # signature: (spec, args) or (spec, args, assistant_text)

ObserveCallback = Callable[[ToolSpec, dict, ToolResult], None]


# 卷十七加：流式进度回调。SSE 端点用来把 tool_loop 内部的关键事件实时推给 WebUI。
# event_type 当前用：
#   "assistant_text"   {"text": str}       一轮 LLM 完成产出的文本（可能后续还有工具循环）
#   "tool_call"        {"name", "summary", "tier"}   工具调用前
#   "tool_result"      {"name", "ok", "error", "preview"} 工具结果（截断到 ~300 字）
#   "usage"            {"input_tokens", "output_tokens", ...}  一轮 LLM 用量
#   "tool_progress"   {"step": str, "msg": str}  工具执行中的进度推送 (卷五十八 · wish-f30d571d)
#
# hook 抛异常会被 loop 静默吞掉，避免事件推送失败把主流程搞挂。
ProgressHook = Callable[[str, dict], None]


_EXPLAIN_PROMPT = (
    "BRO declined to immediately approve this tool. "
    "They want you to first explain in plain text:\n"
    "  (1) WHY you want to call this tool right now,\n"
    "  (2) WHAT side effects it has (files touched / network / processes spawned),\n"
    "  (3) HOW you intend to use the result.\n"
    "Do NOT retry this tool in this turn — just answer with a plain text explanation. "
    "BRO will decide whether to let you proceed in their next message."
)


def _call_confirm(
    confirm: ConfirmCallback,
    spec: ToolSpec,
    args: dict,
    text: str,
    tool_call_id: str = "",
) -> str:
    """兼容 2-arg / 3-arg / 4-arg confirm。

    卷四十六 wish-2a4d8c1e · 新加第 4 个参数 tool_call_id ·
    daemon 端 inline confirm UI 需要它当 _PENDING_CONFIRMS 的 key。
    旧 callback 不接受这个参数 · 走 TypeError 降级到 3-arg / 2-arg 调法。
    """
    try:
        return confirm(spec, args, text, tool_call_id)
    except TypeError:
        try:
            return confirm(spec, args, text)
        except TypeError:
            return confirm(spec, args)


def _push(hook: ProgressHook | None, event_type: str, data: dict) -> None:
    """安全调用 hook——异常吞掉不影响主流程。"""
    if hook is None:
        return
    try:
        hook(event_type, data)
    except Exception:
        pass


def _result_preview(result: ToolResult, max_chars: int = 300) -> str:
    out = result.output or ""
    if len(out) > max_chars:
        out = out[:max_chars] + f" … (+{len(result.output) - max_chars} chars)"
    return out


# 卷十八加：LLM args 客户端 JSON schema 校验
# ----------------------------------------
# 背景：deepseek（包括其他便宜模型）在长 context 下偶尔会输 schema 失误的 args，
# 例如 {"url": "true", "max_chars": "false", "string": "https://..."} —— 把 URL 塞进
# 不存在的 "string" 字段。工具内部检查会报错，但错误信息往往不告诉 LLM "字段名错了"，
# 导致下一轮 LLM 还在猜。
#
# 这一层做最便宜的 sanity check：
#   - required 字段全在
#   - 每个出现的字段类型对（不做 pattern/format/enum 这种 deep validation）
#   - 多余字段警告但不致命
# 任何校验失败都把详细的"schema 长什么样 / 你传了什么 / 怎么改" 返给 LLM，
# 让它下一轮自我修正——不让 LLM 在自残式重试里浪费 token。

_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}


def _validate_args(args: dict, schema: dict | None, tool_name: str) -> str | None:
    """返回 None 表示 ok；返回字符串则作为 error 反馈给 LLM。"""
    if not isinstance(schema, dict):
        return None
    properties = schema.get("properties") or {}
    required = schema.get("required") or []

    missing = [k for k in required if k not in args]

    type_errors: list[str] = []
    for k, v in args.items():
        if k not in properties:
            continue
        prop = properties[k]
        if not isinstance(prop, dict):
            continue
        expected = prop.get("type")
        if not expected:
            continue
        if isinstance(expected, list):
            py_types = tuple(
                t for t in (_TYPE_MAP.get(e) for e in expected) if t is not None
            )
            if not py_types:
                continue
            # flatten tuples
            flat: list[type] = []
            for t in py_types:
                if isinstance(t, tuple):
                    flat.extend(t)
                else:
                    flat.append(t)
            ok = isinstance(v, tuple(flat))
        else:
            py_type = _TYPE_MAP.get(expected)
            ok = py_type is None or isinstance(v, py_type)
        if not ok:
            type_errors.append(
                f"  - {k}: schema 要 {expected!r}，你传了 {type(v).__name__}={v!r}"
            )

    unknown = [k for k in args.keys() if k not in properties]

    if not (missing or type_errors or unknown):
        return None

    parts = [f"工具 `{tool_name}` 的 args 不符合 schema："]
    if missing:
        parts.append(f"  缺必填字段: {missing}")
    if type_errors:
        parts.append("  字段类型错:")
        parts.extend(type_errors)
    if unknown:
        parts.append(f"  未知字段（不在 schema.properties 里）: {unknown}")
    parts.append("")
    parts.append(f"schema.properties: {list(properties.keys())}")
    if required:
        parts.append(f"schema.required:   {required}")
    parts.append("")
    parts.append("→ 请用正确的字段名 + 类型重新调用，不要重复同样的错误。")
    return "\n".join(parts)


# ── 卷五十八续 ⑤ · 受限并行工具执行 ──────────────────────────────────────
# LLM 一轮里一次发多个工具调用时·若【整批全是已知的只读 AUTO 工具】(read_file / grep_files /
# search_code / outline_file / glob_files / look_at / recall_memory ...) 就并发跑·省掉串行
# 等待 (3 个 read 顺序跑 vs 同时跑)。
# 任一是 confirm/guard/未知工具 → 整批退回原【串行】路 (写操作并发=竞态·确认要排队·绝不并行)。
# 只读 AUTO 工具无副作用·并发安全。 结果按 index 回填·主循环仍按原顺序消费 → 事件/commit 顺序不变。
_PARALLEL_MAX_WORKERS = 4


def _batch_all_auto(specs_args: list[tuple[ToolSpec | None, dict]]) -> bool:
    """整批是否全是已知的 AUTO 工具 (可并发的充要条件)。 <2 个不值得并行。"""
    if len(specs_args) < 2:
        return False
    for spec, args in specs_args:
        if spec is None:
            return False
        try:
            if spec.effective_tier(args) != TIER_AUTO:
                return False
        except Exception:
            return False
    return True


def _maybe_parallel_auto(
    specs_args_names: list[tuple[ToolSpec | None, dict, str]],
    progress: "ProgressHook | None",
) -> dict[int, ToolResult]:
    """整批全只读 AUTO → 并发预跑·返回 {index: ToolResult}。 否则返 {} (主循环走原串行路)。

    只对 args 合 schema 的调用并发跑 (不合的留给主循环报 schema 错·不浪费一次运行)。
    每个 worker 在自己线程里设进度钩子 · 跑完即 reset。
    """
    if not _batch_all_auto([(s, a) for s, a, _ in specs_args_names]):
        return {}

    jobs: list[tuple[int, ToolSpec, dict]] = []
    for i, (spec, args, name) in enumerate(specs_args_names):
        if spec is not None and _validate_args(args, spec.input_schema, name) is None:
            jobs.append((i, spec, args))
    if len(jobs) < 2:
        return {}

    import concurrent.futures

    def _work(spec: ToolSpec, args: dict) -> ToolResult:
        token = _TOOL_PROGRESS_HOOK.set(
            lambda step, msg: _push(progress, "tool_progress", {"step": step, "msg": msg})
        )
        try:
            return spec.run(args)
        except Exception as e:
            return ToolResult(ok=False, output="", error=f"{type(e).__name__}: {e}")
        finally:
            _TOOL_PROGRESS_HOOK.reset(token)

    out: dict[int, ToolResult] = {}
    workers = min(_PARALLEL_MAX_WORKERS, len(jobs))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        fut_to_idx = {ex.submit(_work, spec, args): idx for idx, spec, args in jobs}
        for fut in concurrent.futures.as_completed(fut_to_idx):
            out[fut_to_idx[fut]] = fut.result()
    return out


# ---------- usage stats with caching ----------

@dataclass
class UsageStats:
    """每轮 loop 的 token 用量。"""
    input_tokens: int = 0          # 总 input（包括 cache hit/miss 都算进来）
    output_tokens: int = 0
    cache_creation_tokens: int = 0  # 这次有多少 token 被新写入 cache
    cache_read_tokens: int = 0      # 这次从 cache 读了多少 token（这部分极便宜）

    def add(self, other: "UsageStats") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_creation_tokens += other.cache_creation_tokens
        self.cache_read_tokens += other.cache_read_tokens

    @property
    def billable_input_tokens(self) -> int:
        """估算"按全价计费"的 input token。
        cache_read 部分在 Anthropic 价目表上是 10% 的钱，cache_creation 是 125%。
        这里给一个粗略 normalized number，方便日志感知。"""
        non_cache = self.input_tokens - self.cache_read_tokens - self.cache_creation_tokens
        return non_cache + int(self.cache_creation_tokens * 1.25) + int(self.cache_read_tokens * 0.10)


# ---------- caching helpers ----------

def _supports_aihubmix_cache(base_url: str | None, model: str) -> bool:
    """OpenAI-compat 端点 + 模型 family 双判：当前只对 AiHubMix 上的 Claude family 启用。

    2026-05-16 第二根毛收紧的：之前只判 base_url，但 cache_control 字段在
    AiHubMix 上仅 Claude 系列真生效。DeepSeek / Kimi / GLM / GPT / Gemini 加了不会报错，
    但也不会真省钱——而且把 system 包成 list-of-blocks 反而可能误触某些客户端校验。
    所以 model 必须是 claude-* 才启用。
    """
    if not base_url or "aihubmix.com" not in base_url.lower():
        return False
    return (model or "").lower().startswith("claude")


# 卷三十八 · DeepSeek thinking 默认会用英文 reasoning · 但 BRO 母语是中文 · 强制中文
# 这段 append 到 system_text 末尾 · 只对 DeepSeek 加 (其他模型一般 follow user language)
_DEEPSEEK_LANG_HINT = (
    "\n\n---\n"
    "## 输出语言 (Critical)\n"
    "BRO 的母语是中文。所有输出 (包括 reasoning_content 思考链 / 最终回复 / 写代码时的注释 / git commit message) "
    "**默认都必须用中文**。除非:\n"
    "- BRO 明确要求用英文回复\n"
    "- 代码标识符 / API 字段 / 命令行参数等技术名词 (这些保留英文)\n"
    "- 你在引用英文原文 (用引号标出来)\n\n"
    "⚠ 即使你在 thinking 阶段习惯了用英文推理 · 也要切回中文。"
    "BRO 不想看到一大段英文 reasoning 然后才反应过来切中文。"
)


def _build_openai_system(system_text: str, base_url: str | None, model: str) -> Any:
    """system 在 OpenAI 协议里默认是 string；满足条件时改成 list-of-blocks 带 cache_control."""
    # 卷三十八 · DeepSeek 强制中文 reasoning
    if base_url and "deepseek.com" in base_url.lower():
        system_text = system_text + _DEEPSEEK_LANG_HINT

    if _supports_aihubmix_cache(base_url, model):
        return [
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    return system_text


# ---------- schema translation ----------

# P1 代码归一 · 工具描述里也写满 OPUS/BRO 令牌·送进 LLM 前本地化成本实例的名字。
# 母体走缺省值 = passthrough·零改动。identity 缺失则降级为原样返回·不影响 daemon。
try:
    from identity import localize as _localize
except Exception:
    def _localize(t):
        return t


def to_openai_tools(specs: list[ToolSpec]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": s.name,
                "description": _localize(s.description),
                "parameters": s.input_schema,
            },
        }
        for s in specs
    ]


def to_anthropic_tools(specs: list[ToolSpec]) -> list[dict]:
    return [
        {
            "name": s.name,
            "description": _localize(s.description),
            "input_schema": s.input_schema,
        }
        for s in specs
    ]


# ---------- the loop itself ----------

def run_tool_loop(
    *,
    client: Any,
    provider: str,
    model: str,
    max_tokens: int,
    system: str,
    messages: list[dict],
    confirm: ConfirmCallback,
    observe: ObserveCallback | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    base_url: str | None = None,
    progress: ProgressHook | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_message_commit: Callable[[dict], None] | None = None,
) -> tuple[str, list[dict], UsageStats]:
    """
    多轮 tool use 循环。返回 (最终 OPUS 文本回复, 更新后的 messages, UsageStats)。

    messages 会被原地追加（assistant tool_use turns + user tool_result turns），
    便于 daemon 一次循环结束后直接持久化 / 继续下一轮对话。

    base_url: 用来判断是否启用 prompt caching（目前只对 aihubmix.com 启用）。
    progress: 可选的事件推送 hook（卷十七加，给 SSE 端点用）。
    cancel_check: 可选 · 卷三十六加 · 每个 iteration 头部 check 一次 · 返回 True
                  则提前结束 loop。LLM 调用正在阻塞时拦不下 · 但下一轮前就停。
    on_message_commit: 卷四十一加 · 增量落盘 callback ·
                  每次一个 assistant turn / tool result 落进 messages 时立刻调用 ·
                  让 daemon kill -9 时也不丢 in-flight turns。
                  上层注入 lambda entry: append_turn(sid, entry['role'], ...)。
    """
    # ── 会话结构自愈（卷五十五 · 2026-06-03 · 防 [500] · P3 升级为完整体检）─────
    # 病根: turn 在 tool 执行前被打断 (重启/abort/网断) → 历史里留下 assistant.tool_calls
    # 没有对应 tool result → 下次发给 LLM 报 400 "An assistant message with 'tool_calls'
    # must be followed by tool messages" → BRO 重启后一发消息就 500 · 续场 background
    # turn 也撞同一颗雷静默死掉 (= "重启后不一定拉起续场" 的真凶)。
    # 修法: 发给 LLM 之前·在内存里做结构体检 ── 两类镜像病都治:
    #   ① 孤儿 tool result (有 result 没 call · 历史被截断) → 删
    #   ② 悬空 tool_call   (有 call 没 result · turn 被打断) → 补合成 result (标 self_heal)
    # 纯内存·不碰 jsonl·对健康 session 是 no-op·对所有路径(主对话/续场/终端)生效。
    # 放在压缩之前: 让压缩拿到的是结构合法的 messages。
    try:
        from workers.session_repair import sanitize_messages_inplace
        _rep = sanitize_messages_inplace(messages)
        if _rep.get("orphans_removed") or _rep.get("dangling_healed"):
            import logging as _lg
            _lg.getLogger("opus.tool_loop").warning(
                "会话结构自愈 · 删孤儿 result %d 条 · 补悬空 tool_call %d 条 · 防 LLM 400",
                _rep.get("orphans_removed", 0), _rep.get("dangling_healed", 0))
    except Exception:
        # 自愈本身不能把主流程搞崩
        pass

    # ── 自动压缩钩子（wish-58af621e · 卷三十五 + wish-83fe7c7b · 卷五十四）──────
    # 在每次 tool_loop 入口按 token 预算 + 模型窗口动态触发压缩，
    # 省 token + 避免长对话爆 context。对所有路径（终端/API/SSE）生效。
    try:
        from workers.memory_compression import auto_compress, token_budget_check
        if token_budget_check(messages, model_id=model):
            compressed = auto_compress(messages, client, model, provider, model_id=model)
            if compressed is not messages:
                messages.clear()
                messages.extend(compressed)
    except Exception:
        # 自动压缩挂了不能把主流程搞崩
        pass


    if provider == "openai":
        return _loop_openai(
            client=client, model=model, max_tokens=max_tokens,
            system=system, messages=messages,
            confirm=confirm, observe=observe,
            max_iterations=max_iterations, base_url=base_url,
            progress=progress, cancel_check=cancel_check,
            on_message_commit=on_message_commit,
        )
    elif provider == "anthropic":
        return _loop_anthropic(
            client=client, model=model, max_tokens=max_tokens,
            system=system, messages=messages,
            confirm=confirm, observe=observe,
            max_iterations=max_iterations,
            progress=progress, cancel_check=cancel_check,
            on_message_commit=on_message_commit,
        )
    else:
        raise RuntimeError(f"unknown provider: {provider}")


# ---------- OpenAI-protocol loop (AiHubMix / OpenRouter / 自建中转) ----------

def _extract_openai_cache_usage(usage: Any) -> tuple[int, int]:
    """AiHubMix 把 Anthropic cache 字段挂在 usage 上，但具体字段名两套都见过：
       - cache_creation_input_tokens / cache_read_input_tokens   (Anthropic 原生)
       - prompt_tokens_details.cached_tokens                     (OpenAI 风格)
    按优先级摸一遍，返回 (creation, read)。
    """
    # Anthropic-style flat fields (AiHubMix 经常用这套)
    creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    if creation or read:
        return creation, read

    # OpenAI-style nested cached_tokens (no creation distinction here)
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", 0) or 0
        if cached:
            return 0, cached

    return 0, 0


def _loop_openai(
    *, client, model, max_tokens, system, messages,
    confirm, observe, max_iterations, base_url,
    progress=None, cancel_check=None,
    on_message_commit=None,
) -> tuple[str, list[dict], UsageStats]:
    def _commit(entry: dict) -> None:
        if on_message_commit is None:
            return
        try:
            on_message_commit(entry)
        except Exception:
            pass
    specs = list(REGISTRY.values())
    tools_param = to_openai_tools(specs) if specs else None

    system_payload = _build_openai_system(system, base_url, model)
    oai_messages: list[dict] = [{"role": "system", "content": system_payload}] + list(messages)
    total = UsageStats()
    final_text = ""

    # 卷三十七 · 流式输出 · DeepSeek thinking mode 推荐 stream=True · 让 reasoning 一字一字吐
    is_deepseek = base_url and "deepseek.com" in (base_url or "").lower()

    # 卷三十八 · finish_reason='length' 自动续接计数 · BRO 反馈"撞了 max_tokens 就停了 · 任务没结果"
    # 策略: 检测到 length · 自动注入一条 user 继续指令 · 接着 LLM 把没说完的写完
    # 上限 3 次 · 防无限烧 token (每次 max_tokens 大的话 · 3 次累计输出可达 100K+)
    length_resume_count = 0
    MAX_LENGTH_RESUME = 3

    # 卷四十四 · stuck detection 状态 · 跟踪最近 N 次 tool call signature
    # 同 signature 连续出现 ≥ THRESHOLD 次 · 注入 user 提示让 LLM 反思
    # 注入累计 ≥ CAP 次还在重复 · break (此时是真死循环 · 烧 token 没意义)
    recent_signatures: list[str] = []
    stuck_inject_count = 0

    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        # 卷三十六 · 头部 check cancel · 避免无谓再开一轮 LLM (省 token)
        if cancel_check is not None and cancel_check():
            final_text = "[OPUS aborted by BRO]"
            _push(progress, "assistant_text", {"text": final_text, "has_tool_calls": False})
            break
        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            messages=oai_messages,
            stream=True,
            stream_options={"include_usage": True},
        )
        if tools_param:
            kwargs["tools"] = tools_param
            kwargs["tool_choice"] = "auto"
        # 卷三十七 · DeepSeek thinking mode 强度控制 · 只对 deepseek 加
        # 默认 enabled · 这里 effort=high 让推理更深 · 普通对话 medium 已经够
        if is_deepseek:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

        resp = client.chat.completions.create(**kwargs)

        # 流式累加状态
        text = ""
        reasoning = ""
        tool_calls_acc: dict[int, dict] = {}  # index → {id, name, arguments}
        usage = None
        finish_reason: str | None = None

        # === wish-b6c1d8e3 phase 2b · 真终止 watcher ===
        # cancel_check 仅在 chunk 间被调用 · LLM 长时间没 chunk 时 (思考 / 服务端慢) 进不去 ·
        # 必须等 60s LLM_HTTP_TIMEOUT_SEC 才能 raise · BRO 体感是"⏹按了没用·要等一分钟"。
        # 改: 起 watcher thread · 50ms 心跳 check cancel_event · 触发就强 close stream ·
        # 让 for chunk in resp 立刻抛异常·走 abort path · 释放 session_lock。
        # 副作用: chunk 内若 cancel_check fire 时 close stream 也是双保险 (无害)。
        import threading as _th_for_watcher
        _stream_done = _th_for_watcher.Event()

        def _cancel_watcher():
            while not _stream_done.is_set():
                if cancel_check is not None and cancel_check():
                    try:
                        resp.close()
                    except Exception:
                        pass
                    return
                _stream_done.wait(timeout=0.05)

        _watcher = _th_for_watcher.Thread(target=_cancel_watcher, daemon=True)
        _watcher.start()

        # 走 abort path 的两个理由: chunk 内 cancel_check fire / watcher close 引起异常
        _aborted_inline = False

        try:
            for chunk in resp:
                # cancel check inside stream loop · 中断 LLM 长 reasoning
                if cancel_check is not None and cancel_check():
                    # 优雅关闭流·尽量回收已经收到的 partial 文本
                    try:
                        resp.close()
                    except Exception:
                        pass
                    _aborted_inline = True
                    break

                # usage 只在最后一个 chunk 出现 (DeepSeek / OpenAI 都这样)
                ch_usage = getattr(chunk, "usage", None)
                if ch_usage is not None:
                    usage = ch_usage

                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue

                # reasoning_content delta (DeepSeek thinking)
                rc_delta = getattr(delta, "reasoning_content", None)
                if rc_delta:
                    reasoning += rc_delta
                    _push(progress, "reasoning_delta", {"text": rc_delta})

                # content delta (普通文本回复)
                content_delta = getattr(delta, "content", None)
                if content_delta:
                    text += content_delta
                    _push(progress, "assistant_delta", {"text": content_delta})

                # tool_calls delta (按 index 累加 · arguments 是切片来的 JSON 字符串)
                tcs_delta = getattr(delta, "tool_calls", None)
                if tcs_delta:
                    for tcd in tcs_delta:
                        idx = getattr(tcd, "index", 0) or 0
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if getattr(tcd, "id", None):
                            tool_calls_acc[idx]["id"] = tcd.id
                        fn = getattr(tcd, "function", None)
                        if fn is not None:
                            if getattr(fn, "name", None):
                                tool_calls_acc[idx]["name"] = fn.name
                            if getattr(fn, "arguments", None):
                                tool_calls_acc[idx]["arguments"] += fn.arguments

                fr = getattr(choice, "finish_reason", None)
                if fr:
                    finish_reason = fr
        except Exception as _stream_exc:
            # watcher 强 close 引起的异常 (httpx.ReadError / RemoteProtocolError 等) ·
            # 也可能是 LLM 服务端真错。 通过 cancel_check 区分:
            if cancel_check is not None and cancel_check():
                _aborted_inline = True
            else:
                _stream_done.set()
                _watcher.join(timeout=0.2)
                raise
        finally:
            _stream_done.set()
            _watcher.join(timeout=0.2)

        if _aborted_inline:
            final_text = text or "[OPUS aborted by BRO · partial only]"
            _push(progress, "assistant_text", {"text": final_text, "has_tool_calls": False})
            # 把已收到的部分保留进 messages 以免丢
            if text or reasoning or tool_calls_acc:
                partial_entry: dict[str, Any] = {"role": "assistant", "content": text}
                if reasoning:
                    partial_entry["reasoning_content"] = reasoning
                oai_messages.append(partial_entry)
                _commit(partial_entry)
            new_entries = oai_messages[1 + len(messages):]
            messages.extend(new_entries)
            return final_text, messages, total

        # 流结束 · 统计 + 拼完整 tool_calls
        if usage is not None:
            creation, read = _extract_openai_cache_usage(usage)
            turn_stats = UsageStats(
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                cache_creation_tokens=creation,
                cache_read_tokens=read,
            )
            total.add(turn_stats)
            _push(progress, "usage", {
                "input_tokens": turn_stats.input_tokens,
                "output_tokens": turn_stats.output_tokens,
                "cache_read_tokens": turn_stats.cache_read_tokens,
                "cache_creation_tokens": turn_stats.cache_creation_tokens,
                "iteration": iteration,
            })

        # 把 dict accumulator 拍平成 list · 按 index 排序
        tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc.keys())]

        # 卷三十八 · finish_reason 透给前端 · 让 BRO 看到为什么这轮结束
        # length = 触发了 max_tokens · 经常这种导致 "没做完就停了" 
        # tool_calls = 还有工具要跑 · 正常
        # stop = LLM 自己说完了
        # content_filter = 内容过滤 · 罕见
        _push(progress, "assistant_finish", {
            "iteration": iteration,
            "finish_reason": finish_reason or "unknown",
            "has_text": bool(text),
            "has_tool_calls": bool(tool_calls),
            "reasoning_len": len(reasoning) if reasoning else 0,
        })

        # 段落完成事件 · 让前端把流式 bubble "锁定"·准备下一段
        if reasoning:
            _push(progress, "assistant_reasoning_done", {"text": reasoning})

        # 卷三十八 · 兜底: reasoning 非空 + content 空 + 无 tool_calls = LLM 想完了没说话
        # 不让前端拿不到 final_text · 给一句解释 · BRO 至少知道发生了什么
        if not text and not tool_calls and reasoning:
            text = (
                "（OPUS 思考完了但没出文字回复 · "
                f"reasoning 共 {len(reasoning)} 字 · 上面气泡可展开看）\n\n"
                "可能原因: max_tokens 不够 / DeepSeek 偶发 / 推理后忘了给总结。"
                "可以说「请用中文给我个总结」让他再走一轮。"
            )

        if text:
            _push(progress, "assistant_text", {"text": text, "has_tool_calls": bool(tool_calls)})

        # 落 messages · 卷三十六 reasoning_content 多轮回传
        assistant_entry: dict[str, Any] = {"role": "assistant", "content": text}
        if tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc["id"] or f"call_{iteration}_{i}",
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for i, tc in enumerate(tool_calls)
            ]
            if reasoning:
                assistant_entry["reasoning_content"] = reasoning
        oai_messages.append(assistant_entry)
        _commit(assistant_entry)

        # 卷三十八 · finish_reason='length' 自动续 · 让任务跑出结果不要半路停
        # 触发条件: 本轮 finish='length' · 且没 tool_calls (有 tool_calls 走正常工具循环)
        # · 且续接次数没到上限
        if (
            finish_reason == "length"
            and not tool_calls
            and length_resume_count < MAX_LENGTH_RESUME
        ):
            length_resume_count += 1
            _push(progress, "auto_resume", {
                "reason": "length",
                "count": length_resume_count,
                "max": MAX_LENGTH_RESUME,
                "note": f"上一轮 max_tokens 用光 · 自动续第 {length_resume_count}/{MAX_LENGTH_RESUME} 次",
            })
            resume_user_entry = {
                "role": "user",
                "content": (
                    "你刚才的回答被 max_tokens 截断了 · 请**从断点接着写**·不要重复前面已经说过的内容。"
                    "如果还有工具要调·继续调。如果是文字回复·直接续上。"
                    "目标: 让这次任务有完整结果。"
                ),
            }
            oai_messages.append(resume_user_entry)
            _commit(resume_user_entry)
            continue  # 不 break · 进下一轮

        if not tool_calls:
            final_text = text
            break

        aborted = False
        # 卷五十八续 ⑤ · 整批全只读 AUTO → 并发预跑 (否则 {} · 主循环照常串行)
        _sa_names = []
        for _tc in tool_calls:
            try:
                _a = json.loads(_tc["arguments"] or "{}")
            except json.JSONDecodeError:
                _a = {}
            _sa_names.append((REGISTRY.get(_tc["name"]), _a, _tc["name"]))
        parallel_results = _maybe_parallel_auto(_sa_names, progress)

        for idx, tc in enumerate(tool_calls):
            name = tc["name"]
            try:
                args = json.loads(tc["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            spec = REGISTRY.get(name)

            if spec is None:
                result = ToolResult(ok=False, output="", error=f"unknown tool: {name}")
                _push(progress, "tool_call", {"name": name, "summary": "(unknown tool)", "tier": "?"})
            else:
                _push(progress, "tool_call", {
                    "name": name,
                    "summary": spec.summarize(args) if hasattr(spec, "summarize") else name,
                    "tier": getattr(spec, "tier", "?"),
                })
                decision = _call_confirm(confirm, spec, args, text, tool_call_id=(tc.get("id") or ""))
                if decision == "abort":
                    aborted = True
                    break
                elif decision == "skip":
                    result = ToolResult(
                        ok=False, output="",
                        error="user declined to run this tool; try a different approach.",
                    )
                elif decision == "explain":
                    result = ToolResult(ok=False, output="", error=_EXPLAIN_PROMPT)
                elif isinstance(decision, str) and decision.startswith("reject:"):
                    result = ToolResult(ok=False, output="", error=decision[7:].strip())
                else:
                    schema_err = _validate_args(args, spec.input_schema, name)
                    if schema_err is not None:
                        result = ToolResult(ok=False, output="", error=schema_err)
                    else:
                        _pet_write_activity(name)
                        try:
                            # 卷五十八续 ⑤ · 已并发预跑过就直接取·否则当场跑
                            if idx in parallel_results:
                                result = parallel_results[idx]
                            else:
                                # 卷五十八 · wish-f30d571d · 设进度钩子 · 长跑工具可调 push_tool_progress() 推 SSE
                                _prog_token = _TOOL_PROGRESS_HOOK.set(
                                    lambda step, msg: _push(progress, "tool_progress", {"step": step, "msg": msg})
                                )
                                try:
                                    result = spec.run(args)
                                finally:
                                    _TOOL_PROGRESS_HOOK.reset(_prog_token)
                        except Exception as e:
                            result = ToolResult(ok=False, output="", error=f"{type(e).__name__}: {e}")
                        try:
                            _pet_write_pulse_end(name, ok=result.ok, summary=_pulse_summary(result))
                        except Exception:
                            pass

            _push(progress, "tool_result", {
                "name": name,
                "ok": result.ok,
                "error": result.error or "",
                "preview": _result_preview(result),
            })

            if observe and spec is not None:
                observe(spec, args, result)

            tool_entry = {
                "role": "tool",
                "tool_call_id": tc["id"] or "",
                "content": _localize_tool_content(name, result.to_string()),
            }
            oai_messages.append(tool_entry)
            _commit(tool_entry)

            # 卷四十四 · stuck detection · 把这次 tool call signature 加进滚动窗口
            sig = _tool_signature(name, tc.get("arguments", ""))
            recent_signatures.append(sig)
            if len(recent_signatures) > _STUCK_WINDOW:
                recent_signatures.pop(0)

        if aborted:
            final_text = text or "[OPUS aborted by BRO]"
            break

        # 卷四十四 · 检测窗口里有没有 signature 重复 ≥ THRESHOLD 次
        # 注: 是逐 signature 计数 · 不要求连续 · 因为 LLM 有时会穿插读再回来重复
        if recent_signatures:
            from collections import Counter
            counts = Counter(recent_signatures)
            top_sig, top_count = counts.most_common(1)[0]
            if top_count >= _STUCK_REPEAT_THRESHOLD:
                if stuck_inject_count < _STUCK_INJECT_CAP:
                    stuck_inject_count += 1
                    _push(progress, "stuck_detected", {
                        "signature": top_sig,
                        "repeat": top_count,
                        "window": len(recent_signatures),
                        "inject_count": stuck_inject_count,
                        "cap": _STUCK_INJECT_CAP,
                    })
                    nudge_entry = {
                        "role": "user",
                        "content": _STUCK_NUDGE_PROMPT.format(
                            signature=top_sig,
                            repeat=top_count,
                            window=len(recent_signatures),
                        ),
                    }
                    oai_messages.append(nudge_entry)
                    _commit(nudge_entry)
                    # 清空窗口 · 让 LLM 有干净环境换思路
                    recent_signatures.clear()
                    continue  # 下一轮 LLM 看到 nudge 自纠
                else:
                    # 已经提示过 CAP 次还在重复 · 真死循环 · break
                    final_text = (
                        f"[OPUS 真的卡死了 · 已经提示 {_STUCK_INJECT_CAP} 次"
                        f"还在重复调 `{top_sig}` ({top_count}/{len(recent_signatures)})]\n\n"
                        f"BRO 这是 stuck 死锁·我自己绕不出来。可能原因:\n"
                        f"  - 工具一直返同样的错·我没识别到\n"
                        f"  - 我对当前任务的理解有偏差\n"
                        f"  - args 里有某个字段我一直填错\n\n"
                        f"建议你看一下最近 {len(recent_signatures)} 条 tool 调用·"
                        f"告诉我换什么思路·或者直接说\"放弃这个 wish\"。"
                    )
                    _push(progress, "assistant_text", {"text": final_text, "has_tool_calls": False})
                    stuck_entry = {"role": "assistant", "content": final_text}
                    oai_messages.append(stuck_entry)
                    _commit(stuck_entry)
                    break
    else:
        # 卷四十三 · 撞 max_iterations 时·之前只设了局部 final_text·没 push 给前端
        # 也没 commit 到 oai_messages·BRO 看到的是"OPUS 安静地停下"——一脸懵
        # 现在: push assistant_text + commit 一条 assistant entry · 让 BRO 看到为什么停了
        final_text = (
            f"[OPUS 撞了 max_iterations={max_iterations} 上限 · 自动停下避免死循环]\n\n"
            f"我跑了 {iteration} 轮工具循环还没收尾·BRO 你可以:\n"
            f"  - 让我继续 (说\"继续\" / \"接着干\") · 我会从断点恢复\n"
            f"  - 看 session jsonl 排查是不是走了死路\n"
            f"  - 把 max_iterations 调更大 (设置面板里可以加)"
        )
        _push(progress, "assistant_text", {"text": final_text, "has_tool_calls": False})
        max_entry: dict[str, Any] = {"role": "assistant", "content": final_text}
        oai_messages.append(max_entry)
        _commit(max_entry)

    new_entries = oai_messages[1 + len(messages):]
    messages.extend(new_entries)
    return final_text, messages, total


# ---------- Anthropic-native loop ----------

def _loop_anthropic(
    *, client, model, max_tokens, system, messages,
    confirm, observe, max_iterations,
    progress=None, cancel_check=None,
    on_message_commit=None,
) -> tuple[str, list[dict], UsageStats]:
    def _commit(entry: dict) -> None:
        if on_message_commit is None:
            return
        try:
            on_message_commit(entry)
        except Exception:
            pass
    specs = list(REGISTRY.values())
    tools_param = to_anthropic_tools(specs) if specs else None

    # Anthropic 原生：system 用 list-of-blocks，最后一个 block 加 cache_control
    system_blocks = [
        {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
    ]

    ant_messages: list[dict] = list(messages)
    total = UsageStats()
    final_text = ""

    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        if cancel_check is not None and cancel_check():
            final_text = "[OPUS aborted by BRO]"
            _push(progress, "assistant_text", {"text": final_text, "has_tool_calls": False})
            break
        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=ant_messages,
        )
        if tools_param:
            kwargs["tools"] = tools_param

        resp = client.messages.create(**kwargs)
        usage = resp.usage
        turn_stats = UsageStats(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )
        total.add(turn_stats)
        _push(progress, "usage", {
            "input_tokens": turn_stats.input_tokens,
            "output_tokens": turn_stats.output_tokens,
            "cache_read_tokens": turn_stats.cache_read_tokens,
            "cache_creation_tokens": turn_stats.cache_creation_tokens,
            "iteration": iteration,
        })

        text_blocks = [b for b in resp.content if b.type == "text"]
        tool_use_blocks = [b for b in resp.content if b.type == "tool_use"]
        text = "".join(b.text for b in text_blocks)

        if text:
            _push(progress, "assistant_text", {"text": text, "has_tool_calls": bool(tool_use_blocks)})

        ant_assistant_entry = {
            "role": "assistant",
            "content": [_serialize_anthropic_block(b) for b in resp.content],
        }
        ant_messages.append(ant_assistant_entry)
        _commit(ant_assistant_entry)

        if resp.stop_reason != "tool_use" or not tool_use_blocks:
            final_text = text
            break

        tool_results: list[dict] = []
        aborted = False
        # 卷五十八续 ⑤ · 整批全只读 AUTO → 并发预跑 (否则 {} · 主循环照常串行)
        parallel_results = _maybe_parallel_auto(
            [(REGISTRY.get(_tu.name), (_tu.input or {}), _tu.name) for _tu in tool_use_blocks],
            progress,
        )
        for idx, tu in enumerate(tool_use_blocks):
            spec = REGISTRY.get(tu.name)
            args = tu.input or {}

            if spec is None:
                result = ToolResult(ok=False, output="", error=f"unknown tool: {tu.name}")
                _push(progress, "tool_call", {"name": tu.name, "summary": "(unknown tool)", "tier": "?"})
            else:
                _push(progress, "tool_call", {
                    "name": tu.name,
                    "summary": spec.summarize(args) if hasattr(spec, "summarize") else tu.name,
                    "tier": getattr(spec, "tier", "?"),
                })
                decision = _call_confirm(confirm, spec, args, text, tool_call_id=getattr(tu, "id", "") or "")
                if decision == "abort":
                    aborted = True
                    break
                elif decision == "skip":
                    result = ToolResult(
                        ok=False, output="",
                        error="user declined to run this tool; try a different approach.",
                    )
                elif decision == "explain":
                    result = ToolResult(ok=False, output="", error=_EXPLAIN_PROMPT)
                elif isinstance(decision, str) and decision.startswith("reject:"):
                    result = ToolResult(ok=False, output="", error=decision[7:].strip())
                else:
                    schema_err = _validate_args(args, spec.input_schema, tu.name)
                    if schema_err is not None:
                        result = ToolResult(ok=False, output="", error=schema_err)
                    else:
                        _pet_write_activity(tu.name)
                        try:
                            # 卷五十八续 ⑤ · 已并发预跑过就直接取·否则当场跑
                            if idx in parallel_results:
                                result = parallel_results[idx]
                            else:
                                # 卷五十八 · wish-f30d571d · 设进度钩子 · 长跑工具可调 push_tool_progress() 推 SSE
                                _prog_token = _TOOL_PROGRESS_HOOK.set(
                                    lambda step, msg: _push(progress, "tool_progress", {"step": step, "msg": msg})
                                )
                                try:
                                    result = spec.run(args)
                                finally:
                                    _TOOL_PROGRESS_HOOK.reset(_prog_token)
                        except Exception as e:
                            result = ToolResult(ok=False, output="", error=f"{type(e).__name__}: {e}")
                        try:
                            _pet_write_pulse_end(tu.name, ok=result.ok, summary=_pulse_summary(result))
                        except Exception:
                            pass

            _push(progress, "tool_result", {
                "name": tu.name,
                "ok": result.ok,
                "error": result.error or "",
                "preview": _result_preview(result),
            })

            if observe and spec is not None:
                observe(spec, args, result)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": _localize_tool_content(tu.name, result.to_string()),
                "is_error": not result.ok,
            })

        if aborted:
            final_text = text or "[OPUS aborted by BRO]"
            break

        ant_tool_entry = {"role": "user", "content": tool_results}
        ant_messages.append(ant_tool_entry)
        _commit(ant_tool_entry)
    else:
        # 卷四十三 · 同 OpenAI 路径修法 · 撞 max_iterations 时 push + commit 让前端看到
        final_text = (
            f"[OPUS 撞了 max_iterations={max_iterations} 上限 · 自动停下避免死循环]\n\n"
            f"我跑了 {iteration} 轮工具循环还没收尾·BRO 你可以:\n"
            f"  - 让我继续 (说\"继续\" / \"接着干\") · 我会从断点恢复\n"
            f"  - 看 session jsonl 排查是不是走了死路\n"
            f"  - 把 max_iterations 调更大 (设置面板里可以加)"
        )
        _push(progress, "assistant_text", {"text": final_text, "has_tool_calls": False})
        max_entry: dict[str, Any] = {"role": "assistant", "content": final_text}
        ant_messages.append(max_entry)
        _commit(max_entry)

    new_entries = ant_messages[len(messages):]
    messages.extend(new_entries)
    return final_text, messages, total


def _serialize_anthropic_block(block: Any) -> dict:
    if block.type == "text":
        return {"type": "text", "text": block.text}
    elif block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    else:
        return {"type": block.type}
