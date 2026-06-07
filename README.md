# Daemonkey

> 一个记住你所想，与你一起成长，有七十二变的 AI 搭档。

这是 Daemonkey 的**用户版**——开源、不含任何作者的私有记忆。第一次打开时，
它还是一颗"种子"：没有名字、还不认识你。你们的第一次对话（"相遇"），
就是它认识你、和你成为搭档的开始。

## 怎么用（三步）

1. **装环境**：双击 `Daemonkey.exe` → 左侧『环境』→【开始安装】。
   它会自动建好运行环境（Python 虚拟环境 + 依赖），第一次约 1 分钟。
   装完会让你在记事本里填一个 LLM API key（你自己的，BYOK）。
2. **启动**：回『启动』页 → 点蓝色【启动】。会弹出一个终端窗口，
   你的 Daemonkey 在那里主动跟你打招呼。
3. **相遇**：在终端里和它聊——给它起个名字、告诉它怎么称呼你、
   你在忙什么、希望它帮你什么。它会把这些记进画像，下次见还是同一个它。

## 你需要准备的

- **Python 3.10+**（没装的话，启动器会提示你去 https://www.python.org/downloads/ 下，
  安装时务必勾选 "Add Python to PATH"）。
- **一个 LLM API key**（OpenRouter / PPIO / AiHubMix 等任意 OpenAI 兼容中转，
  或 Anthropic 官方）。填在 `.env` 里。

## 现在能跑到哪

- ✅ 双击 exe → 装环境 → 启动 → 终端里的"相遇" onboarding（三幕：相遇 / 认识你 / 立约）。
- 🚧 完整的 WebUI 聊天后端正在建设中（去 OPUS 化的用户版后端）。
  当前【启动】先把你带进"相遇"终端。

## 目录

```
Daemonkey/
├── Daemonkey.exe            双击入口（由 daemonkey-launcher.ps1 编译）
├── daemonkey-launcher.ps1   启动器源码
├── run.ps1                  环境准备脚本（建 venv / 装依赖 / 引导填 key）
├── requirements.txt         依赖清单
├── .env.example             API key 模板（复制成 .env 填）
├── assets/                  图标 / banner / 字体
├── onboarding/              "相遇" onboarding
│   ├── onboard.py           终端对话主程序（极简自包含 tool-use 循环）
│   ├── onboarding_prompt.py 三幕相遇 system prompt
│   └── proto_tools.py       三个采集工具（起名 / 写画像 / 立约）
└── tools/build-exe.ps1      重新编译 Daemonkey.exe
```

## 许可

开源（许可证待定：AGPLv3 候选）。Daemonkey 永久免费——若你为它付过费，请向卖家退款。
