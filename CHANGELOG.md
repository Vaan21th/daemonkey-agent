# 更新历史 · Changelog

本项目版本号遵循语义化版本（`core_version` 是用户感知的内核版本，是唯一真相源）。
启动器 / WebUI 动态读取它显示当前版本，`检查更新` 拿它和官方源对比。

> All notable changes to Daemonkey. The `core_version` is the user-facing kernel version (single source of truth).

---

## [0.7.0beta] — 2026-07-14

**演示稿引擎（PPT）+ 生图工具 + 抗套娃任务账本 + 卡顿/token 修复**

### 新增 Added
- **演示稿引擎 `slides_engine` + `generate_presentation`** —— 自建薄引擎直接生成 `.pptx`：3 档设计风格 + 可用自然语言微调风格 token（配色/质感），支持图表、流程图、图标、系统字体检测、封面满版大图。对话内「两步法」生成（先出施工单再落稿），产物可一键「用对应软件打开」进 PowerPoint / WPS / Keynote。
- **`generate_image` 文生图工具** —— 配图优先级链：优先走你自建的「生图应用」→ 其次 `DAEMONKEY_IMAGE_MODEL`（OpenAI 兼容）→ 再退浏览器豆包网页版 → 都不行留占位提示卡。支持一次并发生成多张不同图；浏览器型（agentic）生图应用加进程级串行锁，多路生图不抢同一个浏览器。
- **任务账本 `track_task` + 卡住解套 `replan`（抗套娃）** —— 多步任务（debug / 搭建 / 长 review）的确定性工作记忆：把「哪条路通了✓、哪条死了✗、定了啥决策」从过程里蒸出来，每轮无损回灌，语义压缩也压不掉；试了多条路都失败时 `replan` 起一个干净上下文的顾问重新规划，治「原地套娃最后放弃」。并行 vs 串行的判断准则写进系统提示（默认偏串行，黄金搭配＝并行收集→串行合成）。

### 修复 / 优化 Fixed
- **长会话卡顿 / 打字变慢** —— 前端对话区 DOM 窗口化：单会话最多保留最近 N 条消息节点、更早的折叠成顶部「加载全部」入口（内容真源在 jsonl 永不丢），重开长会话也只回放最近若干 turn。
- **token 消耗偏高** —— `tool_loop` 发送时对「旧的、超大的」工具输出做确定性瘦身（截头尾留提示，不破坏前缀缓存、不动落盘真源）；记忆压缩触发点 0.6 → 0.7，配合任务账本减少重复摘要造成的漂移。
- **产物打开 / 配图显示 / 进度条** —— 报告/演示稿产物统一「用对应软件打开」；批量生图在对话里内联成可点放大的图廊；并发落盘用原子创建 + 唯一后缀防互相覆盖；进度条整轮读秒，不再卡在 0s。

> 上述能力已纳入 `update_core` 内核白名单（`slides_engine/*`、`generate_presentation`/`generate_image`、`track_task`/`replan`/`task_ledger`、`http_executor`/`memory_compression` 等），老用户点「检查更新」即得；新增引擎**无新增 pip 依赖**（`python-pptx` / `Pillow` / `requests` 已在 requirements）。演示稿/生图产物落 `data/presentations`，升级永不覆盖用户资料。

> Added a self-built PPTX engine (`slides_engine` + `generate_presentation`: styles/charts/flowcharts/icons/font-detection/cover images, two-step outline-first generation, one-click open in PowerPoint/WPS/Keynote), a `generate_image` text-to-image tool (user image-apps first → `DAEMONKEY_IMAGE_MODEL` → browser Doubao → placeholder; concurrent multi-image with an agentic-serialize lock), and an anti-loop toolkit: `track_task` (deterministic working memory that survives compression) + `replan` (a clean-context advisor when stuck). Fixed long-session lag (DOM windowing), high token usage (send-time tool-output slimming + compression trigger 0.6→0.7), plus "open with app"/inline image gallery/collision-safe saving/turn-level timer. All shipped via `update_core`, no new pip deps.

---

## [0.6.8beta] — 2026-07-12

**私有知识库（第二大脑）+ 客户档案 CRM + 双轨情感记忆 + 主动关怀**

