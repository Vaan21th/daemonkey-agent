"""
desktop_pet/pet.py
==================

OPUS 桌宠 v0.1 —— PyQt6 重写版。

设计目标：
  - **平时是像素小猫，在桌面游走**（三花/橙猫风格）
  - **触发表情时头顶弹出气泡**（颜文字）
  - **OPUS 心电图**：daemon 在做什么，桌宠的小猫就反映什么
  - 拖拽、双击弹快速命令框、右键菜单
  - 鼠标接近时小猫看向鼠标
  - 夜间模式（凌晨 2-5 点）速度变慢
  - 位置记忆（位置存 position.txt）

技术栈：PyQt6 6.11+
  - 透明 frameless always-on-top
  - QPixmap sprite（PNG 资源在 sprites/，没有就 fallback 到 emoji）
  - QTimer 控制游走、气泡淡出、状态轮询

文件桥（和 daemon 通信）：
  - state.txt    OPUS 显式情绪（set_emotion 工具）
  - activity.txt daemon 隐式活动（tool_loop 钩子自动写）
  - position.txt 桌宠位置记忆（自己写）

启动：
  .venv\\Scripts\\python.exe desktop_pet\\pet.py
"""

from __future__ import annotations

import datetime as dt
import json
import random
import sys
import time
from pathlib import Path

try:
    from PyQt6.QtCore import Qt, QTimer, QPoint, QSize
    from PyQt6.QtGui import (
        QAction,
        QColor,
        QFont,
        QGuiApplication,
        QPainter,
        QPainterPath,
        QPen,
        QPixmap,
        QTransform,
    )
    from PyQt6.QtWidgets import (
        QApplication,
        QDialog,
        QInputDialog,
        QLabel,
        QMenu,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    # 桌宠是可选功能·没装 PyQt6 时给个原生弹窗 (pythonw 无控制台也能看到)·别静默崩
    _MSG = (
        "桌宠需要 PyQt6 才能跑。\n\n"
        "去启动器『环境』页点『安装/修复环境』·或手动跑：\n"
        ".venv\\Scripts\\python.exe -m pip install PyQt6"
    )
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, _MSG, "桌宠 · 缺依赖 PyQt6", 0x40)
    except Exception:
        print(_MSG)
    raise SystemExit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from desktop_pet.expressions import (  # noqa: E402
    DEFAULT_STATE,
    EXPRESSIONS,
    VALID_STATES,
    variants_for,
)
from desktop_pet.activities import (  # noqa: E402
    ACTIVITY_STALE_SECONDS,
    IDLE_ACTIVITY,
    read_last_events,
)


PET_DIR = Path(__file__).parent
STATE_FILE = PET_DIR / "state.txt"
ACTIVITY_FILE = PET_DIR / "activity.txt"
POSITION_FILE = PET_DIR / "position.txt"
SPRITE_DIR = PET_DIR / "sprites"
MANIFEST_FILE = SPRITE_DIR / "manifest.json"

# state → 优先动作（如果 manifest 没有，走 fallback 链）。
# 第一项是首选；后续是 fallback 顺序，最后总是落到 idle / 静态 sprite。
STATE_TO_ACTIONS: dict[str, list[str]] = {
    "idle":      ["idle"],
    "thinking":  ["paw", "idle"],
    "working":   ["paw", "walk"],
    "happy":     ["meow", "idle"],
    "surprised": ["jump", "idle"],
    "confused":  ["curious", "idle"],
    "sleepy":    ["sleep", "idle"],
    "greeting":  ["meow", "idle"],
}
# 行走时的动作（不依赖 state.state——任何 state 走起来都用 walk）
WALK_ACTION = "walk"

# 视觉
PET_SIZE = QSize(96, 96)
BUBBLE_PADDING = 12
BUBBLE_FONT = QFont("Microsoft YaHei", 13, QFont.Weight.Bold)
BUBBLE_BG = QColor(20, 24, 32, 230)
BUBBLE_BORDER = QColor(125, 249, 255, 200)
BUBBLE_TEXT = QColor(125, 249, 255, 255)

