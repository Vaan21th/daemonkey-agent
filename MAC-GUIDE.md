# Daemonkey · macOS 使用指南

> Daemonkey 是一款运行在本地、开源免费的 AI 搭档：持续记忆、工具调用、可视化对话（WebUI）、自我升级。
> 本指南写给 Mac 用户。当前 Mac 版有两种启动方式：
>
> - **方式 A · 终端一键启动**（`start.sh` · 现在就能用）
> - **方式 B · 图形启动器**（把 `Daemonkey.app` 放进这份代码的根目录，和 `tools/` 同级，再双击。不要只把 `.app` 单独丢进「应用程序」）

---

## 方式 A · 终端一键启动（现在就能用）

**1. 装 Python 3.10+**（已装可跳过）

打开「终端」（访达 → 应用程序 → 实用工具 → 终端），粘贴：

```bash
brew install python
```

> 没有 Homebrew？先去 https://brew.sh 按提示装一行命令即可。

**2. 下载代码**

```bash
git clone https://gitee.com/vaan21th/dae-monkey.git
cd dae-monkey
```

**3. 一键启动**

```bash
chmod +x start.sh
./start.sh
```

脚本会自动：建虚拟环境 → 装依赖（首次 1-2 分钟）→ 起服务 → 打开浏览器。

**4. 首次使用（相遇）**

浏览器打开 `http://127.0.0.1:7860/ui` 后：

1. 填一个 **API Key**（DeepSeek / Kimi / GLM / OpenAI 等任意兼容的，在各自官网申请）
2. 给它**起个名字**、告诉它怎么称呼你——它会记住你（跨会话持久记忆）
3. 之后就可以对话了：问问题、让它写代码、看报告、用各种工具

**5. 停止**

回到终端按 `Ctrl-C`。

---

## 方式 B · 图形启动器 Daemonkey.app

皮和 Windows 是同一份 `assets/launcher.html`（月光操作台）。壳是 Mac 的 `Daemonkey.app`（WKWebView），不是 Windows 那个 exe。

**正确摆法（认根目录，不再写死家目录）：**

1. 把整份 Daemonkey 文件夹拷到 Mac（任意位置都行，例如 `~/Desktop/Daemonkey`）
2. 把 `Daemonkey.app` 放进**这个文件夹的根**，和 `tools/run_api_only.py` 同级
3. 右键 `.app` →「打开」（未签名，Gatekeeper 会拦一次）
4. 点【启动 daemon】

启动器按这个顺序找代码根：

1. 环境变量 `DAEMONKEY_HOME` / `OPUS_DAEMON_DIR`
2. **装着 `.app` 的那一层**（所以放进纯净版根就能用这份 1.0.0）
3. 旁边再套一层 `Daemonkey/`
4. `~/Daemonkey`
5. 以上都没有，才 clone Gitee（远端还是旧 master，不是桌上这份 1.0.0）

旁边已经有根目录、也有 `.venv` 时，不再每次 `pip install`。
首次装依赖和终端 `start.sh` 一样：先清华源 `pypi.tuna.tsinghua.edu.cn`，不通再官方 PyPI。

**不要做的：**

- 只把 `.app` 拖进「应用程序」、旁边没有代码 → 找不到 1.0.0，会去家目录或拉 Gitee 旧仓
- 只拷 dmg、不拷源码文件夹 → 同样不是桌上这份 1.0.0

---

## 首次使用会发生什么（相遇流程）

无论哪种方式，首次打开 WebUI 都会走一遍「相遇」：

| 步骤 | 做什么 |
|---|---|
| 填 Key | 粘贴你的 LLM API Key（本地保存·不上传） |
| 起名字 | 给你的 AI 搭档取名字（比如"小悟"） |
| 认识你 | 它问你几个问题·建立你的画像·之后跨会话记得你 |
| 开聊 | 对话式使用：问问题 / 让它干活 / 看趋势报告 |

> 数据全在本地：对话、记忆、画像都存你这台 Mac 上·不上传任何云端。

---

## 常见问题

**Q：提示"无法打开，因为无法验证开发者"？**
A：这是 macOS 对未签名应用的正常提示。右键 → 打开 → 仍要打开（或系统设置 → 隐私与安全性 → 仍要打开）。只此一次。

**Q：我的 Mac 是 Intel 还是 Apple Silicon？**
A：点左上角  → 关于本机。Apple Silicon（M1/M2/M3/M4）用 **arm64** 包原生跑；Intel 用 **x86_64** 包。图形启动器下载时认准对应架构。

**Q：哪些功能和 Windows 对齐了？哪些还不行？**
A：对话 / 记忆 / 工坊 / 剪贴板 / 开应用（Chrome、微信等走 `open -a`）/ 浏览器手眼（本机 Chrome/Edge，没有则启动器拉 Chromium）已经能用。成品预览有 LibreOffice 就行（`brew install --cask libreoffice`）。录屏要 `brew install ffmpeg` 并打开「屏幕录制」权限。桌宠能从启动器拉开，透明穿透还没 Windows 细。OfficeCOM / OfficeCLI / Windows 通知仍然是 Windows 的。

**Q：端口 7860 被占用？**
A：改端口启动：`OPUS_API_PORT=7861 ./start.sh`（源码方式）。

**Q：怎么更新？**
A：源码方式：`cd dae-monkey && git pull && ./start.sh`。图形启动器：启动器自带自更新检查（启动时自动查新版）。

**Q：装依赖太慢 / 网络问题？**
A：start.sh 已内置清华镜像加速（国内友好）；自动失败会切回官方 PyPI。

---

## 社群与贡献

有 Mac 使用问题 / 想参与贡献？进社群说一声（贡献者名单会更新）。

- 项目：https://gitee.com/vaan21th/dae-monkey （开源 · AGPL 方向）
- 免费声明：Daemonkey 永久免费的个人 AI

---

*Daemonkey · an AI that doesn't say goodbye.*
