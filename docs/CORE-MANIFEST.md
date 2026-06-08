# Daemonkey 内核清单 (core manifest) · 草案

> **选择性更新机制的地基。** 中心库 (Gitee) 只同步「内核层 / L1」里的文件;
> **清单外的一律物理不碰**——用户的功能 (L2)、应用与灵魂 (L3) 永不被覆盖。
>
> 原则: **L1 = 让「写代码安全」+「daemon 稳定」的底层机制。改一处全员受益,用户不该 fork。**
> 清单可演进。撞到用户改过的 L1 文件时,更新流程会弹出来让人决定,绝不无声覆盖。
>
> *草案 · 卷六十四续五 · 2026-06-08 · 待 BRO 圈定*

---

## L1 内核 · 铁定纳入 (高置信)

### 1. 写文件 / 编辑安全
- `agent_tools/edit_file.py` — 编辑文件 (唯一命中 + 回读回滚)
- `agent_tools/write_file.py` — 写文件 (指纹防覆盖)
- `agent_tools/_edit_lock.py` — 并发软锁 (今天新增)
- `agent_tools/_git_lock.py` — daemon 单例 git 锁
- `agent_tools/_subprocess_helper.py` — 子进程辅助 (no-window)
- `workers/safe_write.py` — 原子安全写
- `workers/edit_selfcheck.py` — 编辑后自检
- `workers/schema_guard.py` — 工具入参 schema 守卫
- `workers/secret_redactor.py` — 密钥脱敏

### 2. 代码读 / 搜索 / 执行
- `agent_tools/read_file.py` · `outline_file.py` · `glob_files.py`
- `agent_tools/grep_files.py` · `search_code.py` · `lint_check.py`
- `agent_tools/python_exec.py` · `shell_exec.py`

### 3. git 纪律 / 上线安全闸
- `workers/git_ops.py` — checkpoint / 分支 / 合主干 / last-good
- `workers/worktree_state.py` · `agent_tools/worktree_status.py`
- `workers/verify_gate.py` — 合主干前的上线闸
- `workers/frontend_check.py` — 前端 JS 自检
- `workers/boot_health.py` — 启动自检 + 自动回退 last-good
- `agent_tools/verify_daemon_endpoints.py` — 全路由 smoke
- `tools/install_hooks.ps1` + `tools/git-hooks/*` — pre-commit 钩子

### 4. daemon 生命周期 / 启动 / 续场 / 救命
- `workers/daemon_lifecycle.py` — pid 锁 / crash 检测 / safe_mode 熔断
- `workers/resume_runner.py` — 重启续场
- `agent_tools/request_restart.py` — 重启请求
- `workers/session_repair.py` — 会话修复
- `tools/run_api_only.py` — 启动入口
- `tools/repair_console.py` — daemon 崩了时的救命通道
- `workers/env_reloader.py` — .env 热载 + 容错读取 (今天加固)

### 5. 运行护栏 / 可观测
- `workers/opus_logging.py` — 统一日志
- `workers/audit_logger.py` — 审计日志
- `workers/rate_limiter.py` — 限流
- `workers/token_budget_guard.py` — token 预算闸
- `workers/net_client.py` — 网络客户端基础

### 6. 身份本地化机制 (归一地基)
- `identity.py` — ai_name / owner_name / localize 出口本地化

---

## 边界文件 · 已圈定 (2026-06-08 BRO 拍板: 全按建议)

> 决议: `tool_loop` / `soul_loader` / `api_routes(core+_deps+__init__)` / `daemon_runtime` / `daemon_session` / `scheduler` / `model_aliases` / `provider_presets` **纳入**;
> `daemon_api.py`(混功能路由) 与 `provider_configs.py`(含 key) **不纳入**。
> 机器清单已落地 `core_manifest.json`。

| 文件 | 纠结点 | 决议 |
|---|---|---|
| `daemon_api.py` | API 骨架 (鉴权/生命周期) **混着一堆功能路由**在一个大文件里 | **暂不纳入**——同步它会连功能路由一起盖掉用户的改动。长期应拆「core 骨架」出来再纳入 |
| `tool_loop.py` | LLM 工具循环核心 (纯基础设施) | **纳入** |
| `soul_loader.py` | 加载「机制」是内核,加载的「内容」是 L3 灵魂 | **纳入**(它只读不写灵魂数据,机制改进该共享) |
| `api_routes/core.py` · `_deps.py` · `__init__.py` | 路由基础设施 (静态服务/鉴权依赖) | **纳入** |
| `daemon_runtime.py` · `daemon_session.py` | RUNTIME / 会话核心 | **纳入** |
| `workers/scheduler.py` | 后台调度框架 | **纳入** |
| `model_aliases.py` · `provider_presets.py` | provider 机制 (不含 key) | **纳入**;`provider_configs.py` **不纳入** (含 key = 数据) |

---

## 明确不同步 (清单外 · 用户自管 · 永不覆盖)

- **L2 功能**: 雷达 / 掘金 / 可行性 / 复盘 / 能力镜像 / 报告引擎 / 心愿单 / 工坊应用 / 工作流 / 微信·iLink 渠道 / 视觉 / 日历 / dashboard —— 所有这些 `workers/*` + `agent_tools/*` + `api_routes/*` 功能件
- **前端 UI**: `static/*` (用户最爱改的一层)
- **L3 私人数据**: `soul/` · `data/` · `sessions/` (本就 gitignore / 私人,git 都不碰)

---

## 待办

1. ✅ BRO 圈定「边界文件」→ 白名单落定
2. ✅ 白名单转机器可读 `core_manifest.json`
3. ⬜ 建中心库 (支持 **Gitee + GitHub 双源**;真相源唯一=母体,下游只拉不推) — 配 remote + 首次 push 干净 Daemonkey
4. ⬜ 写 `update_core` 工具: `git fetch` → 按白名单算 diff → 预览给用户 → 只覆盖白名单文件 → 自检 + 失败回滚 (预留多源口子: 可指定从哪个 remote 拉)
5. ⬜ 包成对话工具 (用户说「看下更新」即可)