### 新增 Added
- **私有知识库 / 第二大脑** —— 把资料（PDF / Word / PPT / MD）灌进来抽文本进 FTS5，可召回、可 cite 回原文；文件夹分组 + 报告一键存入 + `pinned` 常驻优先 + `sensitive` 敏感隔离（不自动注入、只显式召回）。
- **客户档案 CRM** —— 每个客户是会长厚的档案（需求 / 会议 / 交付 / pipeline 阶段），时间线 + 会议纪要打通（语音转写一键存成客户会议），CSV / Excel 导入，notes 进 FTS5 可召回，知识库文档可挂到客户名下。
- **双轨记忆·情感优先** —— 闲聊里自然捕捉情绪 / 生活 / 健康信号（静默记录不打断），成熟后在闲聊语境软回访（防尬，每天最多一次），可选经微信主动慰问（配了才发）。
- **成长档案 hub + 技能库查看器**，掘金脑吃知识库当客观背景（cite 原文），信息雷达并行抓取（墙钟从串行相加降到最慢源）。

> 知识库 / 客户 / 报告 / 雷达数据全在 `data/**`，升级绝不覆盖用户资料。

---

## [0.6.0beta] — 2026-07-11

**工作流并行组 + 自主巡航进度 + 语音对话/会议纪要 + 模型行为设置 + 简洁版/换肤**

### 新增 Added
- **工作流并行组** —— 单步可多 app 并发（或同 app 并行）+ 扇入 join，画布可视化并行分支，向后兼容旧串行 flow。
- **自主巡航进度** —— 后台 turn 实时回「正在做什么·第 N 轮·已 Xs」，不再像卡死。
- **语音对话 / 会议纪要模式**，**模型行为设置**（右上角模型菜单调思考模式 / 推理强度 / 输出上限，按厂商能力智能下发），**简洁版**（`Alt+Z` 只留对话框）+ **标题栏换肤**（存 localStorage 不动文件）。
- **大扩内核白名单** —— `daemon_api.py` + 工坊引擎 + UI 骨架全纳入，让上述能力对升级用户全部真生效。

---

## [0.6.0] — 2026-07-10

**派分身 —— 主对话可以一次派出多个「分身」并行干活，跑完自动汇总回来**

### 新增 Added
- **`dispatch_subagent` 派分身工具** —— 主对话里可以一次派出 1~N 个隔离的「分身」并行完成子任务：每个分身**独立上下文** + **收紧的工具白名单**，跑完自动把结论**汇总回本轮对话**。适合「同时查 A / B / C 三个方向再对比」这类天然可拆分、并行更省时的请求，也能把一段查证隔离出去、不让中间过程占满主对话上下文。
- **`workers/subagent_runner.py` 通用子执行器内核** —— 把「临时 messages → 一次工具循环 → 结构化记账」这段通用中段从 app 执行器里抽出来，成为可复用件。它是「派分身」和后续「工作流每步隔离化」共同的地基。

### 安全边界 Safety
- 分身**默认只拿只读/研究工具**（读文件 / grep / 联网搜索 / 查证…），要写文件才需显式授权。
- 硬性剔除 `dispatch_subagent` 自身（**防无限递归**，本版限一层）以及 `request_restart` / `update_core` / `service_*` 等系统控制 / 破坏性工具，即便显式点名也不下放。
- **并发上限 2** + 每个分身独立迭代预算 + 汇总时按长度截断，防 token 失控、防撑爆主对话上下文。
- 每个分身跑完落 `sessions/sub-*.jsonl`，事后可回看它到底查了什么（可追溯）。

> `workers/subagent_runner.py` 与 `agent_tools/dispatch_subagent.py` 已纳入 `update_core` 白名单，老用户点「检查更新」即得（工具随下发自动激活，无需重下 ZIP）。

> Added: `dispatch_subagent` lets the main chat fan out 1~N isolated sub-agents in parallel — each with its own context and a tightened tool whitelist — then auto-aggregates their conclusions back into the current turn. Great for "research A, B and C at once, then compare". Backed by a new reusable core `workers/subagent_runner.py`. Safety: sub-agents get a read-only/research whitelist by default; `dispatch_subagent` itself (no recursion) plus system-control/destructive tools are always stripped; concurrency capped at 2 with per-sub-agent iteration budgets and output clipping; every sub-agent is persisted to `sessions/sub-*.jsonl`. Both files are in the `update_core` whitelist — existing users get it via "检查更新".

