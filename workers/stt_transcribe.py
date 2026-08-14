# workers/stt_transcribe.py · 微信语音转写 (墨言 094-2 移植 · wish-241e0014 · 设置页开关驱动)

# =====================================================================

# 链路: .silk → pilk.silk_to_wav → faster-whisper 转写 → 文本

# 参数对齐 Hermes tools/transcription_tools.py build_local_transcribe_kwargs:

#   beam_size=5 · condition_on_previous_text=False (防幻觉自强化) · vad_filter=True

#   vad min_silence_duration_ms=500 · no_speech_threshold=0.6 · log_prob_threshold=-1.0

#   幻觉后过滤: no_speech_prob>0.6 AND avg_logprob<-1.0 → 丢弃段

# 模型懒加载 + 全局缓存

# 失败返回 "" · 调用方降级提示 · 不阻塞消息流程

# ---------------------------------------------------------------------

# BRO 拍板 (wish-241e0014): STT 是可选更新 · 只在设置页打开「语音识别增强 whisper」
# 才装依赖 + 下载模型 · 不需要的用户零负担。 本文件只负责"已装好后的转写" ·
# 安装/下载/状态管理走 api_routes/stt.py + 设置页 UI。

import logging
import os
import tempfile
import threading
from pathlib import Path

# 模型从 HF 下载 · 大陆直连慢 + xet 被墙 → 强制 hf-mirror + 禁用 xet (08-14 实测 · setdefault 会被系统代理顶掉 → 直接赋值)
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_DISABLE_XET"] = "1"

logger = logging.getLogger("opus.stt")

# 模型名: tiny (~75MB) / base (~150MB) / small (~460MB) · 可在设置页选
_MODEL_NAME = os.environ.get("STT_WHISPER_MODEL", "small")

# 依赖缺省判定 (给设置页状态显示 + 安装触发用)
STT_DEPS = ("pilk", "faster_whisper")


def stt_models_dir() -> Path:
    """模型本地目录: data/runtime/stt_models/<model_name>/"""
    return Path(__file__).resolve().parent.parent / "data" / "runtime" / "stt_models"


def get_model_name() -> str:
    return _MODEL_NAME


def set_model_name(name: str) -> None:
    """设置页切换模型大小 (tiny/base/small) · 下次加载生效"""
    global _MODEL_NAME
    valid = {"tiny", "base", "small"}
    if name in valid:
        _MODEL_NAME = name


def deps_installed() -> bool:
    """检查 STT 依赖是否已装 (pilk + faster_whisper)。设置页状态显示用。"""
    try:
        import importlib
        for d in STT_DEPS:
            if importlib.util.find_spec(d) is None:
                return False
        return True
    except Exception:
        return False


def model_downloaded() -> bool:
    """检查当前模型是否已下载到本地。设置页状态显示用。"""
    return (stt_models_dir() / _MODEL_NAME / "model.bin").is_file()


def stt_status() -> dict:
    """设置页状态聚合: {deps, model, ready} · 前端开关/进度条用。"""
    deps = deps_installed()
    model = model_downloaded()
    return {
        "deps_installed": deps,
        "model_name": _MODEL_NAME,
        "model_downloaded": model,
        "ready": deps and model,
        "model_dir": str(stt_models_dir() / _MODEL_NAME),
        "expected_size_mb": {"tiny": 75, "base": 150, "small": 460}.get(_MODEL_NAME, 150),
    }


_model = None
_model_lock = threading.Lock()


def _load_model():
    """懒加载 + 双检锁 · 并发语音消息不重复加载模型 (Hermes #24767 同款)。

    只读本地预下载目录 · 缺 model.bin 返回 None 不触发在线下载 (review P1-2:
    同步消息路径静默下载 150MB 会卡死 getupdates 轮询 · 模型下载交给设置页显式下载)。"""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                local_dir = stt_models_dir() / _MODEL_NAME
                model_src = str(local_dir) if (local_dir / "model.bin").is_file() else None
                if not model_src:
                    logger.warning(
                        "本地无 whisper 模型 %s/model.bin · STT 降级不可用 (去设置页下载可启用)",
                        local_dir,
                    )
                    return None
                try:
                    from faster_whisper import WhisperModel
                    logger.info("加载 faster-whisper 模型 '%s' (src=%s)...", _MODEL_NAME, model_src)
                    _model = WhisperModel(model_src, device="cpu", compute_type="int8")
                except Exception as e:
                    logger.warning("faster-whisper 模型加载失败: %s", e)
                    return None
    return _model


def _is_hallucinated_segment(seg, no_speech_threshold: float = 0.6, logprob_threshold: float = -1.0) -> bool:
    """保守 AND 闸门 (Hermes _is_hallucinated_segment 同款): 高 no_speech + 低置信 → 静音幻觉。

    quiet-but-real speech 只满足一个条件 → 存活。"""
    no_speech_prob = getattr(seg, "no_speech_prob", None)
    avg_logprob = getattr(seg, "avg_logprob", None)
    if no_speech_prob is None or avg_logprob is None:
        return False
    try:
        return float(no_speech_prob) > no_speech_threshold and float(avg_logprob) < logprob_threshold
    except (TypeError, ValueError):
        return False


def transcribe_silk(silk_path: str, timeout: float = 120) -> str:
    """silk → wav → whisper 转写。失败/超时返回 ""（调用方降级提示）。

    真超时: 模型加载 + 转写放线程跑 · join(timeout) 超时返回 "" (review P1-2)。"""
    silk = Path(silk_path)
    if not silk.is_file() or silk.stat().st_size == 0:
        logger.warning("silk 文件不存在或为空: %s", silk_path)
        return ""

    result: dict = {}

    def _work() -> None:
        try:
            import pilk
            with tempfile.TemporaryDirectory(prefix="wechat-silk-") as td:
                wav = os.path.join(td, silk.stem + ".wav")
                pilk.silk_to_wav(str(silk), wav)
                if not Path(wav).is_file() or Path(wav).stat().st_size == 0:
                    result["error"] = f"pilk 转 wav 失败: {silk_path}"
                    return
                model = _load_model()
                if model is None:
                    result["error"] = "whisper 模型不可用 (本地缺 model.bin)"
                    return
                segments, _info = model.transcribe(
                    wav,
                    beam_size=5,
                    condition_on_previous_text=False,  # 防幻觉自强化
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 500},
                    no_speech_threshold=0.6,
                    log_prob_threshold=-1.0,
                )
                parts = []
                for seg in segments:
                    if _is_hallucinated_segment(seg):
                        continue
                    t = (seg.text or "").strip()
                    if t:
                        parts.append(t)
                result["text"] = " ".join(parts).strip()
        except ImportError:
            result["error"] = "STT 依赖未安装 (pilk/faster-whisper) · 去设置页打开语音识别增强"
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=_work, name="stt-transcribe", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        logger.warning("语音转写超时 (>%ss) · 降级", timeout)
        return ""
    if "error" in result:
        logger.warning("语音转写失败: %s", result["error"])
        return ""
    return result.get("text", "")
