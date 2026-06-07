# scenarios · 场景化铁律细则

> 解决「注意力稀释 + 铁律打架」问题。
>
> system prompt 顶部 (`daemon_rules.md`) 只放工艺纪律 + 铁律 0 (入口路由) +
> 场景索引表 (一句话纪律)。 完整细则按 domain 拆到这里·LLM 触发时调
> `read_scenario` 工具按需读取。

---

## 现有 scenarios

| domain | 文件 | 触发关键词 | 涉及铁律 |
|---|---|---|---|
| self_evolution | `self_evolution.md` | 改 daemon .py · 改 static · "改这个工具" · "重写 worker" | 铁律 0 / 1 / 2 / 3 / 4 / 5 |
| app_creation | `app_creation.md` | "建一个 X 应用" · "排个 X 工作流" · "提炼 skill" · 装 API key | 铁律 6 / 7 |

## 未来 scenarios (用 add_iron_rule 时建)

| domain | 用途 | 状态 |
|---|---|---|
| workflow_creation | 跟 app_creation 区分细 (当前合并在 app_creation) | 待拆 |
| production | 生产环境 (服务器部署 / 远程访问) | 待立 |
| reflection | 复盘 / 月度 review / 自我演化 | 待立 |

---

## 怎么用 (LLM 视角)

1. 看 system prompt 末尾的"场景索引"section
2. 根据当前任务匹配触发关键词
3. 调 `read_scenario(name='<domain>')` 拿到完整细则
4. 按细则执行

**预算**:
- 不触发时: system prompt ~+400 字索引开销
- 触发一次 self_evolution: +~3000 字 (单 turn 内有效)
- 触发一次 app_creation: +~2500 字 (单 turn 内有效)
- 比"全部铁律每 turn 强读" 节省 70-80%

---

## 怎么加新 scenario (将来)

1. 用 `add_iron_rule` 加新铁律 + 指定 domain
2. 在 `data/cognition/scenarios/` 下新建 `<domain>.md` · 抄 self_evolution.md layout
3. 把对应 domain 的铁律细则整理到 scenario md
4. 更新 daemon_rules.md 场景索引表 + 本 README 表格
5. 更新 `agent_tools/read_scenario.py` enum (加新 domain)
