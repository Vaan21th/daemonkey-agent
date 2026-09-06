"""桌宠陪玩：叫到开门，她说完继续听，没人说话再退。跟陪伴语音对话同一套。"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from desktop_pet.play_audio import PlayEar, PlayMouth
from desktop_pet.play_bridge import ack_mp3, bye_mp3, chat, label_session, pcm_wav, stt_ready, tts_to, transcribe
from desktop_pet.play_mode import (
    clear_sid, identity_name, load_sid, load_think, load_wake, save_on, save_sid, save_think,
)
from desktop_pet.play_wake import (
    ACK, LISTEN, OFF, SPEAK, STANDBY, THINK, BYE_TEXT,
    heard_wake, is_echo, should_sit_idle, sitting_expired, on_ack_done, on_listen_end,
    on_speak_done, on_think_done, on_wake, strip_wake, wake_phrases,
)

ROOT = Path(__file__).resolve().parent.parent
TTS_MP3 = ROOT / "data" / "runtime" / "play_reply.mp3"


class PlayTalk(QObject):
    _ui = pyqtSignal(object)

    def __init__(self, pet) -> None:
        super().__init__(pet)
        self.pet = pet
        self.phase = OFF
        self.pending = ""
        self._sid = ""
        self._last_turn = 0.0
        self._spot_busy = False
        self._ignore_wake_ms = 0
        self._miss_cool = 0.0
        self._leaving = False
        self._think_on = load_think()
        self._sit_since = 0.0
        self._ui.connect(lambda fn: fn())
        self.ear = PlayEar(pet)
        self.ear.need_spot.connect(self._spot)
        self.ear.need_utter.connect(self._utter)
        self.ear.need_idle.connect(self._listen_idle)
        self.ear.died.connect(self._mic_died)
        self.mouth = PlayMouth(pet)
        self._cool = QTimer(pet)
        self._cool.setInterval(200)
        self._cool.timeout.connect(self._tick_cool)

    def enable(self, on: bool, *, fresh: bool = True) -> None:
        save_on(on)
        self.pet._play_on = on
        if not on:
            self._halt()
            self._sid = ""
            self._last_turn = 0.0
            clear_sid()
            self._say("", 0)
            return
        miss = stt_ready()
        if miss:
            self._fail(miss, 7000)
            return
        err = self.ear.start()
        if err:
            self._fail(err)
            return
        self._cool.start()
        word = load_wake()
        if fresh:
            self._sid = ""
            self._last_turn = 0.0
            clear_sid()
        else:
            self._sid = load_sid()
        self._standby(f"语音唤醒开了 · 叫「{word}」或点我", 4500)

    def set_think(self, on: bool) -> None:
        self._think_on = bool(on)
        save_think(self._think_on)
        self._say("思考开了" if self._think_on else "思考关了，只说话", 3500)

    def tap(self) -> None:
        if not getattr(self.pet, "_play_on", False):
            return
        if self.phase == LISTEN:
            pcm = bytes(self.ear._utter)
            self.ear.set_mode("spot")
            self._utter(pcm)
            return
        if self.phase in (STANDBY, SPEAK):
            self._enter_wake("")

    def _fail(self, msg: str, ms: int = 6000) -> None:
        self.phase = OFF
        self.pet._play_on = False
        save_on(False)
        self._sync_menu(False)
        self._say(msg, ms)

    def _halt(self) -> None:
        self.phase = OFF
        self.pending = ""
        self.ear.stop()
        self.mouth.stop()
        self._cool.stop()

    def _mic_died(self, msg: str) -> None:
        self._halt()
        self._fail(msg or "麦克风断了")

    def _sync_menu(self, on: bool) -> None:
        act = getattr(self.pet, "_play_act", None)
        if act is None:
            return
        act.blockSignals(True)
        act.setChecked(on)
        act.blockSignals(False)

    def _say(self, text: str, ms: int = 0) -> None:
        bub = getattr(self.pet, "_bubble", None)
        if bub is None:
            return
        if text:
            bub.show_text(text, ms)
            bub.follow(self.pet)
        elif not bub._sticky:
            bub.hide()

    def _tick_cool(self) -> None:
        if self._ignore_wake_ms > 0:
            self._ignore_wake_ms = max(0, self._ignore_wake_ms - 200)
        if should_sit_idle(self.phase, self._sit_since, time.monotonic(), self.ear.capturing()):
            self._listen_idle()

    def _mood(self, state: str) -> None:
        fn = getattr(self.pet, "_play_state", None)
        if fn is not None:
            fn(state)

    def _q(self, fn) -> None:
        self._ui.emit(fn)

    def _standby(self, text: str = "", ms: int = 0, deaf_ms: int = 1800) -> None:
        self.phase = STANDBY
        self.pending = ""
        self._leaving = False
        self._sit_since = 0.0
        self.ear.set_mode("spot")
        self._ignore_wake_ms = max(self._ignore_wake_ms, deaf_ms)
        self._mood("idle")
        self._say(text, ms)

    def _listen(self, text: str = "在听", deaf_ms: int = 900, reset_idle: bool = False) -> None:
        self.phase = LISTEN
        self.pending = ""
        self._leaving = False
        if reset_idle or self._sit_since <= 0:
            self._sit_since = time.monotonic()
        self.ear.set_mode("listen", deaf_ms=deaf_ms)
        self._say(text, 0)

    def _spot(self, pcm: bytes) -> None:
        if self.phase != STANDBY or self._spot_busy:
            return
        if self._ignore_wake_ms > 0:
            return
        self._spot_busy = True

        def work() -> None:
            try:
                word = load_wake()
                text = transcribe(pcm_wav(pcm), timeout=20, spot=True)
                phrases = wake_phrases(word, identity_name())
                if heard_wake(text, phrases):
                    rem = strip_wake(text, phrases)
                    if is_echo(rem):
                        rem = ""
                    self._q(lambda: self._enter_wake(rem))
                elif text:
                    self._q(lambda t=text: self._miss(t))
            finally:
                self._q(lambda: setattr(self, "_spot_busy", False))

        threading.Thread(target=work, daemon=True, name="play-spot").start()

    def _miss(self, text: str) -> None:
        now = time.monotonic()
        if now - self._miss_cool < 6:
            return
        self._miss_cool = now
        heard = (text or "").strip()
        if len(heard) > 16:
            heard = heard[:16] + "…"
        self._say(f"听到「{heard}」· 没对上「{load_wake()}」", 4000)

    def _enter_wake(self, remainder: str) -> None:
        nxt, pending = on_wake(self.phase, remainder)
        if nxt != ACK:
            return
        if self.phase == SPEAK:
            self.mouth.stop()
        self.phase = ACK
        self.pending = pending
        self._ignore_wake_ms = 2200
        self.ear.set_mode("mute")
        self._say("我在", 2500)
        path = ack_mp3()
        if path is None:
            QTimer.singleShot(350, self._after_ack)
            return
        self.mouth.play(path, lambda: QTimer.singleShot(350, self._after_ack))

    def _after_ack(self) -> None:
        if self.phase != ACK:
            return
        nxt = on_ack_done(self.pending)
        self.phase = nxt
        if nxt == THINK:
            msg = self.pending
            self.pending = ""
            self._think(msg)
            return
        self._listen(reset_idle=True)

    def _listen_idle(self) -> None:
        if self.phase != LISTEN:
            return
        self._sit_since = 0.0
        self.ear.set_mode("mute")
        self._leaving = True
        self._say(BYE_TEXT, 4000)
        path = bye_mp3()
        if path is None:
            self._standby(BYE_TEXT, 4000)
            return
        self.phase = SPEAK
        self._ignore_wake_ms = 1200
        self.mouth.play(path, self._spoken)

    def _utter(self, pcm: bytes) -> None:
        if self.phase != LISTEN:
            return
        self.ear.set_mode("mute")
        if len(pcm) < 1600:
            self._listen()
            return
        self.phase = THINK
        if self._think_on:
            self._mood("thinking")
            self._say("在想", 0)

        def work() -> None:
            text = transcribe(pcm_wav(pcm), timeout=45)
            self._q(lambda: self._heard(text))

        threading.Thread(target=work, daemon=True, name="play-utter").start()

    def _heard(self, text: str) -> None:
        if self.phase != THINK:
            return
        nxt = on_listen_end(text)
        if nxt != THINK:
            self._listen()
            return
        self._think(text)

    def _think(self, text: str) -> None:
        self.phase = THINK
        self.ear.set_mode("mute")
        if self._think_on:
            self._mood("thinking")
            self._say("在想", 0)
        if sitting_expired(self._last_turn, time.time()):
            self._sid = ""
            clear_sid()

        def work() -> None:
            reply, new_sid, err, face = chat(text, self._sid, think=self._think_on)
            self._q(lambda: self._replied(reply, err, new_sid, face))

        threading.Thread(target=work, daemon=True, name="play-chat").start()

    def _replied(self, reply: str, err: str, new_sid: str = "", face: str = "") -> None:
        if new_sid:
            born = self._sid != new_sid
            self._sid = new_sid
            save_sid(new_sid)
            self._last_turn = time.time()
            if born:
                label_session(new_sid)
        if self.phase != THINK:
            return
        if err and not reply:
            self._listen(err, deaf_ms=400, reset_idle=True)
            return
        nxt = on_think_done(reply)
        if nxt != SPEAK:
            self._listen(reset_idle=True)
            return
        self.phase = SPEAK
        self.ear.set_mode("mute")
        if face:
            self._mood(face)
        shown = reply if len(reply) <= 42 else reply[:40] + "…"
        self._say(shown, 0)

        def work() -> None:
            terr = tts_to(reply, TTS_MP3)
            self._q(lambda: self._speak(terr))

        threading.Thread(target=work, daemon=True, name="play-tts").start()

    def _speak(self, terr: str) -> None:
        if self.phase != SPEAK:
            return
        if terr or not TTS_MP3.is_file():
            if self._leaving:
                self._standby(terr, 5000 if terr else 0)
            else:
                self._listen(terr or "在听", reset_idle=True)
            return
        self.mouth.play(TTS_MP3, self._spoken)

    def _spoken(self) -> None:
        if self.phase != SPEAK:
            return
        if self._leaving:
            self._standby()
            return
        self._listen(deaf_ms=1100, reset_idle=True)

    def new_round(self) -> None:
        self._sid = ""
        self._last_turn = 0.0
        clear_sid()
        self._say("这一轮清掉了 · 下一句起新对话", 4000)
