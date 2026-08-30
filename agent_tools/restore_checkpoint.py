"""回到对话里某一句 · 砍掉后面的话，并撤这句之后本会话改过的文件。"""
from __future__ import annotations

from . import TIER_CONFIRM, ToolResult, ToolSpec, current_session_id, register_tool


def _summarize(args: dict) -> str:
    tid = (args.get("turn_id") or "").strip()
    return f"restore_checkpoint → {tid or '(no turn_id)'}"


def _run(args: dict) -> ToolResult:
    from workers.turn_checkpoint import run

    sid = (args.get("session_id") or "").strip() or current_session_id()
    turn_id = (args.get("turn_id") or "").strip()
    apply = bool(args.get("apply"))
    if not turn_id:
        return ToolResult(ok=False, output="", error="turn_id 必填")
    if sid.startswith("t") and sid[1:].isdigit():
        return ToolResult(ok=False, output="", error="没拿到真 session_id")
    out = run(sid, turn_id, do_apply=apply)
    if not out.get("ok"):
        return ToolResult(ok=False, output="", error=out.get("error") or "回退失败")
    if not apply:
        n = len(out.get("restore") or []) + len(out.get("delete") or [])
        skip = len(out.get("skip") or [])
        snap = "有文件快照" if out.get("has_snaps") else "没有文件快照（只会砍对话）"
        return ToolResult(
            ok=True,
            output=(
                f"预览 · {snap} · 将写回 {len(out.get('restore') or [])} · "
                f"将删除 {len(out.get('delete') or [])} · 跳过 {skip}。"
                f"{' 共 ' + str(n) + ' 个文件。' if n else ''}"
                " 确认后带 apply=true 再调一次。"
            ),
        )
    return ToolResult(
        ok=True,
        output=(
            f"已回到 {turn_id}。"
            f" 写回 {len(out.get('restored') or [])} ·"
            f" 删除 {len(out.get('deleted') or [])} ·"
            f" 对话截断={'是' if out.get('truncated') else '否'}。"
        ),
    )


SPEC = ToolSpec(
    name="restore_checkpoint",
    description=(
        "Rewind this chat to a user turn. Cuts later messages. "
        "Reverts files this session wrote after that turn via write_file/edit_file. "
        "Preview first with apply=false, then apply=true."
    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "turn_id": {
                "type": "string",
                "description": "User-turn id to keep (from that bubble).",
            },
            "session_id": {
                "type": "string",
                "description": "Session id. Empty = current chat.",
            },
            "apply": {
                "type": "boolean",
                "description": "false=preview, true=do it.",
            },
        },
        "required": ["turn_id"],
    },
    run=_run,
    summarize=_summarize,
)

register_tool(SPEC)
