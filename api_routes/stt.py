# api_routes/stt.py · 语音识别增强 whisper 安装/下载/状态 API (wish-241e0014)
# BRO 拍板: STT 是可选更新 · 只在设置页打开「语音识别增强 whisper」才装依赖+模型。
# 依赖 (pilk/faster-whisper) 走 requirements-stt.txt · 模型 (hf-mirror) 下载到 data/runtime/stt_models/。

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("opus.stt")

router = APIRouter(tags=["stt"])

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
STT_REQ = ROOT / "requirements-stt.txt"
ENV_PATH = ROOT / ".env"

# 安装锁: 同一时刻只允许一个 setup 在跑
_setup_lock = threading.Lock()
_setup_state = {"running": False, "step": "", "pid": None}


def _env_flag(name: str, default: str = "0") -> bool:
    """读 .env 里的开关 (启动预加载)"""
    try:
        if ENV_PATH.exists():
            for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().lower() in ("1", "true", "yes")
    except Exception:
        pass
    return default == "1"


def _write_env_flag(name: str, value: bool) -> None:
    """写 .env 开关 · 保留其他行"""
    try:
        val = "1" if value else "0"
        lines = []
        found = False
        if ENV_PATH.exists():
            lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines:
            if line.strip().startswith(name + "="):
                out.append(f"{name}={val}")
                found = True
            else:
                out.append(line)
        if not found:
            out.append(f"{name}={val}")
        ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    except Exception as e:
        logger.warning("写 .env 开关失败: %s", e)


def _venv_python() -> str:
    """选择 venv python (有 .venv 用它 · 没有用系统 python)"""
    if VENV_PY.exists():
        return str(VENV_PY)
    return sys.executable


def _pip_install_stt() -> bool:
    """pip 安装 STT 依赖 (pilk + faster-whisper) · 走清华源加速 · 真装。"""
    py = _venv_python()
    cmd = [py, "-m", "pip", "install", "--quiet", "-r", str(STT_REQ)]
    # 大陆加速: 清华源 (pip 默认源大陆慢)
    cmd += ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
    logger.info("STT 安装依赖: %s", " ".join(cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            logger.error("STT 依赖安装失败: %s", r.stderr[-500:])
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("STT 依赖安装超时 (10min)")
        return False
    except Exception as e:
        logger.error("STT 依赖安装异常: %s", e)
        return False


def _download_model(model_name: str) -> bool:
    """用 huggingface_hub 下载 faster-whisper 模型到本地 · 走 hf-mirror · 真下载。"""
    from workers import stt_transcribe
    local_dir = stt_transcribe.stt_models_dir() / model_name
    local_dir.mkdir(parents=True, exist_ok=True)
    if (local_dir / "model.bin").is_file():
        return True  # 已下载
    try:
        from huggingface_hub import snapshot_download
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        repo = f"Systran/faster-whisper-{model_name}"
        logger.info("STT 下载模型 %s → %s ...", repo, local_dir)
        snapshot_download(repo_id=repo, local_dir=str(local_dir))
        return (local_dir / "model.bin").is_file()
    except Exception as e:
        logger.error("STT 模型下载失败: %s", e)
        return False


@router.get("/stt/status")
def stt_status():
    """设置页状态聚合: 依赖/模型/就绪/启动预加载开关。"""
    from workers import stt_transcribe
    st = stt_transcribe.stt_status()
    st["boot_load"] = _env_flag("OPUS_STT_BOOT_LOAD")
    st["setup_running"] = _setup_state["running"]
    st["setup_step"] = _setup_state["step"]
    return st


class SttModelReq(BaseModel):
    model_name: str


@router.post("/stt/model")
def stt_set_model(req: SttModelReq):
    """设置页切换模型大小 (tiny/base/small) · 下次加载生效。"""
    from workers import stt_transcribe
    if req.model_name not in ("tiny", "base", "small"):
        raise HTTPException(400, f"模型大小只支持 tiny/base/small · 收到 {req.model_name}")
    stt_transcribe.set_model_name(req.model_name)
    return {"ok": True, "model_name": req.model_name}


class SttBootLoadReq(BaseModel):
    enabled: bool


@router.post("/stt/boot-load")
def stt_set_boot_load(req: SttBootLoadReq):
    """设置页「随 daemon 启动加载模型」开关 → .env OPUS_STT_BOOT_LOAD。"""
    _write_env_flag("OPUS_STT_BOOT_LOAD", req.enabled)
    return {"ok": True, "enabled": req.enabled}


@router.post("/stt/setup")
def stt_setup():
    """一键安装: ①pip 装依赖 ②下载模型。后台线程跑 · 前端轮询 /stt/status。

    安装锁: 同一时刻只允许一个 setup · 重复点返回 409。"""
    if _setup_lock.locked():
        raise HTTPException(409, "安装已在跑 · 请等待完成")
    if not _setup_lock.acquire(blocking=False):
        raise HTTPException(409, "安装已在跑 · 请等待完成")
    try:
        from workers import stt_transcribe
        model_name = stt_transcribe.get_model_name()

        def _worker():
            try:
                _setup_state["running"] = True
                _setup_state["step"] = "pip"
                ok_deps = _pip_install_stt()
                if not ok_deps:
                    _setup_state["step"] = "pip_failed"
                    logger.error("STT setup 依赖安装失败")
                    return
                _setup_state["step"] = "model"
                ok_model = _download_model(model_name)
                _setup_state["step"] = "model_failed" if not ok_model else "done"
            finally:
                _setup_state["running"] = False

        t = threading.Thread(target=_worker, name="stt-setup", daemon=True)
        t.start()
        return {"ok": True, "message": "安装已开始 · 轮询 /stt/status 看进度"}
    finally:
        _setup_lock.release()


@router.post("/stt/remove-model")
def stt_remove_model():
    """删除模型文件 (释放磁盘) · 依赖保留 · 可重新下载。"""
    import shutil
    from workers import stt_transcribe
    model_name = stt_transcribe.get_model_name()
    local_dir = stt_transcribe.stt_models_dir() / model_name
    if not local_dir.exists():
        return {"ok": True, "message": "模型目录不存在"}
    try:
        shutil.rmtree(local_dir)
        logger.info("STT 模型已删除: %s", local_dir)
        return {"ok": True, "message": f"模型 {model_name} 已删除"}
    except Exception as e:
        logger.error("STT 模型删除失败: %s", e)
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
