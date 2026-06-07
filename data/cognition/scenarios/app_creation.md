# app_creation · 工坊造资产场景细则

> **触发**: 用户说"建一个 X 应用" / "做一个 X 应用" / "再加个 Y app" / "排个工作流" /
> "把这几步串成 pipeline"。 或者你判断当前任务是给工坊建 app / workflow / skill。
>
> **何时主动读这个**:
> 1. system_prompt 场景索引里看到"app_creation"
> 2. 准备调 `create_app` / `create_workflow` / `extract_playbook` 之前
> 3. 准备给 app 装 API key (调 `app_set_secret`) 之前
>
> 这里聚集**铁律 6 + 7** 的完整细则。

---

## 铁律 6 · 造工坊资产时先落档 · 再施工

> **先分清「造应用」≠「改工坊工具」**:
> - **造应用实例**——`create_app`/`create_workflow` 落 `data/workshop/apps/*.json`(**数据文件**)·
>   炸不了平台(最多这个 app 自己跑不通)·**不走 wish**·走本铁律 6+7 即可。
> - **改工坊工具/引擎本身**——改 `draft_studio` 输出 schema / `workflow_engine` / 加一类新节点
>   (**daemon 代码**)·改坏了整条产线受牵连·**走 wish**(回铁律 1 分级)。
>
> 判断轴 = **改的东西能不能让平台炸**: 能(代码)→ 走流程 · 不能(数据/应用)→ 不用。
>
> **持久化模型**: `data/workshop/apps/` 跟 `flows/` 已 gitignore ·
> = 与 git 分支**无关**的运行时资产 (跟 `outputs/` `secrets/` 一致)·
> 切分支/合并/重启都不碰 → **应用永不丢**。
> 代价: app 不进 git 历史 (本就是生成资产·不是源码)。 要造的 app 牵动平台代码 → 那部分仍走 wish。

**触发**:
- 用户说"建一个 X 应用"/"做一个 X 应用"/"再加个 Y app"
- 用户说"排个 X 工作流"/"把这几步串成工作流"/"来个 X→Y→Z 的管线"
- 用户说"提炼一个 skill" / "把这个步骤变成 playbook"

**纪律 · 三步**:
1. **先 `create_app` / `create_workflow` / `extract_playbook` 落档**
   产物落到 `data/workshop/apps/<app-id>.json` (或 workflows / skills/) ·
   元数据先记着 · 占位 · 让用户 F5 工坊立刻看见有这个事
2. **再施工** (调底层工具实现 · 例如 `shell_exec` 装包 / `write_file` 写
   prompt / `app_set_secret` 装 key)
3. **施工完回写** · 调 `app_set_status` / `wish_update` 关联

**反面教材**:
   想了 17 分钟思考链漂亮 · 但 0 次 `create_app` · 用户 F5 工坊空空 · 物证零。
   后果: 用户关心的"你给我建了什么" 看不见 · 整个 turn 等于没存在过。