# 行为
WALK_SPEED_PX = 4              # 每帧移动像素（v0.1.1 从 2 提到 4）
WALK_TICK_MS = 50              # 移动节拍（20fps，更顺滑）
WALK_PAUSE_MIN_S = 6           # 偶尔停下休息——更长间隔，少打扰
WALK_PAUSE_MAX_S = 18
DIRECTION_CHANGE_PROB = 0.004  # v0.1.1 从 0.02 降到 0.004 —— 不再原地晃
WALK_FRAME_SWITCH_PROB = 0.30  # 走路 sprite 切换频率（每帧 30%）

# v0.1.2 · 按 state 给不同动画节拍——idle 慢呼吸，walk/jump 快活
FRAME_INTERVAL_MS_DEFAULT = 200
FRAME_INTERVAL_MS_BY_STATE: dict[str, int] = {
    "idle":      450,   # 呼吸节奏，约 1.8 秒一个 4 帧循环
    "sleepy":    600,   # 睡得慢
    "thinking":  280,   # 伸爪悠悠
    "confused":  280,
    "happy":     200,   # 喵叫快活
    "greeting":  200,
    "surprised": 130,   # 弹跳要爽
    "working":   200,
}
FRAME_INTERVAL_MS_WALKING = 100   # 走路节拍（独立于 state，快脚步）

# state 持久过期 —— OPUS 设了 happy/thinking 后多久回 idle（兜底，避免卡住）
STATE_STALE_SECONDS = 30.0
NIGHT_SLOWDOWN = 0.4
DRAG_PAUSE_S = 0.3             # 拖完只 paused 0.3 秒就继续游走

POLL_TICK_MS = 1000
BUBBLE_AUTO_HIDE_MS = 5000
ACTIVITY_BUBBLE_HIDE_MS = 2500


def _is_night() -> bool:
    """凌晨 2~5 点桌宠速度变慢——和用户的作息对齐·夜里别太闹腾。"""
    h = dt.datetime.now().hour
    return 2 <= h < 5


class Bubble(QWidget):
    """头顶弹出的颜文字气泡——半透明圆角框 + 朝下的小三角。"""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._text = ""
        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self.hide)

    def show_text(self, text: str, ms: int = BUBBLE_AUTO_HIDE_MS) -> None:
        self._text = text
        fm = self.fontMetrics()
        f = BUBBLE_FONT
        self.setFont(f)
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(text)
        text_h = fm.height()
        self.resize(text_w + BUBBLE_PADDING * 2, text_h + BUBBLE_PADDING * 2 + 8)
        self.update()
        self.show()
        self.raise_()
        self._auto_hide.start(ms)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        body_h = h - 8

        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(w), float(body_h), 10.0, 10.0)
        tri = QPainterPath()
        tri.moveTo(w / 2 - 7, body_h)
        tri.lineTo(w / 2 + 7, body_h)
        tri.lineTo(w / 2, body_h + 8)
        tri.closeSubpath()
        path = path.united(tri)

        p.setBrush(BUBBLE_BG)
        p.setPen(QPen(BUBBLE_BORDER, 1.5))
        p.drawPath(path)

        p.setFont(BUBBLE_FONT)
        p.setPen(BUBBLE_TEXT)
        p.drawText(
            BUBBLE_PADDING,
            BUBBLE_PADDING,
            w - BUBBLE_PADDING * 2,
            body_h - BUBBLE_PADDING * 2,
            Qt.AlignmentFlag.AlignCenter,
            self._text,
        )


