# 浏览器白屏自救指南

> 适用症状：专属 Edge 窗口白屏、`browser_act` / `browser_fetch` 操作超时、浏览器自动化无响应。

---

## 为什么会白屏

Daemonkey 有一个**专属 Edge 浏览器**（独立 profile，跟你日常用的 Edge 完全隔离），
浏览器自动化（`browser_act` / `browser_fetch`）通过 CDP（Chrome DevTools Protocol）连它操作。

白屏的根因是：专属 Edge **崩溃后**,残留的僵尸进程还占着 profile 的**单实例锁**（`SingletonLock`），
之后所有重拉新 Edge 的尝试都撞上这个锁，新进程把请求转发给僵尸后静默退出——所以看起来"白屏"，重启 daemon 也救不回来。

**从 v0.7.6 起**,daemon 已经内置了自愈逻辑：每次用 CDP 前自动检测浏览器是否"半死"
（主进程活着但渲染全崩），是则自动杀僵尸、清锁、重拉。**正常使用不会再遇到白屏。**

---

## 自救步骤（按优先级）

### 方法 ① — 启动器一键急救（推荐）

1. 打开 Daemonkey 启动器 → 左边导航点 **「急救」**
2. 点击 **「浏览器急救」** 按钮
3. 看到右侧日志 `已清掉 X 个残留浏览器进程 + 单实例锁` → 搞定
4. 下次用浏览器自动化时会自动重拉，窗口恢复正常

### 方法 ② — 手动 PowerShell 命令

如果启动器打不开，在 PowerShell 里跑：

```powershell
cd F:\Desktop\Daemonkey
$p = 'sessions\edge_cdp_profile'
Get-CimInstance Win32_Process -Filter "Name='msedge.exe' or Name='chrome.exe'" |
  Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($p.ToLower()) } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep 2
Remove-Item "$p\SingletonLock","$p\SingletonSocket","$p\SingletonCookie" -Force -ErrorAction SilentlyContinue
Write-Host '浏览器急救完成 · 下次用自动化时会自动重拉'
```

### 方法 ③ — 重启电脑（兜底）

方法 ①② 搞不定时（极少见——说明 profile 本身损坏了）：重启电脑即可。
重启后所有进程清空，专属 Edge 从零重建。

---

## 注意事项

- **不需要重启电脑**——方法 ①② 在 99% 的情况下就能解决
- **不会影响你的日常浏览器**——急救只杀命令行里带 `sessions\edge_cdp_profile` 路径的进程
- 专属 Edge 里的登录态（豆包/知乎等）保存在 profile 里，不会被清掉