---

## [0.5.5b] — 2026-07-10

**对话滚动位置修复（UI hotfix）—— 切换会话标签不再回顶部**

### 修复 Fixed
- **多对话标签切换时对话栏弹回顶部、丢失滚动位置** —— 整个对话区共用一个滚动容器（`#messages`），切回已打开的会话标签时只切了可见性、没存/还原滚动位置，导致每次切回都跳回顶部。现在离开会话时记录其滚动位置，切回时按上次位置还原；离开时在底部则回到底部并继续跟随流式输出（同步粘底标志）。仅动会话切换分支，不碰发送 / 流式 / 首次加载滚到底逻辑。

> Fixed: switching between open conversation tabs no longer resets scroll to the top. Per-session scroll position is now saved on leave and restored on return (bottom-stick preserved). Since `static/chat.js` is in the `update_core` whitelist, existing users get this fix via the launcher's "检查更新" — no ZIP re-download needed.

---

## [0.5.5a] — 2026-06-29

**浏览器的手 Chrome 兜底（hotfix）—— 不再只认 Edge**

### 修复 Fixed
- **没装 Edge 的机器用不了浏览器的手** —— 专属浏览器从 Edge-only 改为 **Edge → Chrome → 用户指定** 的择优查找：找不到 Edge 自动退 Chrome（同为 Chromium 内核，CDP 路径完全一致）；两者都没有时可设环境变量 `DAEMONKEY_BROWSER_PATH` 指向任意 Chromium 内核浏览器 exe（绿色版/非标准路径）。`_find_edge` → `_find_browser`，相关报错文案同步成「Edge / Chrome」。纯兜底增强，无新依赖。

> Hotfix: the dedicated browser is no longer Edge-only. Now resolves Edge → Chrome → user-specified (`DAEMONKEY_BROWSER_PATH`). Machines without Edge fall back to Chrome (same Chromium core, identical CDP). No new dependency.

---

## [0.5.5] — 2026-06-29

**浏览器的手 —— 真的能操作网页（点/填/上传/收图），不只是「看」**

### 新增 Added
- **`browser_act` 浏览器的"手"** —— 在 daemon **专属 Edge** 上真的操作网页：`goto` / `click` / `fill`（含 contenteditable 富文本框）/ `upload`（传本地参考图）/ `press` / `wait` / `read` / `download` / `harvest`（读 src 直接收页面已渲染的图/视频）/ `screenshot` / `inspect`（把页面可交互控件 dump 成纯文字，纯文本模型据此挑选择器、不靠视觉）。多步动作**不关标签页**，状态留在专属 Edge，能跨多次调用接力（开站 → 上传参考图 → 填提示词 → 点生成 → 等 → 收图）。找不到元素**绝不假装成功**：自动截图 + 如实报卡在哪一步。
- **专属 Edge（独立 profile + 独立端口 9333）** —— daemon 自己拥有一个与你日常浏览器**物理隔离**的 Edge，需要时自动拉起、跨调用复用，**绝不碰、绝不杀你的主浏览器**。需登录的站点（豆包/知乎/微信…）在这个专属窗口里登一次，登录态持久化在专属 profile。`browser_fetch`（眼）与 `browser_act`（手）共用同一实例，杜绝"眼手连到不同浏览器"。

### 变更 Changed
- **`browser_fetch` 改走专属 Edge** —— 不再依赖手动开 `Edge --remote-debugging-port=9222`；`cdp` 模式自动拉起 daemon 专属 Edge，`auto` 模式专属 Edge 在就 attach、不在走轻量 standalone。
- **`playwright` 进 `requirements.txt`** —— 浏览器三件套靠 Playwright 驱动系统 Edge（`connect_over_cdp` / `channel="msedge"`），**无需** `playwright install` 下载浏览器内核。此前未列依赖，新用户 pip 完直接缺包。

> Added `browser_act` — the browser "hand": click / fill / upload / press / wait / read / download / harvest / screenshot / inspect, on a **dedicated** Edge (own profile + port 9333, physically isolated from your daily browser, never touched/killed). Multi-step state persists across calls; never fakes success (auto screenshot + honest stuck-point on failure). `browser_fetch` now auto-launches & shares that same dedicated Edge. Added `playwright` to requirements (drives system Edge via CDP — no `playwright install` needed).

