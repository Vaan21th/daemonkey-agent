# Daemonkey

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

> 一个记住你所想，与你一起成长，有七十二变的 AI 搭档。

这是 Daemonkey 的**用户版**——开源、不含任何作者的私有记忆。第一次打开时，
它还是一颗"种子"：没有名字、还不认识你。你们的第一次对话（"相遇"），
就是它认识你、和你成为搭档的开始。

## 怎么用（三步）

1. **装环境**：双击 `Daemonkey.exe` → 左侧『环境』→【开始安装】。
   它会自动建好运行环境（Python 虚拟环境 + 依赖），第一次约 1 分钟。
2. **启动**：回『启动』页 → 点蓝色【启动】。它会在后台起一个本地网页服务，
   并自动打开浏览器。
3. **相遇**：在网页里——
   - 第一次会先让你**填一个 LLM API key**（粘进去点保存即可，不用手动改文件）；
   - 然后你的 Daemonkey 会主动跟你打招呼：给它起个名字、告诉它怎么称呼你、
     你在忙什么、希望它帮你什么。它会把这些记进画像，下次见还是同一个它。

## 你需要准备的

- **Python 3.10+**（没装的话，启动器会提示你去 https://www.python.org/downloads/ 下，
  安装时务必勾选 "Add Python to PATH"）。
- **一个 LLM API key**（OpenRouter / PPIO / AiHubMix 等任意 OpenAI 兼容中转，
  或 Anthropic 官方）。**在网页里填**即可，会自动存进本机 `.env`。

## 现在能跑到哪

- ✅ 双击 exe → 装环境 → 启动 → 浏览器自动打开 → 网页里**填 key** → "相遇" onboarding
  （三幕：相遇 / 认识你 / 立约），全程在网页里完成。
- 🚧 完整 WebUI（工坊 / 看板 / 全套工具）是后续从母版增量去 OPUS 化搬入的方向。
  当前用户版聚焦"完整初始化体验"这条主链路。

## 目录

```
Daemonkey/
├── Daemonkey.exe            双击入口（由 daemonkey-launcher.ps1 编译）
├── daemonkey-launcher.ps1   启动器源码
├── run.ps1                  环境准备脚本（建 venv / 装依赖 / 备 .env）
├── server.py                网页后端（FastAPI：/ui /api/save-key /api/chat …）
├── requirements.txt         依赖清单（openai / fastapi / uvicorn）
├── .env.example             API key 模板（key 也可在网页里填）
├── assets/                  图标 / banner / 字体
├── static/                  网页前端（相遇对话 + key 表单）
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── favicon.ico          浏览器标签页图标
├── onboarding/              "相遇" onboarding
│   ├── onboard.py           终端版对话（原型 · 仍可单独跑）
│   ├── web_loop.py          网页版 tool-use 循环
│   ├── onboarding_prompt.py 三幕相遇 system prompt
│   └── proto_tools.py       三个采集工具（起名 / 写画像 / 立约）
└── tools/build-exe.ps1      重新编译 Daemonkey.exe
```

## 许可

Copyright (c) 2026 vaan21th

本项目采用 **GNU Affero 通用公共许可证 v3.0（AGPL-3.0）** 开源，完整条款见根目录 [LICENSE](LICENSE)。

简单说：

- 你可以自由地**使用、修改、分发**本软件；
- 但**任何修改版——哪怕只是架成网络服务给别人用（不分发也算）——都必须以同样的 AGPL-3.0 协议公开源代码**；
- 必须保留版权声明与许可声明，注明改动。

这条 copyleft 是为了让 Daemonkey 始终对社区开放，挡住"拿去闭源商用"。

Daemonkey 永久免费——若你为它付过费，请向卖家退款。
