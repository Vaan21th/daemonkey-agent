"""
workers · 工作室后台 worker 集合

每个 worker 是一个能被 daemon_api 调用、也能被 CLI 单跑的模块。
轻量 · 同步 · 写本地 JSON / SQLite 当数据落地 · 不引入 redis / celery 等重设施。

注册的 worker:
  - info_radar    · 多源 AI 资讯聚合（Day 2 起手）
"""
