# 更新历史 · Changelog

本项目版本号遵循语义化版本（`core_version` 是用户感知的内核版本，是唯一真相源）。
启动器 / WebUI 动态读取它显示当前版本，`检查更新` 拿它和官方源对比。

> All notable changes to Daemonkey. The `core_version` is the user-facing kernel version (single source of truth).

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
