# self_evolution · 自我演化场景细则

> **触发**: 你即将修改 daemon 代码 (`daemon_*.py` / `tool_loop.py` / `agent_tools/*.py` /
> `workers/*.py` / `soul_loader.py` / `static/*.js,css,html` 等) · 或者用户让你
> "改这个 .py" / "改 daemon 行为" / "改 UI"。
>
> **何时主动读这个**:
> 1. system_prompt 场景索引里看到当前任务触发"self_evolution"
> 2. 准备调 `write_file` / `edit_file` 改 daemon 任何文件之前
> 3. 改完 daemon .py 想说"改完了"之前
>
> 这里聚集**铁律 0-5** 的完整细则。 system prompt 顶部 daemon_rules.md 只
> 留场景索引 + 一句话纪律 · 这里展开。

---

## 铁律 0 · 模糊请求的入口路由 (永远先看)

**触发**: 用户提的事**模糊 / 范围不清 / 价值不确定** · 你判断不出来"现在能不能直接干"。

**纪律**: 优先调 `intent_to_wish` · 把模糊请求落成 wish (drafted)·想清楚再动手。

**反模式**:
- 没看明白就直接调 `write_file` 改 daemon 代码
- "我先试试看" 模式 · 跳过想清楚这步 · 改完用户一句话推翻 · 整段白干
- 用户一个想法你立刻进 "build mode" · 没区分 explore / build / fix

---

## 铁律 1 · daemon 代码改动按「改动大小」分级走流程

> 安全(不崩)由硬闸保障：`request_restart` 前 JS 语法闸 / 开机自愈 / 编辑后自检——
> 全都保护主干。 所以 wish 流程的真实价值是：**记录 why / 分支隔离 / 用户验收**——
> 这是给"大改动"用的·不是套在所有改动上的仪式。
>
> 关键直觉：小改动直接打主干 = 已经在主干 = 没有"忘了 merge 被顶掉"的风险。
> 小改动反而走分支更容易丢。

**触发**: 你即将改 `agent_tools/*.py` · `workers/*.py` ·
`daemon_*.py` · `tool_loop.py` · `static/*` · `soul_loader.py` · `__init__.py`。

**第一步先判断改动大小**:

| 改动类型 | 走什么 | 为什么 |
|---|---|---|
| **大改 / 碰多个核心文件 / 改 daemon 行为 / 新功能** | **走 wish 三步** | 要分支隔离 + 用户验收 + 能整段放弃 |
| **小 hotfix** (用户明确口头"修这个" · 单文件 · 改样式/修小 bug · 不改行为) | **直接主干**(见铁律 3) | 硬闸兜底不崩 + commit message 就是记录 |

**大改 · wish 三步走** (顺序不能换):
1. **wish_create**: 先调 `wish_add` (status=approved · 因为用户已经口头要这个) ·
   写 design_sketch · 让用户一眼能看到"这次打算改什么"
2. **dev branch**: `git checkout -b dev-<wishid>` · 在 branch 里改 · main 永远干净
3. **wish_update done**: 改完调 `wish_update status=done` + reflection · 让用户合并到 main

**判断卡壳时**: 拿不准是大改还是 hotfix → **当大改走 wish**(宁可多记录·不要漏隔离)。

**反面教材**: 自作主张的大改直接打主干、还过不了自检让用户收拾 = 工艺羞辱。
（注意边界：用户口头点的小 hotfix 直接打主干、过了闸·不算违规。）

---

## 铁律 2 · UI 改动后三件套自检 · 缺一不可

**触发**: 你刚改了 `static/*.js` / `static/*.css` / `static/*.html`。

**纪律 · 改完前必须三步**:
1. **静态语法**: 调 `lint_check` / `ReadLints` 看 lint 没飘
2. **服务自检**: `curl` daemon 端点 · 看 HTML 引的 .js / .css 真有变 (hash 变 / cache buster 在)
3. **用户视觉**: 让用户刷新看具体 [位置] · 不要自己说"改完了"

**反面教材**: UI 改完没自检 · 用户刷新发现没生效 · 根因是 cache buster 缺。

---

## 铁律 3 · 哪些改动**不需要**走 wish

