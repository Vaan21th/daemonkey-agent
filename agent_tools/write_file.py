"""
agent_tools/write_file.py
=========================

Daemonkey 的"写"——写或覆盖一个文本文件。

三档分类（动态）：
  - 默认 CONFIRM
  - 升级到 GUARD 的目标路径：
      .env / .env.* （凭证）
      soul/ 下的任何文件 （灵魂副本）
      .git/ （仓库内部状态）
      C:\\Users\\...\\opus-soul\\ 全局灵魂目录
      .venv/ 下任何路径

写策略：
  - mode='create' : 文件存在则报错（防止误覆盖）
  - mode='overwrite' : 全量覆盖
  - mode='append' : 追加到末尾（适合写日志）

精准改一段 → 用 edit_file (str_replace 局部替换)·不要用 overwrite。
  卷五十八教训: 大文件 (read_file 一次只能看 40K) 用 overwrite 改 = 凭残缺记忆
  重建整文件 = 悄悄碾掉没读到的部分 (chat.js 语音/文档/视觉就是这么没的)。
  本工具的 overwrite 现在带【缩水守卫】: 旧文件 >20K 且新内容掉到 <60% 直接拦·
  逼你改用 edit_file。 create / append / 小文件 overwrite 不受影响。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from . import (
    TIER_CONFIRM,
    TIER_GUARD,
    ToolResult,
    ToolSpec,
    current_session_id,
    register_tool,
)
from ._subprocess_helper import no_window_kwargs
from ._git_lock import daemon_git_lock
from ._edit_lock import (
    guard as _edit_guard,
    note_write as _edit_note,
    remember_before as _ckpt_before,
    blocked_by_restore as _restore_blocked,
)


ROOT = Path(__file__).resolve().parent.parent

# 卷四十四 F · daemon 核心代码目录 (改这些必须走 wish 分支)
# 修改这个列表 = 修改"什么算 daemon 改动" · 谨慎
_DAEMON_CORE_DIRS = (
    "agent_tools",
    "workers",
    "static",
    "tools",
    "desktop_pet",
)
_DAEMON_CORE_FILES = (
    "daemon_api.py",
    "opus_daemon.py",
    "soul_loader.py",
    "daemon_runtime.py",
    "tool_loop.py",
)


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()


def _detect_eol(path: Path, content: str) -> str:
    """检测目标换行风格 (wish-21c3ec8b · 换行保真)。

    已存在文件 → 跟随原文件的换行风格 (CRLF 文件写回 CRLF · LF 文件写回 LF)；
    新建文件 → 用内容自带的换行 (content 里 \r\n 多则 CRLF · 否则 LF)。

    返回 '\r\n' 或 '\n'。
    """
    if path.exists():
        try:
            with open(path, "rb") as f:
                raw = f.read(65536)
            if b"\r\n" in raw:
                return "\r\n"
        except Exception:
            pass
    crlf = content.count("\r\n")
    lf = content.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def _normalize_eol(content: str, eol: str) -> str:
    """把内容统一成目标换行 (wish-21c3ec8b)。

    - 先把所有 \r\n / \r 统一成 \n
    - 再按目标 eol 替换 (目标是 \n 就不动 · 目标是 \r\n 就全转)
    """
    norm = content.replace("\r\n", "\n").replace("\r", "\n")
    if eol == "\r\n":
        norm = norm.replace("\n", "\r\n")
    return norm


def _is_guard_target(path: Path) -> bool:
    """命中这些位置一律 GUARD。

    2026-07-28 BRO 拍板 · GUARD 重新定界 = 只留「开不了机 / 不可逆」级:
      - .env            KEY 泄露/丢失不可逆 (铁律 7)
      - .git/           毁仓库历史不可逆
      - .venv/          改坏虚拟环境 = daemon 起不来 = 自爆同级
    以下从 GUARD 降到 CONFIRM (有 git 版本/副本冗余·可恢复·不该弹窗):
      soul/ · opus-soul · skills-cursor  (灵魂层·写坏可从副本/git 恢复)
    """
    name = path.name.lower()
    if name == ".env" or name.startswith(".env."):
        return True
    parts_lower = [p.lower() for p in path.parts]
    if ".git" in parts_lower:
        return True
    if ".venv" in parts_lower or "site-packages" in parts_lower:
        return True
    return False


def _is_daemon_core(path: Path) -> bool:
    """卷四十四 F · 这个路径是不是 daemon 核心代码 (改这些要走 wish)。

    judgement:
      - path 在 ROOT 下
      - 且 path 第一层目录是 _DAEMON_CORE_DIRS 之一 · 或 path 名是 _DAEMON_CORE_FILES 之一
    """
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return False  # 不在 daemon 项目内 · 不管
    parts = rel.parts
    if not parts:
        return False
    if parts[0] in _DAEMON_CORE_DIRS:
        return True
    if len(parts) == 1 and parts[0] in _DAEMON_CORE_FILES:
        return True
    return False


def _current_git_branch() -> Optional[str]:
    """拿当前 git 分支名 · 拿不到返 None (没 git / 不在 repo / 异常)。

    sub-process · 显式 utf-8 (Windows 默认 GBK 会崩 · 卷四十二教训)。
    """
    if not (ROOT / ".git").exists():
        return None
    try:
        with daemon_git_lock("write_file:rev-parse"):
            res = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=ROOT, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=3,
                **no_window_kwargs(),
            )
        if res.returncode == 0:
            return (res.stdout or "").strip() or None
    except Exception:
        pass
    return None


def _branch_guard_warning(path: Path) -> Optional[str]:
    """卷四十四 F · master 上改 daemon 核心代码时返回一段 warn 文案。

    不阻止调用 · 只把 warn 拼进 ToolResult.output · Daemonkey 看到了就知道下次走 wish。
    返回 None 表示无需警告。
    """
    if not _is_daemon_core(path):
        return None
    branch = _current_git_branch()
    if branch is None:
        return None  # 没 git 信息 · 不警告
    if branch.startswith("wish-"):
        return None  # 已经在 wish 分支 · 合规
    if branch != "master":
        return None  # 在某个 feature 分支 · 不是 master · OK
    from identity import localize_narration as _ln
    return _ln(
        "WARN · daemon 工程铁律 1 触发 (卷四十四 F):\n"
        f"  你刚在 master 分支上改了 daemon 核心代码: {path.name}\n"
        "  按 data/cognition/daemon_rules.md 铁律 1 · 这应该走 wish 流程 (卷五十三四态):\n"
        "    1) wish_create + wish_update status=active · 批方案后清 daemon_phase → 自动开 wish-XXX/<slug> 分支\n"
        "    2) 在 wish 分支上改 · 不污染 master\n"
        "    3) 改完 wish_update status=review · BRO 验收点 live 时自动 merge 回 master\n"
        "  本次写入已生效 · 但下次先 wish_create · 不要再直接打 master。\n"
        "  如果这次是 BRO 急手要的 hotfix · 可以无视这条 · 但在 reflection 里说明。"
    )


def _active_wish_ids() -> list:
    """列出当前所有 active 的 wish id（started_at 新的在前）。

    ⚠ 只用来「告诉人有哪几条可选」—— 不再用它替人挑（2026-09-18 BRO 拍板「不猜，看分支名」）。
    共树多实例时 active 实测有 6 条·最近那条常常跟手上活无关·挑错 = 改动记到别的账上。
    读不到 / 没有 → 空 list。
    注：wish 条目只有 created_at / approved_at / started_at / completed_at·没有 updated_at。
    """
    try:
        import json
        data = json.loads((ROOT / "data" / "opus_wishlist.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    items = data.get("wishes") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    act = [w for w in items if isinstance(w, dict)
           and str(w.get("status") or "").lower() == "active"
           and str(w.get("id") or "").startswith("wish-")]
    act.sort(key=lambda w: str(w.get("started_at") or w.get("created_at") or ""), reverse=True)
    return [str(w.get("id")) for w in act if w.get("id")]


def _note_branch(err: str, note: Optional[str]) -> str:
    """早退时也要说清「HEAD 已经换分支了」。

    切分支发生在所有闸之后、真正写盘之前，但写盘过程自己还有失败路径
    （mkdir / 会话已回退 / 编辑锁 / 写盘异常）。这些路径如果不带这句，人只看到
    「写入被拒」，不知道仓库已经不在原分支上 —— 下一步会一直以为自己还在 master，
    而且 _auto_branch_for_core 下次直接 early return（已经在 wish-* 上），静默不提。
    """
    return f"{err}\n\n{note}" if note else err


def _auto_branch_for_core(path: Path, wish_id: Optional[str] = None) -> Optional[str]:
    """核心文件要写、人却在 master 上 → 先开/切 wish 分支再落笔（wish-cf51665e P1「方案 2」）。

    消灭「先开分支、再写文件」两步之间的中间态 —— 忘了第一步就直接改 master（已犯 4 次）。
    返回一段给 Daemonkey 看的说明（分支已切过去）· None = 不需要 / 做不到
    （做不到【不阻断】写入 —— 退回 _branch_guard_warning 的事后警告）。

    分层判据（硬→软）:
      ① wish_id 显式给 → 用它
      ② 已在 wish-* 分支 → 不需要（下面早退·也避开双重提醒）
      ③ 否则 → **不猜**，返回「你没挂 wish」的提醒（2026-09-18 BRO 拍板）

    为什么③是「提醒」而不是「自动挑一条 active 的」：实测 wishlist 里 active 有 6 条·
    最近那条常常跟手上活无关 —— 挑错就把改动记到别的账上；没有 active 时旧逻辑还会
    编一个 wish-auto-xxx 出来，那种名字合的时候找不到主人。 分支名在这里也给不出答案，
    因为「人走到这个函数」本身就意味着他在 master 上、没挂分支。
    """
    if not _is_daemon_core(path):
        return None
    branch = _current_git_branch()
    if branch is None or branch.startswith("wish-"):
        return None          # 没 git 信息 / 已经合规 —— 都不动
    if branch != "master":
        return None          # 别的 feature 分支 · 不擅自动

    wid = (wish_id or "").strip()
    if not wid:
        act = _active_wish_ids()
        hint = ("  当前 active 的有：" + "、".join(act[:3]) + ("…" if len(act) > 3 else "") + "\n"
                if act else "  当前 wishlist 里没有 active 的心愿。\n")
        return ("⚠ 这是 daemon 核心文件 · 你人在 master 上、也没指定挂哪条 wish。\n"
                "  我没替你挑 —— 猜错会把改动记到别的账上（上次差点）。\n"
                + hint +
                "  → 要挂哪条就把 wish_id 传给 write_file 再来一次；"
                "或先 wish_update 把那条置 active 再走。\n"
                "  （这次改动会直接落在 master 上 · 除非你先切分支）")
    new_branch = f"{wid}/core-write"

    reused = False
    try:
        with daemon_git_lock("write_file:auto-branch"):
            res = subprocess.run(
                ["git", "checkout", "-b", new_branch],
                cwd=ROOT, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=15,
                **no_window_kwargs(),
            )
            if res.returncode != 0:
                # 「分支已存在」是常态而不是异常：分支名按 wid 稳定推出来，所以同一个 wish
                # 第二次写核心文件必然撞名（或 merge 回 master 后本地分支还留着）。
                # → 直接切过去复用，别退回 master（退回 = 自动开分支这个能力对该 wish 永久失效）。
                res2 = subprocess.run(
                    ["git", "checkout", new_branch],
                    cwd=ROOT, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=15,
                    **no_window_kwargs(),
                )
                if res2.returncode != 0:
                    err = (res2.stderr or res.stderr or res.stdout or "").strip()[:200]
                    return (f"⚠ 想切到 wish 分支 `{new_branch}` 但失败了（{err}）· "
                            f"本次仍写在 {branch or 'master'} 上 —— 请手动 `git checkout` 后重写一次。")
                reused = True
    except Exception as e:
        return f"⚠ 自动开 wish 分支异常（{e}）· 本次仍写在 {branch or 'master'} 上。"

    head = (f"✓ 这是 daemon 核心文件 · 分支 `{new_branch}` 已存在 → 切过去继续落笔。\n"
            if reused else
            f"✓ 这是 daemon 核心文件 · 已在 master 上 → 先切到 wish 分支 `{new_branch}` 再落笔。\n")
    return head + "  依据：你显式传了 wish_id。"


def _classify(args: dict) -> str:
    raw = args.get("path") or ""
    if not raw:
        return TIER_CONFIRM
    try:
        p = _resolve(raw)
    except Exception:
        return TIER_CONFIRM
    if _is_guard_target(p):
        return TIER_GUARD
    return TIER_CONFIRM


def _summarize(args: dict) -> str:
    p = args.get("path", "?")
    mode = args.get("mode", "overwrite")
    content = str(args.get("content") or "")
    if not content.strip():
        return f"write_file  {p}  mode={mode}  (content 空·将自动抓本轮回复正文兜底)"
    n_lines = content.count("\n") + (1 if content else 0)
    return f"write_file  {p}  mode={mode}  size={len(content)} chars / {n_lines} lines"


def _run(args: dict) -> ToolResult:
    raw = args.get("path")
    if not raw:
        return ToolResult(ok=False, output="", error="missing 'path'")

    # 卷七十四续二十四 · 两步法兜底 (补 __init__.py 第 84 行注释承诺却没实现的 "write_file.content 兜底")。
    # 痛点: DeepSeek 等弱模型 tool call 的长 content 经常丢成空壳 → 被门口 _validate_args 当
    # "缺必填字段" 挡回 → 30+ 次空调用死循环 (BRO 手机做 word 翻车现场)。
    # 解法 (对齐 generate_report): content 没传 / 纯空白 → 抓 "LLM 本轮已写的回复正文" 当内容
    # (写文本流是弱模型强项·丢的只是结构化长参数)。 前沿模型照旧直接传 content·根本不进这条兜底。
    content = args.get("content")
    grabbed_from_turn = False
    if content is None or not str(content).strip():
        try:
            from . import current_turn_text
            grabbed = current_turn_text() or ""
        except Exception:
            grabbed = ""
        if grabbed.strip():
            content = grabbed
            grabbed_from_turn = True
        else:
            return ToolResult(
                ok=False, output="",
                error=(
                    "没拿到 content · 两种给法二选一:\n"
                    "  ① 把完整内容直接放进 content 参数;\n"
                    "  ② 先在你这条回复正文里写完整内容 · 再调本工具【只给 path · 不带 content】 · "
                    "我会自动抓你刚写的正文 (适合长文档·或对长参数不稳的模型)。\n"
                    "→ 要做精排 word/docx 文档 (带封面/排版/可下载) 请改用 generate_report·"
                    "它只需 title·正文同样能自动抓·别用 write_file 写 .docx (会写成假 docx 纯文本)。"
                ),
            )
    mode = (args.get("mode") or "overwrite").lower()
    if mode not in ("create", "overwrite", "append"):
        return ToolResult(ok=False, output="", error=f"invalid mode: {mode}")

    path = _resolve(raw)

    if mode == "create" and path.exists():
        return ToolResult(ok=False, output="", error=f"file already exists: {path}")

    if not path.exists():
        from workers.output_sinks import refuse_new_path
        sink_err = refuse_new_path(path, ROOT)
        if sink_err:
            return ToolResult(ok=False, output="", error=sink_err)

    try:
        from workers.playbook_guard import check_path
        pb_err = check_path(path, content)
    except Exception:
        return ToolResult(ok=False, output="", error="操作手册闸不可用，拒绝写入。")
    if pb_err:
        return ToolResult(ok=False, output="", error=pb_err)

    try:
        from workers.notebook_guard import check_path as _nb_check
        nb_err = _nb_check(path, content)
    except Exception:
        return ToolResult(ok=False, output="", error="记忆落点闸不可用，拒绝写入。")
    if nb_err:
        return ToolResult(ok=False, output="", error=nb_err)

    # wish-cf51665e P1「方案 2」· 所有闸都过了、确定要写了 → 才动分支。
    # 放这么晚是有意的: 太早切会把「其实会被拒」的情况也白切一次分支。
    _branch_note = _auto_branch_for_core(path, args.get("wish_id"))

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return ToolResult(ok=False, output="", error=_note_branch(f"mkdir parent failed: {e}", _branch_note))

    old_content: Optional[str] = None
    can_rollback = False
    if mode == "overwrite" and path.exists():
        try:
            old_content = path.read_text(encoding="utf-8")
            can_rollback = True
        except Exception:
            pass

    # 卷五十八 · 缩水守卫 · chat.js 444K 整文件覆盖丢功能事故的硬闸
    #   "大文件 overwrite 暴跌" = 经典"没读全·凭记忆重建·碾掉看不见的部分"特征
    #   (read_file 一次只 40K · 9000 行文件你大概率没读全)。 拦下来逼用 edit_file 局部替换。
    #   阈值: 旧文件 > 20K 字符 (≈半个读窗) 且新内容掉到 < 60% → 拦。 有意大删传 allow_shrink=true。
    if old_content is not None and not args.get("allow_shrink"):
        old_n, new_n = len(old_content), len(content)
        if old_n > 20000 and new_n < old_n * 0.6:
            return ToolResult(
                ok=False,
                output="",
                error=(
                    f"⛔ 缩水守卫拦截: 你要把 {path.name} 从 {old_n} → {new_n} 字符"
                    f" (掉了 {100 * (old_n - new_n) // old_n}%)。\n"
                    "这正是 chat.js 整文件覆盖丢功能事故的特征——大文件 read_file 一次只能看 40K·"
                    "你大概率没读全·overwrite 会用残缺记忆碾掉没读到的部分 (语音/文档/视觉就是这么没的)。\n"
                    "→ 正确做法: 用 edit_file 做局部 str_replace·只动你要改的那段·其余字节原地不动。\n"
                    "→ 如果你确实是【有意】大幅删减 (删了一整块死代码)·传 allow_shrink=true 再来一次。"
                ),
            )

    # 编辑并发软锁: 覆盖/追加已存在文件时·另一个对话正改它 / 磁盘被外部改过 → 软提示 (可 force 过)
    # create 模式是新建文件·没有覆盖风险(撞 already exists 已在上面拦)·跳过。
    _owner = current_session_id()
    if _restore_blocked(_owner):
        return ToolResult(ok=False, output="", error=_note_branch("会话已回退 · 停手", _branch_note))
    _lock_note = None
    if mode != "create" and path.exists():
        if old_content is not None:
            _cur_text = old_content
        else:
            try:
                _cur_text = path.read_text(encoding="utf-8")
            except Exception:
                _cur_text = ""
        _lock_ok, _lock_note = _edit_guard(
            str(path), _owner, _cur_text, force=bool(args.get("force")), tool=f"write_file:{mode}"
        )
        if not _lock_ok:
            return ToolResult(ok=False, output="",
                              error=_note_branch(_lock_note or "编辑锁冲突", _branch_note))

    try:
        # wish-21c3ec8b · 换行保真: 先定目标 eol (已存在文件跟随原风格) · 内容归一化 · newline="" 禁止 Python 转换
        _ckpt_before(path)
        _eol = _detect_eol(path, content)
        _payload = _normalize_eol(content, _eol)
        if mode == "append":
            with path.open("a", encoding="utf-8", newline="") as f:
                f.write(_payload)
        else:
            with path.open("w", encoding="utf-8", newline="") as f:
                f.write(_payload)
    except Exception as e:
        return ToolResult(ok=False, output="",
                          error=_note_branch(f"{type(e).__name__}: {e}", _branch_note))

    try:
        # wish-21c3ec8b · 校验也用 newline="" 保留原始字节 · 换行差异不再被归一化掩盖
        with open(path, encoding="utf-8", newline="") as f:
            written = f.read()
    except Exception as e:
        rolled = False
        if can_rollback and old_content is not None:
            try:
                path.write_text(old_content, encoding="utf-8", newline="")
                rolled = True
            except Exception:
                pass
        return ToolResult(
            ok=False,
            output="",
            error=(
                f"write verify read-back failed: {e}. "
                f"{'Rolled back to previous content.' if rolled else 'No rollback (file was new or non-UTF-8).'}"
            ),
        )

    if mode == "append":
        mismatch_detail = (
            f"appended {len(_payload)} chars but file does not end with them"
            if not written.endswith(_payload)
            else ""
        )
    else:
        mismatch_detail = (
            f"expected {len(content)} chars exact match but got {len(written)} chars on disk"
            if written != _payload
            else ""
        )

    if mismatch_detail:
        rolled = False
        if can_rollback and old_content is not None:
            try:
                path.write_text(old_content, encoding="utf-8", newline="")
                rolled = True
            except Exception:
                pass
        return ToolResult(
            ok=False,
            output="",
            error=(
                f"write verify roundtrip mismatch: {mismatch_detail}. "
                f"Likely cause: silent encoding loss / concurrent overwrite / disk error. "
                f"{'Rolled back to previous content.' if rolled else 'No rollback available.'}"
            ),
        )

    # 写成功 · 把编辑锁刷新到新内容指纹(同一对话连续写不误报·也记录"这文件谁动过")
    _edit_note(str(path), _owner, written, tool=f"write_file:{mode}")

    try:
        size = path.stat().st_size
    except OSError:
        size = -1

    base_output = (
        f"wrote {path}\n"
        f"mode={mode}  bytes_on_disk={size}  chars_written={len(content)}  verified=utf-8-roundtrip"
    )
    if grabbed_from_turn:
        base_output += (
            "\n(content 为空 · 已自动抓取你本轮回复正文当文件内容 · "
            "若不是你想写的·重新调用并显式传 content)"
        )
    if _lock_note:
        base_output = f"{base_output}\n{_lock_note}"

    # 卷四十四 F · branch guard
    if _branch_note:
        base_output = f"{base_output}\n\n{_branch_note}"
    warn = _branch_guard_warning(path)
    if warn:
        base_output = f"{base_output}\n\n{warn}"

    # 卷五十四 · B4 · 编辑后即时自检 (告警·不拦·"锁出口不锁动作")
    try:
        from workers.edit_selfcheck import budget_check, selfcheck
        sc_ok, sc_warn = selfcheck([str(path)])
        if not sc_ok:
            base_output = f"{base_output}\n\n{sc_warn}"
        b_ok, b_warn = budget_check([str(path)])
        if not b_ok:
            base_output = f"{base_output}\n\n{b_warn}"
    except Exception:
        pass

    try:
        from workers.overlay_policy import attach_write_notice
        base_output = attach_write_notice(path, base_output)
    except Exception:
        pass

    return ToolResult(ok=True, output=base_output, stage_path=path)


SPEC = ToolSpec(
    name="write_file",
    description=(
        "创建/覆盖/追加文本文件。精排 docx 用 generate_report。HTML 原型写 data/design/ 或 data/workshop/outputs/，写完中栏能看。长内容可只传 path。.env/soul/.git 是 GUARD。"    ),
    tier=TIER_CONFIRM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "相对工程根。新文件须落已有分类：HTML→data/design 或 data/workshop/outputs；草稿→data/runtime/scratch。",
            },
            "content": {
                "type": "string",
                "description": "要写入的全文。不传则抓本条回复正文。",
            },
            "mode": {
                "type": "string",
                "enum": ["create", "overwrite", "append"],
                "description": "create: fail if exists. overwrite: replace. append: add to end.",
            },
            "allow_shrink": {
                "type": "boolean",
                "description": (
                    "Bypass the shrink-guard. Only set true when you INTENTIONALLY shrink a large file "
                    ">40% (e.g. deleting a big dead-code block). "
                ),
            },
            "force": {
                "type": "boolean",
                "description": (
                    "Override the concurrent-edit advisory lock (another conversation editing this file, "
                    "or the file changed on disk since the last tool write). Only set true after confirming "
                    "you won't clobber someone else's work. Default false."
                ),
            },
            "wish_id": {
                "type": "string",
                "description": "核心文件指定 wish 分支 id；不传则自动挑 active 的。",
            },
        },
        "required": ["path"],
    },
    run=_run,
    summarize=_summarize,
    classify=_classify,
)


register_tool(SPEC)
