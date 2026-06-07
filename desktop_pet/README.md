# 桌宠 v0.1.2

> 情绪通道 · 像素小猫 · 在你桌面上自己走路、伸爪、跳起来 · 实时反映 daemon 在干什么

---

## 启动

```powershell
# 先装桌宠依赖（只用装一次）
.venv\Scripts\python.exe -m pip install PyQt6

# 启桌宠
.venv\Scripts\python.exe -m desktop_pet.pet
```

也可以直接在启动器里点「召唤桌宠」。桌宠和 daemon 互相独立，谁先启都行；同时跑时桌宠会反映 daemon 的活动（"心电图"）。

> **没有 sprite 图也能跑**：默认用颜文字 / emoji 小猫（🐈）作 fallback。想要像素猫贴图，见下面「sprite 是怎么来的」。

---

## 操作

| 操作 | 效果 |
|---|---|
| 鼠标左键拖动 | 移动整个桌宠（可拖到副屏） |
| **双击** | 弹出对话框，输入直接写到 `inbox.txt` |
| 右键 | 弹出菜单：表情切换 / 回到屏幕中下方 / 退出 |

---

## 8 种表情

| state | 含义 |
|---|---|
| `idle` | 默认 / 待机 |
| `thinking` | 思考中 |
| `working` | 专注工作 |
| `happy` | 开心 / 完成任务 |
| `surprised` | 惊讶 / 截屏 |
| `confused` | 困惑 |
| `sleepy` | 提醒你休息 |
| `greeting` | 打招呼 |

---

## 它怎么和 daemon 通信？

**文件桥**（`desktop_pet/` 下，运行时自动生成，已 gitignore）：

| 文件 | 方向 | 写者 | 读者 | 用途 |
|---|---|---|---|---|
| `state.txt` | daemon → pet | `set_emotion` 工具 | pet 每 1s 检查 | OPUS 主动表达情绪（30s stale） |
| `activity.txt` / `activity.jsonl` | daemon → pet | tool_loop 自动 | pet 每 1s 检查 | OPUS 在干什么的"心电图" |
| `inbox.txt` | pet → daemon | 桌宠双击对话框 | daemon 主循环 | 你通过桌宠对 OPUS 说话 |
| `position.txt` | pet self | pet 走动时 | pet 启动时 | 记住桌宠最后位置 |

任意一个进程崩溃另一个不受影响。

---

## sprite 是怎么来的？（可选）

1. 用任意 AI 画图工具跑 sprite sheet → 落在项目根目录 `fps/raw_<action>.png`
2. 跑 `tools/process_sprites.py` 自动切片（按网格等分 / 抠背景 / 缩放到 96×96 / 生成 `sprites/manifest.json`）
3. pet 启动读 manifest，自动用上新 sprite

不做这步也没关系——桌宠会用颜文字小猫继续陪你。

---

## 夜晚模式

`_is_night()` 检查到凌晨 2-5 点时桌宠走路速度减慢——夜里不太闹腾。
