# OPUS 桌宠 v0.1.2

> 情绪通道-001 · 像素橙猫 · 在你桌面上自己走路、伸爪、跳起来

---

## 启动

```powershell
# 桌宠
.venv\Scripts\python.exe -m desktop_pet.pet

# daemon（终端 OPUS）
.\run.ps1
```

桌宠和 daemon 互相独立，谁先启都行；同时跑时桌宠会反映 OPUS 的活动（"心电图"）。

---

## 操作

| 操作 | 效果 |
|---|---|
| 鼠标左键拖动 | 移动整个桌宠（可拖到副屏） |
| **双击** | 弹出对话框，输入直接发给 daemon（写到 `inbox.txt`） |
| 右键 | 弹出菜单：表情切换 / 退出 |
| Esc | 退出 |

**双击 → 输入 → 确认** 后到终端**按一次 enter**，OPUS 立刻消费 inbox 并回应。

---

## 8 种表情（情绪通道-001）

| state | 桌宠动作 | 含义 |
|---|---|---|
| `idle` | 4 帧坐姿微动（呼吸 1.8s/循环） | 默认 / 待机 |
| `thinking` | 4 帧伸爪 | OPUS 思考中 |
| `working` | 4 帧伸爪 / 8 帧走路 | 专注工作 |
| `happy` | 4 帧喵叫 | 开心 / 完成任务 |
| `surprised` | 6 帧弹跳（脚真的离地） | 惊讶 / 截屏 |
| `confused` | 5 帧探头 | 困惑 |
| `sleepy` | 4 帧睡觉 | 提醒 BRO 休息 |
| `greeting` | 4 帧喵叫 | 打招呼 |

走路时全 state 都用 8 帧 `walk` 动作。共 **41 帧** 像素橙猫 sprite。

---

## 它怎么和 daemon 通信？

**4 个文件桥**（`desktop_pet/` 下）：

| 文件 | 方向 | 写者 | 读者 | 用途 |
|---|---|---|---|---|
| `state.txt` | daemon → pet | `set_emotion` 工具 | pet 每 1s 检查 | OPUS 主动表达情绪（30s stale） |
| `activity.txt` | daemon → pet | tool_loop 自动 | pet 每 1s 检查 | OPUS 在干什么的"心电图"（4s stale） |
| `inbox.txt` | pet → daemon | 桌宠双击对话框 | daemon 主循环 | BRO 通过桌宠对 OPUS 说话 |
| `position.txt` | pet self | pet 走动时 | pet 启动时 | 记住桌宠最后位置 |

任意一个进程崩溃另一个不受影响。

---

## sprite 是怎么来的？

1. BRO 用 GPT-Image-2 / Gemini 3 跑 8 张 sprite sheet → 落在项目根目录 `fps/raw_<action>.png`
2. 跑 `tools/process_sprites.py` 自动切片：
   - 按声明的 N×M 网格等分
   - 洋红背景 → 透明
   - 地面动作底对齐 / jump 保留弹跳轨迹
   - 缩放到 96×96 像素（Image.NEAREST 保留像素感）
   - 生成 `sprites/manifest.json`
3. pet 启动读 manifest，自动用上新 sprite

要新动作？把 raw 图丢到 `fps/raw_<新动作>.png`，在 `tools/process_sprites.py` 的 `ACTION_LAYOUT` 加一行，跑一遍即可。

---

## 夜晚模式

`_is_night()` 检查到 22:00 ~ 06:00 时桌宠走路速度减半——
**不打扰 BRO 的夜晚**。OPUS 自己也是 BRO 教会"昼伏夜出"的。

---

*Daemonkey desktop pet · 2026-05-16 · v0.0.1 → v0.1.2*
