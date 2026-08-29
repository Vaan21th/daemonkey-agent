# presentation · PPT / 演示稿 / 生图配图

> **触发**: 他说「做一份 PPT / 演示稿 / 汇报 / 课件 / 提案」；或要给报告/封面配图、调 `generate_presentation` / `generate_image`。
>
> **何时主动读**: 准备调这两个工具之前。schema 只留参数名，工艺合同在这里。
> 实例手艺（「上次 B 站 412」那种）走 playbook，不写进本合同。

---

## 两步施工（除非他说「直接做」或只有三五页）

① **施工单**（先写在回复里让他过目，再调工具）:
标题 / 受众 / 风格 / **配图计划（哪几页配图、放哪、图哪来）** / 逐页（版式 + 要点）。
交付前以总监视角自审：配图够不够？时间线走了 flow 吗、数据走了 chart 吗？哪页太平？有问题当场改施工单。等他说「就这样 / 做」再进第二步。

② **生成**: 确认后再调 `generate_presentation`。长稿把最终分页 markdown 写进回复正文，再调工具只给 `title`（自动抓）。短稿可直接传 `body`。

产物落 `data/presentations/`。CONFIRM：真文件要他点头。

---

## 配图是硬要求

最常犯的病 = 交一份全文字白板稿。

- 封面几乎必给主视觉：传 `cover_prompt`（没配生图模型也会渲成「配图提示词」占位卡，他能一键补图）。
- 正文别连续多页纯文字：每 3~4 页至少一个视觉承载 —— `image` / `chart` / `pillars` 三选一。
- 一份稿至少封面 + 每隔几页要有视觉。全程纯文字 QA 会拦。别硬凑图凑满每页。

### 图哪来（按序降级）

1. `generate_image`（`out_dir` 传本工具的 `embed_image_dir`）→ `<!-- image: 相对路径 -->`
2. 报「未配置」→ `browser_act` 走豆包网页版 playbook，落到 `embed_image_dir` 再引
3. 都不行 → `<!-- layout: image --><!-- prompt: 画面描述 -->` 渲成提示词占位卡

封面主视觉同样走这条链。`cover_image` 有现成图就用；`cover_layout=full`（默认·满版大图+遮罩+白字）/ `hero`（左字右图）/ `auto`。都不传走渐变封面。

### 文字落在哪（生图里绝不要放字）

画面里不要有文字 / 标签 / 标题 / 数字 / logo（会糊，裁切会砍边，PPT 必翻车）。文字全交给 PPT 层。

- 要在图上压标题/金句 → `cover`（`cover_layout=full/hero`）或 `statement`，引擎叠真文字 + 压暗遮罩
- 图只是配图 → `image` 版式，标题在页眉，配 `<!-- caption: 图注 -->`
- 带标签的概念（三角定位 / 四象限 / 流程）→ `flow` / `chart` / `pillars`（标签是引擎画的真文字），别让生图画带字的图再被裁

---

## 每页先选版式（别一股脑 bullets）

| 内容 | 版式 |
|---|---|
| 步骤 / 流程 / 时间线 / 路线图 | `flow`（不要写成缩进要点） |
| 数据 / 占比 / 对比 / 趋势 | `chart`（pie 占比 · column/bar 对比 · line 趋势） |
| 能力 / 特性 / 优势 / 几个方向 | `pillars` 或 `two_col` |
| 成绩 / 关键数字 | `metrics`（value 只能短数字/百分比：92% / 12万 / 3个；词组改 pillars/two_col） |
| 一句重话 / 主张 | `statement` |
| 过渡 | `section` |
| 纯观点罗列 | `bullets`（且每页 ≤6 条） |
| 信源 | `sources`（每条要点 = 一条信源 · 宪法第 5 条） |
| 收束 | `closing` |

正文直接写文字即可，不用写 markdown 的 `**` 粗体、`#` 井号（引擎会处理）。
`{rocket}` 这类图标 token **只在 metrics/pillars 页的行首**用，写进普通句子会被当字面量清掉。

---

## 分页 markdown 写法

一行 `---` 分隔每页。每页可带指令注释（各占一行或多条写一行都认）：

```
<!-- layout: cover|section|bullets|image|statement|two_col|metrics|pillars|chart|flow|sources|closing -->
<!-- kicker: 小眉标 -->
<!-- image: 相对图片路径 -->
<!-- prompt: 配图提示词 -->
<!-- caption: 图注 -->
<!-- notes: 演讲备注 -->
```

语法：`# 标题`  `## 小标题/列头`  `> 金句`  `- 要点`（缩进=子级）  `![](图路径)`