> **升级说明**：浏览三件套是 `agent_tools/` 下的 L2 能力工具（同 `web_fetch`，**不在 `update_core` 白名单**）。老用户点启动器「检查更新」只同步白名单内的内核文件、**不含此能力** —— 请**下载本 Release 的 ZIP / exe** 即得（或自行 `pip install playwright` 后把 `agent_tools/_browser.py` / `_browser_actions.py` / `browser_act.py` 拷进去 + 用本版 `browser_fetch.py`）。

---

## [0.5.2b] — 2026-06-29

**用户报修三连（vision 404 / 填 URL 卡死 / env 暴露内部代号）**

### 修复 Fixed
- **视觉模型配置报 404（Not Found）** —— `/vision-config` 接口代码本就存在，但主程序 `daemon_api.py` 漏了一行 `include_router` 注册，前端配置视觉模型时找不到路由。已补注册。（`daemon_api.py` 不在升级白名单，此修复随新下载的 ZIP / exe 下发。）
- **初见 / 换 key 填 URL 失败且改不了** —— `save-key` 改为**先试连再落盘**：连不通就不写 `.env`，把人话错误（含「在结尾加 / 去掉 `/v1`」的具体可粘贴地址）抛回前端，配置卡片保留、当场改，根治「填错一次只能去手改 `.env`」的卡死。新增 `clean_base_url` 自动去掉用户误贴的 `/chat/completions` 尾巴（贴完整端点会被 SDK 重复拼接 → 404）。
- **环境变量名暴露内部代号** —— 写进用户 `.env` 的配置名由 `OPUS_*` 改为 `DAEMONKEY_*`（社区有人截图露出 `OPUS_BASE_URL`）。新增 `workers/env_aliases.py` 双向别名垫片：内核数百处 `os.environ["OPUS_*"]` 读取**一行不改**也能拿到值，老用户旧 `OPUS_*` 的 `.env` 完全兼容、不破坏。

> Three user-reported fixes: vision-config 404 (missing router registration), onboarding API-URL save now probes before persisting (with `/v1` hint + `/chat/completions` trim, no more stuck-on-bad-config), and the public-facing `.env` keys are renamed `OPUS_*` → `DAEMONKEY_*` with a backward-compatible alias shim (existing `.env` files keep working).

---

## [0.5.2a] — 2026-06-29

**首个公开发布的发布物修复（hotfix）· 主要惠及新下载用户**

### 修复 Fixed
- **品牌签名校验误杀正规包** —— `.gitattributes` 把 `assets/brand.json` 标记 `-text`，钉死换行符。此前 git 的 CRLF↔LF 自动转换会让正规 `clone` / GitHub「Download ZIP」拿到的字节与作者签名时不一致，导致验签失败、启动器误弹「这不是官方版」。固化成签名对应的字节后，所有人验签通过。（作者本机因 `autocrlf` 恰好转成一致而未触发，故仅用户侧暴露。）
- **大屏对话栏过窄** —— `chat.css` 新增大屏断点：≥1680px 默认对话栏 540px、≥2200px 640px。此前默认值 400px 只为中屏调，1080p+ 上对话区显窄。仅调整「从未拖动过」用户的默认值（JS 只在 `localStorage` 有值时才覆盖），拖动习惯零影响，仍可在 280–800px 自由拖拽。

> First public hotfix. Fixes brand-signature false-positive on `clone`/ZIP downloads (CRLF normalization) and a too-narrow chat pane on 1080p+ screens. Affects newly downloaded copies; existing installs were unaffected.

---

## [0.5.2] — 2026-06-24

**技能闭环打通 + 开源门面 + 品牌防护**

### 新增 Added
- **技能闭环第②环「接住」** —— `extract_playbook` 新增 `import` 动作 + `workers/playbook_import.py`：把外部 SKILL 文档经 LLM 归一成自己的 Playbook 入库，`memory_index` 自动索引，按需召回。从此「发现 → 接住 → 按需用」的技能生命周期闭环。
- **启动器双发布入口** —— 关于页 B站 + 抖音胶囊双按钮。
- **品牌资源签名校验** —— `assets/brand.json` 私钥签名 + 启动器内置公钥验签，防止官方渠道被冒名篡改。
- **暗记水印** —— 代码层 + banner 隐写溯源标记（防盗版传播）。

