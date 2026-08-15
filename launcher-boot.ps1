#requires -Version 5.1
<#
.SYNOPSIS
  Daemonkey 薄壳 (壳肉分离): 定位根目录 → 找肉 → 拉起 → 退出。
  全部 UI/逻辑在 daemonkey-launcher.ps1 (肉) · 改肉不重编本 exe。
  设计原则 (2026-08-15 BRO 拍板):
    - 壳逻辑零环境假设 (不探测 venv / 不查端口) · 才配得上"永不重编"
    - 启动画面 / 托盘 / 面板 / 崩溃自启 / 维修台入口 全在肉里 · 随版本升级
#>
$ErrorActionPreference = 'Continue'
$root = if ($PSScriptRoot) { $PSScriptRoot }
        elseif ($PSCommandPath) { Split-Path -Parent $PSCommandPath }
        else { try { Split-Path -Parent ([System.Reflection.Assembly]::GetEntryAssembly().Location) } catch { (Get-Location).Path } }
Set-Location -Path $root

$meat = Join-Path $root 'daemonkey-launcher.ps1'
if (-not (Test-Path $meat)) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "找不到 daemonkey-launcher.ps1`r`n启动器文件不完整 · 请重新解压完整包。",
        'Daemonkey', [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    exit 1
}

# 拉起肉 · 肉自带 WinForms UI · -WindowStyle Hidden 只遮控制台 · 肉 ShowDialog 自己弹窗
# 2026-08-15 · Start-Process 自身也带 -WindowStyle Hidden (双保险: 防 powershell 控制台窗口闪现)
Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden `
    -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File', ('"' + $meat + '"')) `
    -WorkingDirectory $root
exit 0
