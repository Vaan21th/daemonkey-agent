# 更新历史 · Changelog

本项目版本号遵循语义化版本（`core_version` 是用户感知的内核版本，是唯一真相源）。
启动器 / WebUI 动态读取它显示当前版本，`检查更新` 拿它和官方源对比。

> All notable changes to Daemonkey. The `core_version` is the user-facing kernel version (single source of truth).

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

[0.5.2]: https://gitee.com/vaan21th/dae-monkey
[0.5.0]: https://gitee.com/vaan21th/dae-monkey
[0.4.0]: https://gitee.com/vaan21th/dae-monkey
[0.3.2]: https://gitee.com/vaan21th/dae-monkey
