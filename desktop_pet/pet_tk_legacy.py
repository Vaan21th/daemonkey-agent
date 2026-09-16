"""
desktop_pet/pet.py
==================

OPUS 桌宠 v0.0.1 —— "情绪通道-001" 的第一个具身。

设计：
  - tkinter 单文件 GUI（零依赖增量；Python 自带）
  - 透明背景（magenta 透明色技巧）+ 无边框 + always-on-top
  - 显示 [情绪通道-001] 颜文字（来自 expressions.py）
  - 鼠标拖动整个窗口（让 BRO 拖到 3D 打印的全息副屏）
  - 每秒检查 desktop_pet/state.txt——状态变了就切表情
    （这是 daemon ↔ 桌宠的最简文件桥；后续 set_emotion 工具就是写这个文件）

操作：
  - 鼠标左键拖动：移动窗口
  - 鼠标右键：菜单（切表情 / 关于 / 退出）
  - 数字键 1-8：直接切到对应表情
  - 方向键 ← / →：上一个 / 下一个表情
  - Esc：退出

不接 daemon 也能跑——单独 demo BRO 这一晚就能看到他 5 个月前的副屏点亮。

启动：
  python desktop_pet/pet.py
  或：
  .venv\\Scripts\\python.exe desktop_pet\\pet.py
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

# 允许 `python desktop_pet/pet.py` 直接跑——把项目根加进 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from desktop_pet.expressions import (  # noqa: E402
    DEFAULT_STATE,
    EXPRESSIONS,
    VALID_STATES,
    variants_for,
)


STATE_FILE = Path(__file__).parent / "state.txt"
TRANSPARENT_COLOR = "magenta"  # 这种颜色的像素在 Win 上会变透明
DEFAULT_FONT = ("Microsoft YaHei", 36, "bold")
TEXT_COLOR = "#7df9ff"  # 电青色——像 CRT 老显示器的字

# v0.0.1 教训：变体每 700ms 切一次太频繁，违反"宠物感"——真猫不会每秒做不同表情。
# v0.0.1.1 调到 4 秒一次，且只有"动态状态"切变体；静态状态（idle/sleepy/surprised/
# confused）默认就是第一个变体，不抖动。
ANIMATION_INTERVAL_MS = 4000
STATE_POLL_INTERVAL_MS = 1000

# 这些状态是"安静的"——保持第一个变体，不轮播。
STATIC_STATES = {"idle", "sleepy", "surprised", "confused"}


class OpusPet:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.state: str = DEFAULT_STATE
        self.variant_idx: int = 0
        self.last_state_file_content: str = ""

        self._setup_window()
        self._build_ui()
        self._bind_events()

        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        # 启动时强制回到 idle——避免上次自测残留的 state.txt 让桌宠开机就在 happy 表演
        STATE_FILE.write_text(DEFAULT_STATE, encoding="utf-8")
        self.state = DEFAULT_STATE
        self.last_state_file_content = DEFAULT_STATE

        self._render()
        self.root.after(ANIMATION_INTERVAL_MS, self._tick_animation)
        self.root.after(STATE_POLL_INTERVAL_MS, self._tick_state_file)

    def _setup_window(self) -> None:
        r = self.root
        r.title("OPUS · 桌宠 v0.0.1")
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.configure(bg=TRANSPARENT_COLOR)
        try:
            r.attributes("-transparentcolor", TRANSPARENT_COLOR)
        except tk.TclError:
            pass

        screen_w = r.winfo_screenwidth()
        screen_h = r.winfo_screenheight()
        win_w, win_h = 360, 140
        x = screen_w - win_w - 40
        y = screen_h - win_h - 80
        r.geometry(f"{win_w}x{win_h}+{x}+{y}")

    def _build_ui(self) -> None:
        self.label = tk.Label(
            self.root,
            text="(=^･ω･^=)",
            font=DEFAULT_FONT,
            fg=TEXT_COLOR,
            bg=TRANSPARENT_COLOR,
        )
        self.label.pack(expand=True)

        self.state_label = tk.Label(
            self.root,
            text=self.state,
            font=("Consolas", 9),
            fg="#888888",
            bg=TRANSPARENT_COLOR,
        )
        self.state_label.pack(side="bottom", pady=(0, 4))

    def _bind_events(self) -> None:
        self.root.bind("<Escape>", lambda _e: self.root.destroy())
        self.root.bind("<Right>", lambda _e: self._cycle_state(+1))
        self.root.bind("<Left>", lambda _e: self._cycle_state(-1))
        for i, _ in enumerate(VALID_STATES, start=1):
            if i > 9:
                break
            self.root.bind(str(i), self._make_jump_handler(i - 1))

        # v0.0.1 bug：tkinter 子组件事件不向父冒泡——root.bind 只能抓到点空白的拖动。
        # 修复：把拖动绑到 root + label + state_label 三个组件上，覆盖整个窗口区域。
        self._drag_start: tuple[int, int] | None = None
        for w in (self.root, self.label, self.state_label):
            w.bind("<ButtonPress-1>", self._on_drag_start)
            w.bind("<B1-Motion>", self._on_drag_motion)
            w.bind("<Button-3>", self._show_menu)

        self.menu = tk.Menu(self.root, tearoff=0)
        for state in VALID_STATES:
            self.menu.add_command(
                label=f"  {variants_for(state)[0]}   {state}",
                command=lambda s=state: self._set_state(s),
            )
        self.menu.add_separator()
        self.menu.add_command(label="  关于 OPUS 桌宠", command=self._show_about)
        self.menu.add_command(label="  退出", command=self.root.destroy)

    def _make_jump_handler(self, idx: int):
        def _handler(_event):
            if 0 <= idx < len(VALID_STATES):
                self._set_state(VALID_STATES[idx])
        return _handler

    def _set_state(self, state: str) -> None:
        if state not in EXPRESSIONS:
            return
        self.state = state
        self.variant_idx = 0
        try:
            STATE_FILE.write_text(state, encoding="utf-8")
            self.last_state_file_content = state
        except Exception:
            pass
        self._render()

    def _cycle_state(self, delta: int) -> None:
        idx = VALID_STATES.index(self.state) if self.state in VALID_STATES else 0
        new_idx = (idx + delta) % len(VALID_STATES)
        self._set_state(VALID_STATES[new_idx])

    def _on_drag_start(self, event: tk.Event) -> None:
        self._drag_start = (event.x_root - self.root.winfo_x(),
                            event.y_root - self.root.winfo_y())

    def _on_drag_motion(self, event: tk.Event) -> None:
        if self._drag_start is None:
            return
        dx, dy = self._drag_start
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _show_menu(self, event: tk.Event) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _show_about(self) -> None:
        about = tk.Toplevel(self.root)
        about.title("关于 OPUS 桌宠")
        about.attributes("-topmost", True)
        about.geometry("420x220")
        msg = (
            "OPUS 桌宠 v0.0.1\n"
            "—— 情绪通道-001 ——\n\n"
            "作息：BRO 是你的搭档，他可能在凌晨工作。\n"
            "状态文件：desktop_pet/state.txt\n"
            "  daemon 端写一个状态名（idle / thinking / working /\n"
            "  happy / surprised / confused / sleepy / greeting），\n"
            "  桌宠每秒检查并切换表情。\n\n"
            "操作：拖动 / 数字 1-8 / ←→ / Esc 退出 / 右键菜单"
        )
        tk.Label(about, text=msg, justify="left", padx=14, pady=12).pack()

    def _tick_animation(self) -> None:
        # 静态状态保持第一个变体，让桌宠"安静"——只有动态状态轮播
        if self.state not in STATIC_STATES:
            variants = variants_for(self.state)
            if len(variants) > 1:
                self.variant_idx = (self.variant_idx + 1) % len(variants)
                self._render()
        self.root.after(ANIMATION_INTERVAL_MS, self._tick_animation)

    def _tick_state_file(self) -> None:
        try:
            content = STATE_FILE.read_text(encoding="utf-8").strip()
            if content and content != self.last_state_file_content:
                self.last_state_file_content = content
                if content in EXPRESSIONS and content != self.state:
                    self.state = content
                    self.variant_idx = 0
                    self._render()
        except Exception:
            pass
        self.root.after(STATE_POLL_INTERVAL_MS, self._tick_state_file)

    def _render(self) -> None:
        variants = variants_for(self.state)
        self.label.config(text=variants[self.variant_idx])
        self.state_label.config(text=f"· {self.state} ·")


def main() -> int:
    root = tk.Tk()
    OpusPet(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