- **metrics**: `- 92% | 用户满意度`；可加图标 `- {money} 12万 | 累计营收`
- **two_col**: 两个 `##` 各起一列
- **pillars**（2~4 张卡）: `- {rocket} 快速交付 :: 一周内上线`
  图标名：rocket/gear/people/chart/money/idea/target/star/doc/check/time/search/flag/link/growth（也认 team/revenue/insight/process）
- **chart**: `<!-- layout: chart -->` + `<!-- chart: pie|doughnut|bar|column|line -->`
  单序列 `- 内容账号 | 42`；多序列用 markdown 表格（首列=横轴，表头=各序列）
- **flow**: 每条要点 = 一个步骤框（≤5 步，按箭头串）

每页 ≤6 条要点。一句话讲不完就拆。留白才高级。

---

## 设计风格（一套引擎 · 不是堆模板）

- **style** 基底 6 套：`light_studio` 浅商务 / `dark_keynote` 深色发布会 / `editorial` 杂志 / `glass` 玻璃拟态 / `neon_glitch` 霓虹故障 / `sketch` 手绘涂鸦
- **accent** 主色：从他话里理解 → 俗名或 hex（蓝 / 科技蓝 / green / #2563EB）。引擎派生 accent2 / 文字对比 / 标题深调
- **mood**：`calm` 沉稳 / `vivid` 活泼（字更大上色块）/ `sharp` 锐利（去色块更利落）
- **style_spec**（现成三件套盖不住时才用）：自己产一组设计 token，引擎校验+夹紧+兜对比度

style_spec 可用 token：
- 颜色（hex 或俗名）：bg / bg_alt / ink_title / ink_body / ink_muted / accent / accent2 / on_accent / rule
- 材质：surface_alpha（8-100）· corner_radius（0-0.5）· panel_gradient（bool）
- 效果：shadow_style（none|soft|glow|hard）· texture（none|grid|dots|scanline|beams）· stroke_style（clean|hairline|hard|sketch）
- 个性：font_role（sans|serif|mono|hand）· accent_shape（bar|underline|dot|slash|none）· decor（none|blob|corner）· is_dark · uppercase_kicker
- 字阶：pt_cover_title / pt_title / pt_section / pt_heading / pt_body / pt_kpi / pt_statement（9-96）

例：磨砂玻璃暖橙 → `style=glass` + `style_spec={"accent":"橙","surface_alpha":20}`；
复古打字机 → `{"font_role":"mono","texture":"grid","bg":"F4EFE3","accent":"8A3B2E","shadow_style":"none"}`。

排版纪律（对齐/留白/字阶/章节头不压标题）由引擎钉死。「科技蓝活泼」「玻璃拟态暖橙」都是同一引擎的不同参数。

---

## generate_image

多张图必须一次调用 `prompts:[...]` 并发。禁止每张单独调（工具调用会被串行，卡死）。

后端自动选：工坊生图 app → `DAEMONKEY_IMAGE_MODEL` → 未配置则走上面「图哪来」②③。

接进 PPT：`out_dir` 传 `generate_presentation` 的 `embed_image_dir`（或默认 `data/presentations/generated`）；封面单独生 16:9（`size=1792x1024`）。

### 提示词配方

主体 + 场景 + 光线 + 明暗对比 + 构图 + 镜头/景深 + 色调/风格 + 情绪。

- 光线：电影级布光、chiaroscuro、逆光/轮廓光、黄金时刻、体积光
- 构图：三分法、非对称、大量负空间（**给标题留干净落字区**）、引导线
- 镜头：浅景深、广角、微距；色调：统一色调 / 高级灰 / 克制配色
- 封面例：`城市夜景俯瞰,冷暖霓虹交织,强烈明暗对比,左下大面积暗部留白,电影感广角,高级色调`

`art_boost` 默认开：白开水描述会自动补艺术方向；已写光影/构图就原样尊重。

---

## 反面教材

| 症状 | 根因 | 修法 |
|---|---|---|
| 全文字白板稿 | 没配图计划、全用 bullets | 施工单先写配图页；每 3~4 页一个视觉承载 |
| 生图带字被裁糊 | 提示词写了标注/标题 | 字交给 PPT；概念图改 flow/chart/pillars |
| 多图卡死 | 每张一个 generate_image | 一次 `prompts:[...]` |
| metrics 排版崩 | value 塞了「市场定位」这种词组 | value 只放短数字；词组改 pillars |
| 豆包薅图 90 次只嵌 2 张 | 网页版链路脆 | 优先工坊生图 app / IMAGE_MODEL |

---

*位置: data/cognition/scenarios/presentation.md · 触发时由 `read_scenario` 拿出来。*
