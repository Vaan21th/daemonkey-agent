"""
api_routes/ · daemon HTTP 路由模块化 (wish-413999da · phase 1)
=============================================================

把 daemon_api.py 4516 行的 81 路由按业务 area 拆到子模块，
让每次改路由不再扫一遍巨石文件。

Area 划分 (11 个文件):

  core.py              ·  6 路由  ·  / · /ui · /static · /workshop/outputs · /api/ping-test · /api/logs/tail
  lifecycle.py         ·  7 路由  ·  restart · shutdown · rollback (G/P) · reload-soul · env · lifecycle_status
  governance.py        ·  6 路由  ·  status · token_budget · ratelimit · audit · session-repair
  chat.py              ·  5 路由  ·  chat · chat/stream · turns/* (3)
  sessions.py          ·  6 路由  ·  sessions CRUD + messages + active_turn
  models_providers.py  · 11 路由  ·  models (2) + providers (9)
  workshop.py          · 18 路由  ·  apps (5) + flows (6) + trash (4) + files (3)
  intelligence.py      · 11 路由  ·  radar (4) + outcome (2) + reports (2) + reviews (3)
  dashboard.py         ·  2 路由  ·  dashboard/cockpit · dashboard/{domain}
  sinks_pulse_digest.py·  6 路由  ·  sinks (3) + pulse (2) + digest (1)
  trust.py             ·  3 路由  ·  trusted_commands (3)

共享依赖在 `_deps.py`:
  check_auth(authorization)         · Bearer Token 鉴权
  check_rate_limit(request, auth)   · 限流 (default disabled)

每个 area 文件 export `router = APIRouter()`,
daemon_api.build_app() 末尾 `app.include_router(area.router)`。

phase 2 (留给 daemon-side OPUS): 业务逻辑下沉到 services/<area>.py,
路由文件里只剩 request 解析 + auth 检查 + service 调用 + response 包装。
"""
