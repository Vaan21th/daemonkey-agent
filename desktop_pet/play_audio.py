"""陪玩耳朵：Qt 开麦。待机只攒短窗，开口才录整句。"""

from __future__ import annotations

import math
import struct

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtMultimedia import (
    QAudioFormat,
    QAudioSource,
    QMediaDevices,
    QMediaPlayer,
    QAudioOutput,
)
from PyQt6.QtCore import QUrl

RATE = 16000
RING_MS = 2400
POLL_MS = 50
SPEECH_RMS = 0.018
SPOT_HOLD_MS = 180
SILENCE_MS = 1000
MIN_UTTER_MS = 400
MAX_UTTER_MS = 8000
SPOT_COOL_MS = 1100
SWITCH_DEAF_MS = 600
LISTEN_IDLE_MS = 8000


def _rms(pcm: bytes) -> float:
    if len(pcm) < 4:
        return 0.0
    n = len(pcm) // 2
    samples = struct.unpack("<" + "h" * n, pcm[: n * 2])
    acc = 0.0
    for s in samples:
        acc += s * s
    return math.sqrt(acc / n) / 32768.0


class PlayEar(QObject):
    need_spot = pyqtSignal(bytes)
    need_utter = pyqtSignal(bytes)
    need_idle = pyqtSignal()
    died = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.mode = "spot"
        self._src: QAudioSource | None = None
        self._io = None
        self._ring = bytearray()
        self._utter = bytearray()
        self._hot_ms = 0
        self._quiet_ms = 0
        self._utter_ms = 0
        self._voiced = False
        self._cool_ms = 0
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._tick)

    def start(self) -> str:
        self.stop()
        try:
            dev = QMediaDevices.defaultAudioInput()
            if dev.isNull():
                return "没找到麦克风"
            fmt = QAudioFormat()
            fmt.setSampleRate(RATE)
            fmt.setChannelCount(1)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            self._src = QAudioSource(dev, fmt, self)
            self._io = self._src.start()
            if self._io is None:
                return "麦克风打不开"
        except Exception as e:
            return f"麦克风打不开 ({type(e).__name__})"
        self._ring.clear()
        self._utter.clear()
        self._hot_ms = self._quiet_ms = self._utter_ms = 0
        self._voiced = False
        self._cool_ms = 0
        self._poll.start(POLL_MS)
        return ""

    def stop(self) -> None:
        self._poll.stop()
        if self._src is not None:
            try:
                self._src.stop()
            except Exception:
                pass
        self._src = None
        self._io = None

    def capturing(self) -> bool:
        return self.mode == "listen" and bool(self._voiced)

    def set_mode(self, mode: str, deaf_ms: int | None = None) -> None:
        self.mode = mode
        self._ring.clear()
        self._hot_ms = 0
        self._cool_ms = SWITCH_DEAF_MS if deaf_ms is None else max(0, int(deaf_ms))
        self._utter.clear()
        self._utter_ms = 0
        self._voiced = False
        self._quiet_ms = 0

    def _tick(self) -> None:
        if self._io is None:
            return
        try:
            chunk = bytes(self._io.readAll())
        except Exception:
            self.died.emit("麦克风断了")
            self.stop()
            return
        if not chunk:
            return
        self._cool_ms = max(0, self._cool_ms - POLL_MS)
        self._ring.extend(chunk)
        cap = RATE * 2 * RING_MS // 1000
        if len(self._ring) > cap:
            del self._ring[: len(self._ring) - cap]
        rms = _rms(chunk[-4096:] if len(chunk) > 4096 else chunk)
        loud = rms >= SPEECH_RMS
        if self.mode == "mute":
            return
        if self.mode == "listen":
            if self._cool_ms > 0:
                return
            self._utter.extend(chunk)
            self._utter_ms += POLL_MS
            if loud:
                self._voiced = True
                self._quiet_ms = 0
            elif self._voiced:
                self._quiet_ms += POLL_MS
            if not self._voiced and self._utter_ms >= LISTEN_IDLE_MS:
                self._utter.clear()
                self._utter_ms = 0
                self.need_idle.emit()
                return
            if (self._voiced and self._quiet_ms >= SILENCE_MS and self._utter_ms >= MIN_UTTER_MS) or (
                self._utter_ms >= MAX_UTTER_MS
            ):
                pcm = bytes(self._utter)
                self._utter.clear()
                self._utter_ms = 0
                self._voiced = False
                self._quiet_ms = 0
                self.need_utter.emit(pcm)
            return
        if self.mode != "spot":
            return
        if loud:
            self._hot_ms += POLL_MS
        else:
            self._hot_ms = 0
        if self._hot_ms >= SPOT_HOLD_MS and self._cool_ms == 0 and len(self._ring) > RATE:
            self._cool_ms = SPOT_COOL_MS
            self._hot_ms = 0
            self.need_spot.emit(bytes(self._ring))


def playback_over(status) -> bool:
    name = getattr(status, "name", str(status))
    return name in {"EndOfMedia", "InvalidMedia", "NoMedia"}


class PlayMouth:
    """TTS 播放。停 = 打断。失败也要收尾，不能卡在 ACK/SPEAK。"""

    def __init__(self, parent) -> None:
        self._player: QMediaPlayer | None = None
        self._out: QAudioOutput | None = None
        self._on_done = None
        self._parent = parent

    def play(self, path, on_done) -> None:
        self.stop()
        self._on_done = on_done
        player = QMediaPlayer(self._parent)
        out = QAudioOutput(self._parent)
        out.setVolume(1.0)
        player.setAudioOutput(out)
        player.mediaStatusChanged.connect(self._status)
        player.errorOccurred.connect(self._failed)
        player.setSource(QUrl.fromLocalFile(str(path)))
        self._player = player
        self._out = out
        player.play()

    def _finish(self) -> None:
        cb = self._on_done
        self._on_done = None
        if cb:
            cb()

    def _status(self, status) -> None:
        if playback_over(status):
            self._finish()

    def _failed(self, *_a) -> None:
        self._finish()

    def stop(self) -> None:
        self._on_done = None
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:
                pass
        self._player = None
        self._out = None
