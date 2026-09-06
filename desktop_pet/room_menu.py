"""右键菜单：对话 / 脉搏 / 锁定 / 大小滑块。"""

from __future__ import annotations

import os
import webbrowser
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QSlider,
    QWidget,
    QWidgetAction,
)

from desktop_pet.activities import read_last_events
from desktop_pet.clip_map import (
    PCT_MAX,
    PCT_MIN,
    load_lock,
    load_pct,
    save_lock,
    save_pct,
    size_for_pct,
)
from desktop_pet.room_dock import dock, expand, load_flip, save_flip
from desktop_pet.expressions import VALID_STATES

ROOT = Path(__file__).resolve().parent.parent


def apply_geom(pet) -> None:
    if getattr(pet, "_docked", False):
        from desktop_pet.room_dock import snap_dock
        snap_dock(pet)
        return
    w, h = size_for_pct(pet._pct)
    cx, cy = pet.x() + pet.width() // 2, pet.y() + pet.height() // 2
    pet.setFixedSize(w, h)
    pet.move(cx - w // 2, cy - h // 2)
    bub = getattr(pet, "_bubble", None)
    if bub is not None:
        bub.follow(pet)


def set_pct(pet, pct: int) -> None:
    pct = max(PCT_MIN, min(PCT_MAX, int(pct)))
    if pct == pet._pct:
        return
    pet._pct = pct
    save_pct(pct)
    if not getattr(pet, "_docked", False):
        apply_geom(pet)
    pet.update()
    if getattr(pet, "_pct_lab", None) is not None:
        pet._pct_lab.setText(f"{pct}")


def toggle_lock(pet, on: bool) -> None:
    pet._locked = bool(on)
    save_lock(pet._locked)


def open_chat() -> None:
    port = "7860"
    try:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("OPUS_API_PORT=") or line.startswith("PORT="):
                    port = line.split("=", 1)[1].strip() or port
                    break
    except Exception:
        pass
    port = os.environ.get("OPUS_API_PORT") or os.environ.get("PORT") or port
    webbrowser.open(f"http://127.0.0.1:{port}/companion/index.html")


def show_today(pet) -> None:
    if pet._bubble._sticky:
        return
    lines: list[str] = []
    for ev in reversed(read_last_events(8)):
        desc = (ev.get("desc") or "").strip()
        if not desc or desc in ("空闲",):
            continue
        if desc not in lines:
            lines.append(desc)
        if len(lines) >= 4:
            break
    pet._bubble.show_text(" · ".join(lines) or "这会儿还没干活", 8000)
    pet._bubble.follow(pet)


def build_menu(pet) -> QMenu:
    menu = QMenu(pet)
    chat = QAction("打开对话", pet)
    chat.triggered.connect(open_chat)
    menu.addAction(chat)
    today = QAction("今天干了啥", pet)
    today.triggered.connect(lambda: show_today(pet))
    menu.addAction(today)
    lock = QAction("锁定位置", pet)
    lock.setCheckable(True)
    lock.setChecked(load_lock())
    lock.toggled.connect(lambda on: toggle_lock(pet, on))
    menu.addAction(lock)
    dock_act = QAction("贴边", pet)
    dock_act.setCheckable(True)
    dock_act.setChecked(bool(getattr(pet, "_want_dock", False)))
    dock_act.toggled.connect(lambda on: _toggle_dock(pet, on))
    menu.addAction(dock_act)
    pet._dock_act = dock_act
    voice = menu.addMenu("语音唤醒")
    play = QAction("启用", pet)
    play.setCheckable(True)
    play.setChecked(bool(getattr(pet, "_play_on", False)))
    play.toggled.connect(lambda on: _toggle_play(pet, on))
    voice.addAction(play)
    pet._play_act = play
    think = QAction("思考", pet)
    think.setCheckable(True)
    think.setChecked(_load_think())
    think.toggled.connect(lambda on: _toggle_think(pet, on))
    voice.addAction(think)
    pet._think_act = think
    wake = QAction("设置唤醒词", pet)
    wake.triggered.connect(lambda: _edit_wake(pet))
    voice.addAction(wake)
    nxt = QAction("新开一轮对话", pet)
    nxt.triggered.connect(lambda: _new_round(pet))
    voice.addAction(nxt)
    flip = QAction("水平翻转", pet)
    flip.setCheckable(True)
    flip.setChecked(load_flip())
    flip.toggled.connect(lambda on: _toggle_flip(pet, on))
    menu.addAction(flip)
    size_menu = menu.addMenu("大小")
    box = QWidget(size_menu)
    lay = QHBoxLayout(box)
    lay.setContentsMargins(10, 4, 10, 4)
    sl = QSlider(Qt.Orientation.Horizontal, box)
    sl.setRange(PCT_MIN, PCT_MAX)
    sl.setValue(pet._pct)
    sl.setMinimumWidth(120)
    lab = QLabel(str(pet._pct), box)
    lab.setMinimumWidth(28)
    sl.valueChanged.connect(lambda n: set_pct(pet, n))
    lay.addWidget(sl)
    lay.addWidget(lab)
    act = QWidgetAction(size_menu)
    act.setDefaultWidget(box)
    size_menu.addAction(act)
    pet._pct_lab = lab
    st_menu = menu.addMenu("状态")
    for s in VALID_STATES:
        a = QAction(s, pet)
        a.triggered.connect(lambda _=False, st=s: pet._user_state(st))
        st_menu.addAction(a)
    quit_act = QAction("退出", pet)
    quit_act.triggered.connect(QApplication.instance().quit)
    menu.addAction(quit_act)
    return menu


def _edit_wake(pet) -> None:
    from desktop_pet.play_mode import load_wake, save_wake
    cur = load_wake()
    text, ok = QInputDialog.getText(pet, "唤醒词", "中文两三个字更好认：", text=cur)
    if not ok:
        return
    word = save_wake(text)
    bub = getattr(pet, "_bubble", None)
    if bub is not None:
        bub.show_text(f"以后叫「{word}」", 4000)
        bub.follow(pet)


def _new_round(pet) -> None:
    hook = getattr(pet, "_play", None)
    if hook is not None:
        hook.new_round()


def _load_think() -> bool:
    from desktop_pet.play_mode import load_think
    return load_think()


def _toggle_think(pet, on: bool) -> None:
    from desktop_pet.play_mode import save_think
    save_think(on)
    hook = getattr(pet, "_play", None)
    if hook is not None:
        hook.set_think(on)


def _toggle_play(pet, on: bool) -> None:
    hook = getattr(pet, "_play", None)
    if hook is not None:
        hook.enable(on)


def _toggle_dock(pet, on: bool) -> None:
    if on:
        dock(pet)
    else:
        expand(pet, keep_want=False)


def _toggle_flip(pet, on: bool) -> None:
    pet._flip = bool(on)
    save_flip(pet._flip)
    pet.update()
