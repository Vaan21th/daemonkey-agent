# 在 macOS / Linux 上启动 Daemonkey

> Daemonkey 当前主力形态是 **Windows 桌面**（双击 `Daemonkey.exe`）。
> macOS / Linux 用户照这份说明，一条命令把 WebUI 跑起来。
> **实验性**——核心启动链已在 Linux POSIX 实测通过；mac 因与 Linux 高度同源，WebUI 可起，少数 Windows 专属能力暂未适配（见下方表格）。

---

## 一、先准备好两样东西

**1) Python 3.10 或更新**

- **macOS**：`brew install python`（没有 Homebrew 先去 https://brew.sh 装）
- **Ubuntu / Debian**：`sudo apt install -y python3 python3-venv python3-pip`
- 验证：终端执行 `python3 --version`，看到 `3.10` 或更高即可。

**2) 一个 LLM API key**

OpenRouter / PPIO / AiHubMix 等任意 OpenAI 兼容中转，或 Anthropic / DeepSeek / 智谱 GLM 官方，任选其一。
**现在不用填**——启动后在网页里粘贴保存即可，自动写进本机 `.env`。

---

## 二、启动（一条命令）

在 Daemonkey 文件夹里打开终端，执行：

```bash
chmod +x start.sh && ./start.sh
```

第一次会自动：

1. 建 Python 虚拟环境 `.venv`
2. 装依赖（约 1–2 分钟，国内自动走清华镜像、海外自动回退默认 PyPI）
3. 起本地服务，并自动打开浏览器到 `http://127.0.0.1:7860/ui`

之后再启动直接 `./start.sh`，几秒即起。

---

## 三、起来之后

浏览器里会看到 Daemonkey 的「相遇」页：

1. 先**填一个 LLM API key**（粘进去保存，不用手改文件）；
2. 然后它会主动跟你打招呼——给它起名字、告诉它怎么称呼你、你在忙什么、希望它帮你做什么；
3. 这些会记进画像，下次见还是同一个它。

**停止**：回到运行 `start.sh` 的终端，按 `Ctrl-C`。

---

## 四、想换端口？

默认 `7860`。若被占用，指定别的端口：

```bash
OPUS_API_PORT=7888 ./start.sh
```

---

## 五、哪些能用 / 哪些暂时不能

| 能用（已验证） | 暂时不能（Windows 专属，未适配） |
|---|---|
| WebUI 对话 | 桌宠（屏幕上的小宠物） |
| 6 层记忆 / 画像 | 剪贴板读写 |
| 工坊 / 报告 / 信息雷达 | 打开本地应用 |
| 定时任务 / 主动联系 | 一键维修台 / 回档（`.bat`） |

这些不影响你和 Daemonkey 聊天，以及用它的核心能力。

---

## 六、常见问题

- **`command not found: python3`** → 没装 Python，见第一节。
- **装依赖卡住 / 失败** → 多半是网络。脚本会先试清华镜像、再回退默认 PyPI；仍不行就检查代理 / 网络。
- **浏览器没自动打开** → 手动打开终端里打印的那个 `http://127.0.0.1:7860/ui`。
- **端口被占用** → 用 `OPUS_API_PORT=别的端口 ./start.sh`。
- **想完全重来** → 删掉文件夹里的 `.venv` 目录，再跑一次 `./start.sh` 即可重建环境。

---

## English quickstart

```bash
chmod +x start.sh && ./start.sh
```

Needs **Python 3.10+** (`brew install python` on macOS). First run builds a venv, installs deps, starts the local service and opens your browser at `http://127.0.0.1:7860/ui`. Paste an LLM API key in the web UI, then it greets you. Stop with `Ctrl-C`. Change the port via `OPUS_API_PORT=7888 ./start.sh`.

Windows-only features (desktop pet, clipboard, open-app, the repair / rollback `.bat`s) aren't ported yet, but they don't affect core chat / memory / studio. Startup is verified on Linux POSIX; macOS is highly similar and the WebUI runs, hence *experimental* until a native-mac smoke test lands.