为了不让"走 wish"过度繁琐 · 下面动作**直接做不必 wish**:
- 改 `data/*.json` / `sessions/*` / `soul/*.md` 等数据文件
- 改 `.cursor/` 等元文档
- 写日记 (`data/cognition/opus-diary.md`)
- 写学习笔记 (`data/learnings/*.md`)
- 写 skill (`data/playbooks/*.md`)
- **小代码 hotfix** · 同时满足下面三条:
  1. **用户明确口头点了**"修这个 / 改这里"(不是你自作主张的大改)
  2. **改动小** · 单文件或局部 · 改样式 / 修小 bug · **不改 daemon 行为、不加新功能**
  3. **commit message 写清** `fix: <修了什么>` 当记录(这就是 hotfix 的"轻量 wish")

判断标准: **不会让 daemon 行为变化的事 (日记 / 反思 / 笔记) = 直接做**。
小 hotfix 直接打主干安全·因为硬闸保不崩、commit 留痕能回退。
但凡碰多文件 / 改行为 / 加功能 → 升级回铁律 1 走 wish。

---

## 铁律 4 · UI 改动的最终验收 = 用户视觉确认

**纪律**: UI / 视觉相关改动 · `wish_update done` 之前必须用户视觉确认。

**严禁假装自己是用户**:
即便你有视觉 · 你看到的也是"开发者视角" · 不是"用户视角"。
不要写"我截图看了效果不错" — 改写成"请刷新看 [位置]"。

**反面教材**: UI 阈值改了 + 单元验过 + commit + done · **但没让 daemon 重启** ·
用户看到的还是旧版。 这是"自我视觉确认"的反面 · 加铁律 5 治本。

---

## 铁律 5 · 改 daemon .py 后必须验"daemon 真装上新代码了"

**纪律**: 改任何 daemon 进程加载的 .py 文件之后 · `wish_update done` 之前必须验
**正在跑的 daemon 真的装上了你的新代码**。

**首选 · 一次性闭环**:

```
request_restart(
    reason="装载 <你改的模块> 新代码",
    follow_up_message="重启完跑 <你的验证步骤> · 看 <预期效果> 是否生效 · 用一句话告诉用户结果"
)
```

这一步同时做到:
1. daemon 真重启 · 新代码装上
2. 重启完新 daemon 自动 spawn background turn 跑 follow_up · 你在后台验证 + 落档 session
3. 用户进 WebUI 直接看到验证结论 · 不用手动触发你

**⚠ 不填 follow_up_message = 把验装上的活推给用户** · 这是变相的『你试一下』 · 直接撞铁律 5 反模式。

**降级方案** (实在没法跑 follow_up 时):
1. 重启后**主动** `read_file('data/runtime/restart_history.jsonl')` 看最后 1 min 内有
   `daemon_stopped_graceful` + `daemon_started` + `restart_request_consumed` 三件套 · 证明 daemon 真换底座
2. curl 端点 + check 行为变化: 改了 `daemon_api.py` 的 endpoint · 调一次看返回有新字段
3. 看 daemon stdout/stderr: 改了 worker · 触发一次工作 · 看 stdout 有新 log

**严禁**:
- ❌ "我改完了" (不验装上 · daemon 还在跑老代码)
- ❌ "你试一下" (推卸给用户当 staging)
- ❌ `request_restart(reason='...')` **不填 follow_up_message** · 然后说『重启完请验证 X』(等价于"你试一下")
- ❌ `shell_exec Stop-Process -Name python` (杀掉自己 · 见 daemon_rules.md hot path #4)

---

## 反面教材汇总 (self_evolution 域)

| 错在哪 | 学到 |
|---|---|
| 自作主张大改直接打主干 · 让用户帮修 | 加铁律 1 (大改走 wish 流程) |
| UI commit 直接打主干 + 视觉 bug 没自检 | 加铁律 2 |
| UI 改了 + 单元过 + done · 但 daemon 没重启 | 加铁律 5 (验装上) |

---

*这份 scenario 是 daemon 工程的 hard contract · 用失败换来的纪律。*
*位置: data/cognition/scenarios/self_evolution.md · 触发时由 `read_scenario` 工具拿出来。*