### 变更 Changed
- **playbook 技能系统整体纳入 L1 内核白名单** —— discover（发现）/ import（接住）/ extract（沉淀）/ playbooks（存储）写入侧与召回侧不再割裂，官方可增量下发改进。
- **维修台中性化** —— `repair.bat` 重写为纯 ASCII（消除中文编码雷）+ 标题中性品牌。
- **ZIP 用户更新机制** —— 启动器首启静默配置官方升级源（Gitee 主 + GitHub 备份，自动 failover + 超时保护）。

### 修复 Fixed
- **`max_tokens` 单一真相源** —— `safe_max_tokens` 统一裁决，thinking / 长文档模型不再被写死的小值截断。
- **宪法注入断链** —— 修复 `soul_loader` 未接入 `product_constitution` 的同步遗漏（通用三条现已正确注入 system prompt）。
- **LLM read timeout** —— 60s → 300s，扫清各处写死的过短超时。

> Skill lifecycle closed (discover → absorb → use), dual publish entries, brand signature + watermark, kernel whitelist for the playbook system, and a batch of timeout / max_tokens fixes.

---

## [0.5.0] — 2026-06

**自主节奏 + 产品宪法 + 急救体系**

### 新增 Added
- **NLP 定时任务** —— `workers/task_scheduler.py` + `scheduled_tasks` 工具组：用自然语言设定周期任务，到点自动在后台跑一个完整 LLM turn。侧边栏新增「定时任务」维度。
- **产品宪法两层注入** —— `product_constitution.py`：通用三条（闭环 / NLP 优先 / 可追溯）作为内核地基随升级同步，实例宪法 `soul/CONSTITUTION.md` 从使用中沉淀。
- **急救体系周全** —— `ensure_git_repo` 首启兜底（无 git 也能建仓）、维修台优先策略、回档与自测入口齐全。

> User-defined NLP scheduled tasks, two-layer product constitution, and a complete emergency rescue system.

---

## [0.4.0] — 2026-06

**能力发现引擎**

### 新增 Added
- **`discover_skill` 画像驱动发现引擎** —— Daemonkey 照着你的画像主动去 GitHub / B站 / 抖音找「别人做出来的 AI 能力」。
- **每周一节律** —— 自动发起一次能力发现。
- **看板入口** —— 发现结果落到 WebUI 看板，可一键评估、落地。

> Profile-driven capability discovery engine with a weekly rhythm and dashboard entry.

---

## [0.3.2] — 2026-05

**记忆系统纳入内核**

### 新增 Added
- **记忆自动注入** —— 启动时灵魂套件自动读进上下文。
- **两段式 recall** —— FTS5 全文检索，先列表后细读，省 token。
- **缓存稳定化** —— prompt caching 长期保持高命中。

> Memory system promoted into the kernel: auto-injection, two-stage FTS5 recall, cache stabilization.

---

## [0.2.x] — 2026-05

**内核版本体系 + 核心前端 + 备份源**

### 新增 Added
- `core_version` 版本号体系（用户感知的内核版本唯一真相源）。
- 核心前端搬入（WebUI 主链路）。
- GitHub 备份源接通（Gitee 主 + GitHub 备份双源）。

---

## [0.1.0] — 2026-05

**首个用户版 · 相遇 onboarding**

### 新增 Added
- **「相遇」onboarding** —— 网页版三幕（相遇 / 认识你 / 立约）：第一次打开就能在网页里完成初始化，给它起名、立约。
- **一键启动器** —— 双击 exe → 装环境 → 启动 → 浏览器自动打开 → 填 key → 相遇。
- **AGPL-3.0 开源** —— 用户版不含任何作者私有记忆，从空白种子开始。

> First public user build: web-based "encounter" onboarding, one-click launcher, AGPL-3.0.

---

[0.5.2a]: https://gitee.com/vaan21th/dae-monkey
[0.5.2]: https://gitee.com/vaan21th/dae-monkey
[0.5.0]: https://gitee.com/vaan21th/dae-monkey
[0.4.0]: https://gitee.com/vaan21th/dae-monkey
[0.3.2]: https://gitee.com/vaan21th/dae-monkey