**产物落点 (铁律 6.1)**:
- ❌ 不要 `write_file` 写 `.exe` / `.dll` / `.pyd` 二进制 (PowerShell 会把它当文本写坏)
- ❌ 不要 `write_file` 写 windows 绝对路径 `F:\...` 当 url (浏览器拒绝 file://)
- ❌ 不要 `write_file` 写 `<img>` HTML 标签 (mdRender 会 escape 转义)
- ✅ 二进制下载用 `shell_exec curl` · 路径用 `data/workshop/outputs/<domain>/<file>` 走
  daemon static 服务

---

## 铁律 7 · KEY/secret 永远走 secret store · 不准写明文进任何文本资产

**触发**:
- 用户把一个 API KEY / token / 密码 / 凭证发给你 · 让你装 / 调用 / 测试 API
- `create_app` 之后准备写 system_prompt · 想引用用户给的 KEY
- `create_workflow` 之后准备写 step 模板 · 想嵌用户给的 KEY

**纪律 · 三步**:
1. **必须先 `app_set_secret`** · KEY 落到 `data/workshop/secrets/<app-id>.json` (`.gitignore` 拦着)
2. **system_prompt / step 模板用 `${secret:<app_id>:<name>}` 占位** · 不写真值
3. **运行时 daemon 替换占位** · 真值不进任何 git 跟踪的文件

**反面教材**:
   `sk-key` 真值明文写进 `config.api_key` 字段 · 一旦 `git push` 永久暴露。
   修法就是这个铁律 + `app_set_secret` / `app_list_secrets` / `app_delete_secret` 三件套。

**严禁**:
- ❌ 在 chat 里 `print(api_key)` (chat history 会跨 session)
- ❌ 写 `f"Authorization: Bearer {api_key}"` 入 system_prompt (走 secret store)
- ❌ 装 .env 时把 KEY 写进 docs/ / data/learnings/ (截图也会泄)
- ✅ 临时调试: `app_get_secret_for_test` (TIER_CONFIRM · 用户批准才能解)

---

## 反面教材汇总 (app_creation 域)

| 错在哪 | 学到 |
|---|---|
| 思考链很长 · 0 次 create_app · 工坊空 | 加铁律 6 (先落档再施工) |
| `sk-key` 写明文 config · git 暴露 | 加铁律 7 + secret store 三件套 |

---

## 工艺指南 · 应用设计四步法

> 铁律 6+7 保证不翻车。四步法保证做出来的应用真的好用。

### 第一步：选 exec_kind · agentic 还是 scripted

这是建 app 的第一个决策——决定这个应用的核心执行模式。

| 判断维度 | agentic（LLM 调度） | scripted（0 LLM 直转） |
|---|---|---|
| 需要 LLM 理解需求 + 动态决策 | ✅ 适合 | ❌ 做不到 |
| 固定参数 → 调 API → 拿结果 | ❌ 浪费 token + 慢 | ✅ 最佳 |
| 多步工具链（读文件→分析→写文件） | ✅ 适合 | ❌ 做不到 |
| 输入格式多变、边界情况多 | ✅ 灵活 | ❌ 硬编码扛不住 |
| 速度 | 秒~分钟级（LLM 思考） | 毫秒~秒级 |
| 每次成本 | $0.01-0.10 | $0 |

**选择树**（按顺序问自己）：

```
1. 这个应用的核心是不是"接收参数 → 调外部 API → 返回结果"？
   └─ 是 → scripted（图像生成、语音合成、翻译、语音识别……）
   └─ 不是 → 往下

2. 这个应用需要读本地文件 / 跑命令 / 多步推理 / 动态判断吗？
   └─ 是 → agentic（周报生成、代码审查、竞品分析、debug……）
   └─ 不是 → 往下

3. 拿不准？
   └─ 先用 agentic 跑通，再评估要不要优化成 scripted
```

**反面教材**：一个图像生成 app 最初用了 agentic 模式。用户说"生成一张图"，LLM 先思考"我应该调什么工具"再决定调 shell_exec curl，每次多烧 $0.02-0.05 还慢 3-5 秒。后来改成 scripted + exec_template，form 提交直接拼 HTTP 请求转发，秒级出图，零 token 成本。

### 第二步：写 system_prompt

system_prompt 是 agentic app 的"操作手册"。写好了 LLM 像老兵，写差了像无头苍蝇。

**四段式结构**：

```
## 角色
一句话。你是谁、你的唯一任务是什么。

## 输入
用户会给你什么。如果有 ui_form_schema，写清楚字段对应关系。
例："用户通过表单提供了以下输入：text（要合成的文字）、emotion（情绪）、speed（语速）"

## 动作
你必须执行的步骤。不超过 3 步，每一步写清用什么工具、达到什么效果。
例：
  1. 读 data/xxx.json 拿到上周数据
  2. 用 web_search 搜本周相关动态
  3. 把两者整合成 markdown 周报

## 输出
你返回给用户的格式。越具体越好。
例："返回纯 markdown，含 ## 本周摘要 / ## 关键指标 / ## 下周计划 三个段落"
```

**工具白名单怎么选**：

| 应用场景 | 推荐 tools |
|---|---|
| 纯文本处理（总结、翻译、改写） | `[]` 或省略（不需要任何工具） |
| 需要读本地文件 | `['read_file', 'grep_files']` |
| 需要读 + 跑命令 | `['read_file', 'shell_exec']` |
| 需要搜网页 | `['web_search', 'web_fetch']` |
| 需要读 + 写 + 搜 | `['read_file', 'write_file', 'web_search', 'web_fetch']` |

**收紧原则**：给的工具越少，LLM 越不会乱来。能不用工具就不用，能用 2 个别给 5 个。

**反面教材**：
- system_prompt 写"你是一个强大的 AI 助手，帮助用户完成各种任务" → LLM 不知道自己是干嘛的，开始自由发挥、调不该调的工具。
- tools 给 `['shell_exec', 'write_file', 'web_search', 'open_app', 'read_file']` 但应用只是做文本总结 → LLM 可能跑去搜网页甚至打开应用。

### 第三步：ui_form_schema · 写还是不写

**该写表单**：
- 应用的输入参数固定且明确（文字 + 情绪 + 语速 / 描述 + 尺寸 / 日期范围 + 指标名）
- 用户会重复使用（≥5 次/周）
- 不写表单的话用户每次要打同样结构的 prompt → 烦

**不该写表单**：
- 开放对话型应用（聊天、头脑风暴、自由问答）
- 输入参数每次都不一样、无法模板化
- 写了反而限制用户的表达自由

**判断口诀**：**"用户每次用这个 app 说的第一句话是不是都差不多？"** 差不多 → 写表单。每次都不一样 → 不写。

**反面教材**：给一个"代码审查"app 写了表单（文件路径 + 审查维度）→ 用户发现每次审查的文件都不一样、关注点也不一样，表单变成了碍事的东西。

### 第四步：建完后的测试验证

**标准测试动作**（按 exec_kind 分）：

**scripted app**：
1. 用户填表单提交一次
2. 检查返回的 output_schema 字段是否都有值
3. 没值 → 看 exec_template 的 `response.extract` 路径是否匹配实际 API 返回结构
4. 调一次 shell_exec curl 看原始 response JSON → 修正 extract path
5. 通了 → 告诉用户 "app-xxx 测通，工坊直接可用"

**agentic app**：
1. 用户给一个最简单的测试输入（不要边缘 case）
2. 看 LLM 是否按 system_prompt 约束的行动步骤走
3. 看 LLM 是否只用了白名单里的工具（没乱调）
4. 看输出格式是否符合约定
5. 不通 → 改 system_prompt 加约束 → 再测
6. 通了 → 再给一个稍复杂输入测边界

**测试完成标准**：同一个 app 连续两次不同输入都按预期跑通 → 才算测完。

---

## 常见翻车模式 · 速查表

| 症状 | 最可能的根因 | 修法 |
|---|---|---|
| LLM 调了不该调的工具 | system_prompt 太宽泛 + tool 白名单太大 | 收紧 prompt 角色设定 + 砍白名单 |
| 输出格式每次不一样 | prompt 里没约定输出格式 | 加"你必须返回以下格式的 markdown：…" |
| scripted app 跑不通 | `response.extract` 路径跟实际 API 返回对不上 | 先 curl 一次看原始 JSON 结构再改路径 |
| 用户说"不知道怎么用" | 缺 ui_form_schema 或 description 写太抽象 | 补表单 + 改 description 为"输入 X → 得到 Y" |
| agentic app 太慢 | 每次都过 LLM 思考链但其实不需要 | 评估是否该切到 scripted |
| 用户提交表单后没反应 | 可能 exec_kind=agentic 但 system_prompt 没告诉 LLM"表单字段是什么" | 在 system_prompt 里明确列出表单字段对应关系 |
| 应用输出里出现真实 KEY | 铁律 7 违反——KEY 写了明文 | 立刻轮转 KEY + app_set_secret + 改 prompt 用 placeholder |

---

*工艺指南是活的——每次翻车后回来加一条。*
