"""api_routes/radar_settings.py · 掘金雷达 自动刷新配置 (wish-7f38376e)

GET  /radar-config  · 读配置 + 当前调度状态（上次刷新 / 下次刷新 / 上轮抓到多少条）
POST /radar-config  · 写配置（enabled / interval_min）
                      scheduler 线程每 10s 热读一次 · 改完立刻生效·不用重启
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Header

from api_routes._deps import check_auth

router = APIRouter()


def _runtime_snapshot() -> dict:
    """调度线程的实时状态（给设置页显示「上次 … · 下次 …」）。"""
    try:
        from workers.scheduler import get_scheduler_state

        st = get_scheduler_state()
    except Exception:
        return {}
    return {
        "enabled": st.get("enabled", True),
        "last_run_at": st.get("last_run_at"),
        "next_run_at": st.get("next_run_at"),
        "last_run_ok": st.get("last_run_ok"),
        "last_run_items": st.get("last_run_items"),
        "runs_completed": st.get("runs_completed", 0),
        "interval_min": st.get("interval_min", 0),
        "running": bool(st.get("enabled", True)),
    }


@router.get("/radar-config")
async def get_radar_config(authorization: Optional[str] = Header(None)):
    """读雷达自动刷新配置 + 实时状态。"""
    check_auth(authorization)
    from workers.radar_config import load_radar_config

    return {"config": load_radar_config(), "runtime": _runtime_snapshot()}


@router.post("/radar-config")
async def set_radar_config(
    payload: dict = Body(...),
    authorization: Optional[str] = Header(None),
):
    """写配置。只收已知字段（enabled / interval_min）。"""
    check_auth(authorization)
    from workers.radar_config import save_radar_config

    merged = save_radar_config(payload or {})
    if merged.get("enabled"):
        note = "已开启 · 后台会按新频率抓取（最多 10 秒内生效）"
    else:
        note = "已关闭 · 后台不再自动抓取（手动「抓一下雷达」仍然可用）"
    return {"saved": True, "config": merged, "runtime": _runtime_snapshot(), "note": note}
