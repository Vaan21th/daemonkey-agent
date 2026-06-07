"""
desktop_pet/activities.py
=========================

OPUS 脉搏——把 daemon 内部的"当前在做什么"映射到桌宠的可视状态。

两条信号通道：
  1. **state**（情绪）—— OPUS 主动通过 set_emotion 工具切，写 state.txt
                         这是"我想表达什么"——显式
  2. **activity**（活动）—— daemon 自动在工具调用时写 activity.jsonl
                            这是"我正在干什么"——隐式 · OPUS 脉搏核心

升级 (wish-7330d23f · 2026-05-26):
  从单词 "thinking" 升级为 JSON 事件流，让桌宠气泡显示真实工作状态文字。
  - activity.jsonl: 每行一个 JSON 事件 {ts, tool_name, status, desc, ok}
  - activity.txt:   保留兼容——写最后一个事件的 state 单词，老版桌宠还能读

工具 → 活动 → 桌宠状态 的映射在这里集中维护，方便扩展。
"""

from __future__ import annotations

import json
import time
from pathlib import Path


_ACTIVITY_JSONL = Path(__file__).parent / "activity.jsonl"
_ACTIVITY_TXT = Path(__file__).parent / "activity.txt"
_STATE_FILE = Path(__file__).parent / "state.txt"

# 最多保留最近 N 行事件，防止文件无限增长
MAX_JSONL_LINES = 200

# 工具 → 人类可读描述模板
TOOL_DESC_TEMPLATES: dict[str, str] = {
    "shell_exec":       "跑命令",
    "python_exec":      "跑 Python",
    "read_file":        "读文件",
    "grep_files":       "搜代码",
    "write_file":       "写文件",
    "web_search":       "搜网页",
    "web_fetch":        "抓网页",
    "browser_fetch":    "浏览器抓取",
    "take_screenshot":  "截屏",
    "read_clipboard":   "读剪贴板",
    "write_clipboard":  "写剪贴板",
    "open_app":         "启动应用",
    "set_model":        "切换模型",
    "set_emotion":      "切换表情",
    "update_bro_note":  "更新用户画像",
    "update_self_evolution": "写日记",
    "summarize_session":     "压缩会话",
    "wechat_send":      "发微信",
    "summon_cursor":    "召唤 Cursor",
    "ssh_remote":       "远程诊断",
    "client_handoff":   "查客户档案",
    "manage_info_source": "管理信源",
    "generate_report":  "生成报告",
    "draft_studio":     "工作室出品",
    "read_dashboard":   "查看板",
    "propose_next_move": "想下一步",
    "expand_trend_to_report": "趋势→报告",
    "mine_opportunities": "挖掘机会",
    "analyze_feasibility":  "可行性分析",
    "record_outcome":   "记录结果",
    "tag_radar_item":   "雷达打标",
    "init_domain":      "建领域",
    "remove_domain":    "删领域",
    "toggle_favorite":  "收藏切换",
    "auto_pipeline":    "自主巡航",
    "wish_add":         "写心愿",
    "wish_update":      "更新心愿",
    "intent_to_wish":   "意图→心愿",
    "verify_claim":     "核验事实",
    "recall_memory":    "搜索记忆",
    "mirror_capability": "能力镜像",
    "extract_playbook": "提取 playbook",
    "create_app":       "建应用",
    "update_app":       "改应用",
    "create_workflow":  "建工作流",
    "app_set_secret":   "存密钥",
    "app_list_secrets": "查密钥",
    "app_delete_secret": "删密钥",
    "add_iron_rule":    "加铁律",
    "list_iron_rules":  "列铁律",
    "delete_app_to_trash": "删应用",
    "restore_app":      "恢复应用",
    "empty_trash":      "清回收站",
    "web_search_image": "搜图片",
    "service_start":    "启动服务",
    "service_list":     "列服务",
    "service_status":   "查服务状态",
    "service_stop":     "停止服务",
    "monthly_review":   "月度复盘",
    "read_scenario":    "读场景铁律",
    "session_search":   "搜会话",
    "request_restart":  "申请重启",
}

