"""
daemon_runtime.py
=================

Daemon 进程级单例。

为什么需要它——
  set_model 这种工具要在调用结束后**改变 daemon 的运行状态**（model 字段），
  下一轮对话 daemon 才能用新值。但 ToolSpec.run(args) 的签名是纯函数（只接受 args），
  没有"daemon context"参数。

折中：把可变的运行时状态放进一个进程级单例。
  - daemon 启动时 set RUNTIME.model / RUNTIME.base_url / RUNTIME.persist_callback
  - 主循环每轮发请求前从 RUNTIME 读最新 model
  - set_model 工具直接改 RUNTIME

不优雅，但比"给所有工具加 context 参数"动作小且直达目的。
未来如果要做多 daemon 实例共存，再做依赖注入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class DaemonRuntime:
    model: str = ""
    base_url: Optional[str] = None
    persist_callback: Optional[Callable[[str], None]] = None
    """把 model 写到 .env 的回调。daemon 启动时注入；set_model(persist=True) 时调用。"""

    client: Any = None
    """LLM client (openai.OpenAI / anthropic.Anthropic 实例)——summarize_session 等工具需要直接调 LLM。"""

    provider: str = ""
    """'openai' | 'anthropic'——决定怎么调 client。"""

    messages: list[dict] = field(default_factory=list)
    """当前会话 messages 的引用。summarize_session 工具会原地修改它。"""

    session_id: str = ""
    """当前 session id (chat handler 入口处 set)·让工具能拿到当前 session
    用于 request_restart 续场注入定位 session。 卷四十六 III · wish-ed5553d5 hookup."""

    system_prompt: str = ""
    """当前 system prompt（拼装好的）。summarize_session 调 LLM 时可能用到（一般传空让总结独立）。"""

    started_at: float = 0.0
    """daemon 进程启动时刻 (time.time())。wish-1d286099 · dynamic_telemetry 用。"""

    vision_override: Optional[bool] = None
    """视觉能力全局覆盖 (None=自动 · True=多模态 · False=纯文本)。
    wish-4a6331b2 引入 · 2026-06-03 曾在重构中丢失字段定义 (靠动态属性+except 硬撑) ·
    wish-00ed11c2 补回正式字段。 启动 / 激活 provider 配置时从 active config.vision 同步。
    注意: 这是"当前激活配置"的全局快照 · 按模型精确判断走 model_aliases.supports_vision L1。"""

    pending_images: Optional[dict] = None
    """当前 user 轮待注入的多模态图片旁路 · wish-00ed11c2。
    形状: {"sid": session_id, "images": [(mime, b64), ...]}。
    _process_attachments 判定当前模型原生视觉时注册 · tool_loop._diet_messages_for_send
    发送前临时组装成 content list (内存/持久化里的 user message 永远保持 str · 零影响
    压缩层/token 计数/前端渲染)。 每个新 user 轮进 chat handler 时重置。"""


RUNTIME = DaemonRuntime()


def bg_max_tokens(default: Optional[int] = None) -> int:
    """后台任务 (proactive / scheduled / 各 worker) 的 max_tokens 真相源 (卷七十四续三十一)。

    病根: 用户在 WebUI 设的 max_tokens 只接进了主聊天 (_resolve_max_tokens)·后台 worker
      各写死小常量 (2000 / 2048 / 8000 …) → 用户设了大值·后台任务仍被截断。
    根治: 后台也读同一个真相源 (active config.max_tokens)·用户调一次全局生效。

    优先级: active config.max_tokens (用户全局设置) > default (调用方建议下限) >
            模型推荐 (default_max_tokens_for) > safe_max_tokens 兜底 floor。
    末尾过 safe_max_tokens: thinking 保底 + 按模型 max_output 封顶 (防超上限被 API 拒)。

    实时读 active config (不缓存 / 不依赖字段注入)·切配置下一次调用即生效。 best-effort:
    任何异常都回落到 safe_max_tokens·绝不让额度解析把后台任务搞崩。
    """
    from provider_presets import safe_max_tokens, default_max_tokens_for
    model = RUNTIME.model or ""
    req = 0
    try:
        from workers.provider_configs import get_active_config
        cfg = get_active_config(include_key=False)
        if cfg and cfg.get("max_tokens"):
            req = int(cfg["max_tokens"])
    except Exception:
        pass
    if req <= 0:
        req = int(default or 0) or default_max_tokens_for(model)
    return safe_max_tokens(req, model)


# ── wish-e1178ade · 层配置：按档位的 system prompt（进程级缓存 · 同档字节稳定）──
_SP_CACHE: dict = {}


def sp_for_profile(pid) -> str:
    """按会话档位的「层配置 + 工具名单」返回 system prompt。

    - 档没配 layers 且名单没有可磨项（standard / 不设限）→ RUNTIME.system_prompt（零改动路径）；
    - 配了 layers 或名单里有已全量提上的 → load_soul(...)，按 pid 缓存（同 pid 同文本 → 前缀缓存稳）；
    - wish-9de9bce3 · 精准磨：catalog_exclude = 该档「全量进 tools[]」的那批（visible_names 口径）
      → 延迟目录里不再重复列出已到手的工具（标准档恒无差 · 零字节变化）。
    - reload_soul_into_runtime 清缓存（画像更新后按新灵魂重装）。
    """
    try:
        from workers.tool_profiles import profile_soul_layers, resolve_profile
        lay = profile_soul_layers(pid or "")
        _pid, toolset = resolve_profile(pid or "")
        # ★ BRO 2026-10-05 报：闲聊档写着 thin、实际下发全量 —— 档位的 soul_thickness 从没被这里读过。
        #   thin / full 必须走 load_soul；只有 "" / standard 才允许走零改动快路径。
        _th = ""
        try:
            from workers.tool_profiles import profile_soul_thickness as _pst
            _th = _pst(pid or "") or ""
        except Exception:
            _th = ""
        excl = set()
        if toolset:
            from agent_tools._tool_catalog import visible_names
            excl = set(visible_names(toolset))
        if lay is None and not excl and _th in ("", "standard"):
            return RUNTIME.system_prompt or ""
        key = f"{pid or ''}|{_th}"      # 厚度进键：档改了不会拿到旧缓存
        hit = _SP_CACHE.get(key)
        if hit is not None:
            return hit
        from soul_loader import load_soul
        sp = load_soul(layers=lay,
                       thickness=(_th if _th in ("thin", "companion") else None),   # thin/companion 生效·standard/full 保持原行为
                       catalog_exclude=excl or None).system_prompt
        _SP_CACHE[key] = sp
        return sp
    except Exception:
        return RUNTIME.system_prompt or ""


def reload_soul_into_runtime() -> Optional[int]:
    """卷五十四 · 同会话热重载灵魂 (Hermes '建立对你的深度模型' 那一环)。

    update_bro_note / update_self_evolution 写完画像/日记后调它 · 重建
    RUNTIME.system_prompt → daemon API 路径下一轮 chat 立刻带上刚写的画像
    (daemon_api 每轮从 RUNTIME.system_prompt 现拼)。 之前要等重启/手动 reload-soul。

    best-effort: 任何异常都吞掉 (终端 REPL 不读 RUNTIME · 跨进程时无副作用)。
    返回新 system_prompt 字符数 · 失败返 None。
    """
    try:
        from soul_loader import load_soul
        soul = load_soul()
        RUNTIME.system_prompt = soul.system_prompt
        try:
            _SP_CACHE.clear()   # wish-e1178ade · 灵魂更新 → 各档位层配置 sp 也重装
        except Exception:
            pass
        return len(RUNTIME.system_prompt)
    except Exception:
        return None
