#requires -Version 5.1
<#
.SYNOPSIS
  已废弃。再跑会把薄壳覆盖成肉版 exe，双击必报 Add-Log / Visible。

.DESCRIPTION
  用户入口只允许 tools/build-boot-exe.ps1（csc 编 DaemonkeyBoot.cs）。
#>

$ErrorActionPreference = 'Stop'
Write-Host '[X] tools/build-exe.ps1 已废弃 · 拒绝编译' -ForegroundColor Red
Write-Host '    它会把整份启动器打进 exe（ps2exe 肉版）。社区双击会弹 Add-Log / Visible。' -ForegroundColor Yellow
Write-Host '    正确入口: powershell -ExecutionPolicy Bypass -File tools\build-boot-exe.ps1' -ForegroundColor Yellow
exit 1