class OpusPet(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(PET_SIZE)

        self._state: str = DEFAULT_STATE
        self._last_state_file_text: str = ""
        self._last_activity_file_text: str = ""
        self._last_activity_mtime: float = 0.0
        self._last_pulse_ts: float = 0.0

        self._action_frames: dict[str, list[QPixmap]] = {}
        self._idle_pixmap: QPixmap | None = None
        self._walk_pixmaps: list[QPixmap] = []
        self._walk_frame_idx: int = 0
        self._is_walking: bool = False
        self._facing_right: bool = True
        self._fallback_glyph: str = "🐈"
        self._frame_tick_idx: int = 0

        self._load_sprites()
        self._frame_anim_timer = QTimer(self)
        self._frame_anim_timer.timeout.connect(self._tick_frame_anim)
        self._frame_anim_timer.start(FRAME_INTERVAL_MS_DEFAULT)
        self._current_frame_interval_ms = FRAME_INTERVAL_MS_DEFAULT
        self._state_set_at: float = time.time()
        self._build_ui()

        self._direction = random.choice([-1, 1])
        self._walk_paused_until: float = 0.0
        self._walk_timer = QTimer(self)
        self._walk_timer.timeout.connect(self._tick_walk)
        self._walk_timer.start(WALK_TICK_MS)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._tick_poll_files)
        self._poll_timer.start(POLL_TICK_MS)

        self._bubble = Bubble()

        self._restore_position()
        self._render()
        self._init_state_files()

        self._drag_offset: QPoint | None = None

    def _build_ui(self) -> None:
        self._sprite_label = QLabel(self)
        self._sprite_label.setGeometry(0, 0, PET_SIZE.width(), PET_SIZE.height())
        self._sprite_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sprite_label.setStyleSheet("background: transparent;")

        font = QFont("Segoe UI Emoji", 56)
        self._sprite_label.setFont(font)

        self._menu = QMenu(self)
        for s in VALID_STATES:
            sample = variants_for(s)[0]
            act = QAction(f"  {sample}    {s}", self)
            act.triggered.connect(lambda _checked=False, st=s: self._user_set_state(st))
            self._menu.addAction(act)
        self._menu.addSeparator()

        recenter = QAction("  回到屏幕中下方", self)
        recenter.triggered.connect(self._recenter)
        self._menu.addAction(recenter)

        about = QAction("  关于 OPUS 桌宠 v0.1", self)
        about.triggered.connect(self._about)
        self._menu.addAction(about)

        quit_act = QAction("  退出", self)
        quit_act.triggered.connect(QApplication.instance().quit)
        self._menu.addAction(quit_act)

    def _load_sprites(self) -> None:
        """
        加载顺序：
          1. 优先 sprites/manifest.json 里声明的多动作 sprite（自己跑图 + tools/process_sprites.py 处理后产生）
          2. fallback 到 v0.1 的初版 cat_01_idle / cat_02_walk1 / cat_03_walk2
        """
        if not SPRITE_DIR.exists():
            return

        manifest: dict = {}
        if MANIFEST_FILE.exists():
            try:
                manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}

        for action, info in manifest.items():
            files = info.get("files", []) if isinstance(info, dict) else []
            frames: list[QPixmap] = []
            for fname in files:
                p = SPRITE_DIR / fname
                if not p.exists():
                    continue
                pm = QPixmap(str(p))
                if pm.isNull():
                    continue
                frames.append(
                    pm.scaled(
                        PET_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.FastTransformation,
                    )
                )
            if frames:
                self._action_frames[action] = frames

        idle = SPRITE_DIR / "cat_01_idle.png"
        if idle.exists():
            pm = QPixmap(str(idle))
            if not pm.isNull():
                self._idle_pixmap = pm.scaled(
                    PET_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
        for name in ("cat_02_walk1.png", "cat_03_walk2.png"):
            p = SPRITE_DIR / name
            if not p.exists():
                continue
            pm = QPixmap(str(p))
            if pm.isNull():
                continue
            self._walk_pixmaps.append(
                pm.scaled(
                    PET_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            )

    def _frames_for_state(self, state: str, walking: bool) -> list[QPixmap]:
        """根据当前 state + 是否在走，挑一组帧序列。manifest 优先，否则 fallback。"""
        if walking:
            walk = self._action_frames.get(WALK_ACTION)
            if walk:
                return walk
            return self._walk_pixmaps  # v0.1 fallback

        for action in STATE_TO_ACTIONS.get(state, ["idle"]):
            frames = self._action_frames.get(action)
            if frames:
                return frames

        if self._idle_pixmap is not None:
            return [self._idle_pixmap]
        return []

    def _init_state_files(self) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(DEFAULT_STATE, encoding="utf-8")
        self._last_state_file_text = DEFAULT_STATE
        if not ACTIVITY_FILE.exists():
            ACTIVITY_FILE.write_text(IDLE_ACTIVITY, encoding="utf-8")
        self._last_activity_file_text = IDLE_ACTIVITY

    def _render(self) -> None:
        frames = self._frames_for_state(self._state, self._is_walking)
        if not frames:
            self._sprite_label.setPixmap(QPixmap())
            self._sprite_label.setText(self._fallback_glyph)
            return

        pm = frames[self._frame_tick_idx % len(frames)]
        if not self._facing_right:
            pm = pm.transformed(QTransform().scale(-1, 1))

        self._sprite_label.setPixmap(pm)
        self._sprite_label.setText("")

    def _tick_frame_anim(self) -> None:
        """全局 sprite 帧推进——按 state 调速（idle 慢，jump 快），让动作有呼吸感。"""
        if self._is_walking:
            target_interval = FRAME_INTERVAL_MS_WALKING
        else:
            target_interval = FRAME_INTERVAL_MS_BY_STATE.get(self._state, FRAME_INTERVAL_MS_DEFAULT)

        if target_interval != self._current_frame_interval_ms:
            self._frame_anim_timer.setInterval(target_interval)
            self._current_frame_interval_ms = target_interval

        frames = self._frames_for_state(self._state, self._is_walking)
        if len(frames) > 1:
            self._frame_tick_idx += 1
            self._render()

    def _tick_walk(self) -> None:
        now = time.monotonic()
        if now < self._walk_paused_until:
            if self._is_walking:
                self._is_walking = False
                self._render()
            return

        if self._state in {"sleepy", "thinking"}:
            if self._is_walking:
                self._is_walking = False
                self._render()
            return

        if not self._is_walking:
            self._is_walking = True
            self._render()

        if random.random() < DIRECTION_CHANGE_PROB:
            self._direction = -self._direction
            self._facing_right = self._direction > 0
            self._render()

        speed = WALK_SPEED_PX
        if _is_night():
            speed = max(1, int(speed * NIGHT_SLOWDOWN))

        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = self.x() + self._direction * speed
        y = self.y()

        if x < screen.left():
            x = screen.left()
            self._direction = 1
            self._facing_right = True
            self._render()
        elif x + self.width() > screen.right():
            x = screen.right() - self.width()
            self._direction = -1
            self._facing_right = False
            self._render()

        self.move(x, y)
        self._save_position()
        self._reposition_bubble()

        if random.random() < 0.005:
            self._walk_paused_until = now + random.uniform(WALK_PAUSE_MIN_S, WALK_PAUSE_MAX_S)

    def _tick_poll_files(self) -> None:
        try:
            txt = STATE_FILE.read_text(encoding="utf-8").strip()
            if txt and txt != self._last_state_file_text:
                self._last_state_file_text = txt
                if txt in EXPRESSIONS:
                    self._on_state_change(txt, source="state")
        except Exception:
            pass

        # v0.1.2 兜底：state 卡住超过 STATE_STALE_SECONDS 自动回 idle
        # 防止 OPUS 设了 thinking/happy 后没人清，桌宠永远卡住一个动作
        if (
            self._state != DEFAULT_STATE
            and (time.time() - self._state_set_at) > STATE_STALE_SECONDS
        ):
            try:
                STATE_FILE.write_text(DEFAULT_STATE, encoding="utf-8")
            except Exception:
                pass
            self._last_state_file_text = DEFAULT_STATE
            self._on_state_change(DEFAULT_STATE, source="stale")

        # OPUS 脉搏 (wish-7330d23f): 从 activity.jsonl 读最新事件显示真实文字
        try:
            events = read_last_events(3)
            if events:
                latest = events[-1]
                ts = latest.get("ts", 0)
                desc = latest.get("desc", "")
                status = latest.get("status", "")
                if (
                    ts > self._last_pulse_ts
                    and desc
                    and self._state == DEFAULT_STATE
                ):
                    self._last_pulse_ts = ts
                    # 根据状态加前缀 emoji
                    prefix = {"start": "🔵", "end": "✅", "error": "🛑", "idle": "😴"}.get(status, "")
                    text = f"{prefix} {desc}" if prefix else desc
                    self._show_bubble(text, ACTIVITY_BUBBLE_HIDE_MS)
        except Exception:
            pass

    def _on_state_change(self, new_state: str, *, source: str) -> None:
        self._state = new_state
        self._state_set_at = time.time()  # v0.1.2 标记，便于 stale 检测
        if source != "stale":
            self._show_bubble(variants_for(new_state)[0])
        if new_state in {"happy", "greeting", "surprised"}:
            self._walk_paused_until = time.monotonic() + 1.5

    def _show_bubble(self, text: str, ms: int = BUBBLE_AUTO_HIDE_MS) -> None:
        # v0.1.1 bug fix：先把气泡 move 到正确位置再 show，否则 isVisible 检查
        # 在 OS 真正贴图前为 False 会导致 _reposition_bubble 提前 return
        bw_estimate = max(120, len(text) * 18)
        bx = self.x() + (self.width() - bw_estimate) // 2
        by = self.y() - 60
        self._bubble.move(bx, by)
        self._bubble.show_text(text, ms)
        self._reposition_bubble()

    def _reposition_bubble(self) -> None:
        # v0.1.1 移除 isVisible 守卫——拖动时即使气泡瞬时不可见也应该提前算位置
        bw = self._bubble.width()
        bh = self._bubble.height()
        bx = self.x() + (self.width() - bw) // 2
        by = self.y() - bh - 4
        self._bubble.move(bx, by)

    def _user_set_state(self, state: str) -> None:
        if state not in EXPRESSIONS:
            return
        try:
            STATE_FILE.write_text(state, encoding="utf-8")
            self._last_state_file_text = state
        except Exception:
            pass
        self._on_state_change(state, source="user")

    def _save_position(self) -> None:
        try:
            POSITION_FILE.write_text(f"{self.x()},{self.y()}", encoding="utf-8")
        except Exception:
            pass

    def _restore_position(self) -> None:
        try:
            if POSITION_FILE.exists():
                txt = POSITION_FILE.read_text(encoding="utf-8").strip()
                x, y = (int(v) for v in txt.split(","))
                self.move(x, y)
                return
        except Exception:
            pass
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 60, screen.bottom() - self.height() - 100)

    def _recenter(self) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(
            screen.center().x() - self.width() // 2,
            screen.bottom() - self.height() - 100,
        )
        self._save_position()

    def _about(self) -> None:
        msg = (
            "OPUS 桌宠 v0.1\n"
            "—— 情绪通道-001 + OPUS 心电图 ——\n\n"
            "操作：\n"
            "  鼠标左键拖动：移动\n"
            "  双击：弹快速命令框\n"
            "  右键：菜单（切表情/回中/退出）\n\n"
            "文件桥：\n"
            "  desktop_pet/state.txt    OPUS 主动情绪（set_emotion）\n"
            "  desktop_pet/activity.txt daemon 自动活动（工具调用）\n"
            "  desktop_pet/position.txt 位置记忆\n\n"
            "夜间模式：凌晨 2-5 点游走速度自动减慢"
        )
        dlg = QDialog(self)
        dlg.setWindowTitle("OPUS 桌宠 v0.1")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(msg))
        dlg.resize(420, 260)
        dlg.exec()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()
        elif e.button() == Qt.MouseButton.RightButton:
            self._menu.exec(e.globalPosition().toPoint())
            e.accept()

    def mouseMoveEvent(self, e) -> None:
        if self._drag_offset is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            new_pos = e.globalPosition().toPoint() - self._drag_offset
            self.move(new_pos)
            self._reposition_bubble()
            self._save_position()
            self._walk_paused_until = time.monotonic() + DRAG_PAUSE_S
            e.accept()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            e.accept()

    def mouseDoubleClickEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        text, ok = QInputDialog.getText(
            self, "对 OPUS 说一句", "（这会写到 desktop_pet/inbox.txt——daemon 端 v0.2 会读它）："
        )
        if ok and text.strip():
            inbox = PET_DIR / "inbox.txt"
            with inbox.open("a", encoding="utf-8") as f:
                f.write(text.strip() + "\n")
            self._show_bubble("(=^ω^=)φ_", BUBBLE_AUTO_HIDE_MS)


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    pet = OpusPet()
    pet.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