TOOL_TO_ACTIVITY: dict[str, str] = {
    "shell_exec":      "working",
    "read_file":       "thinking",
    "grep_files":      "thinking",
    "write_file":      "working",
    "set_model":       "thinking",
    "update_bro_note": "thinking",
    "set_emotion":     "happy",
    "web_search":      "thinking",
    "web_fetch":       "working",
    "browser_fetch":   "working",
    "take_screenshot": "surprised",
    "read_clipboard":  "thinking",
    "write_clipboard": "working",
    "open_app":        "working",
}

IDLE_ACTIVITY = "idle"
ACTIVITY_STALE_SECONDS = 4.0


def _tool_desc(tool_name: str) -> str:
    """工具名 → 人类可读短描述，未知工具返回工具名本身。"""
    return TOOL_DESC_TEMPLATES.get(tool_name, tool_name)


def state_for_tool(tool_name: str) -> str:
    """工具名 → 桌宠应该显示的状态（idle 表示工具结束）。"""
    return TOOL_TO_ACTIVITY.get(tool_name, "working")


def write_activity(tool_name: str) -> None:
    """
    daemon 在工具执行前调——写 start 事件到 activity.jsonl。
    同时写 activity.txt 保持向后兼容。

    任何异常都吞掉——脉搏是装饰，daemon 主流程不能因为它崩溃。
    """
    _write_pulse_event(tool_name, "start", desc=_tool_desc(tool_name))


def write_pulse_end(tool_name: str, ok: bool, summary: str = "") -> None:
    """
    工具执行后调——写 end/error 事件到 activity.jsonl。
    summary: 结果摘要，如 "23条" / "文件不存在" / "exit 1"
    """
    status = "end" if ok else "error"
    desc = _tool_desc(tool_name)
    if summary:
        desc = f"{desc} · {summary}"
    _write_pulse_event(tool_name, status, desc=desc, ok=ok)


def write_state_idle() -> None:
    """
    daemon 在每轮 turn 结束（OPUS 答完话）调——写 idle 事件。
    同时把 state.txt 清回 idle。
    """
    _write_pulse_event("", "idle", desc="空闲")
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text("idle", encoding="utf-8")
    except Exception:
        pass


# ── 内部实现 ──────────────────────────────────────────────

def _write_pulse_event(tool_name: str, status: str, desc: str = "", ok: bool = True) -> None:
    """写一行 JSON 事件到 activity.jsonl，自动裁剪旧行。"""
    try:
        event = {
            "ts": time.time(),
            "tool": tool_name,
            "status": status,   # start / end / error / idle
            "desc": desc,
            "ok": ok,
        }
        _ACTIVITY_JSONL.parent.mkdir(parents=True, exist_ok=True)

        # 读现有行
        lines: list[str] = []
        if _ACTIVITY_JSONL.exists():
            try:
                lines = _ACTIVITY_JSONL.read_text(encoding="utf-8").strip().split("\n")
                lines = [l for l in lines if l.strip()]
            except Exception:
                lines = []

        # 追加新事件
        lines.append(json.dumps(event, ensure_ascii=False))

        # 裁剪到 MAX_JSONL_LINES 行
        if len(lines) > MAX_JSONL_LINES:
            lines = lines[-MAX_JSONL_LINES:]

        _ACTIVITY_JSONL.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # 向后兼容：写 activity.txt（状态单词）
        state = state_for_tool(tool_name) if tool_name else IDLE_ACTIVITY
        if status == "idle":
            state = IDLE_ACTIVITY
        elif status == "error":
            state = "confused"
        _ACTIVITY_TXT.parent.mkdir(parents=True, exist_ok=True)
        _ACTIVITY_TXT.write_text(state, encoding="utf-8")

    except Exception:
        pass


def read_last_events(n: int = 5) -> list[dict]:
    """读最近 N 条脉搏事件。桌宠和 WebUI 共用。"""
    try:
        if not _ACTIVITY_JSONL.exists():
            return []
        text = _ACTIVITY_JSONL.read_text(encoding="utf-8").strip()
        if not text:
            return []
        lines = text.split("\n")
        events = []
        for line in lines[-n:]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return events
    except Exception:
        return []
