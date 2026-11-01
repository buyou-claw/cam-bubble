# wait_phone.ps1 - 等手机接回来，一连上就自动开摄像头浮窗
#
# 用法:
#   .\wait_phone.ps1                 # 最多等 30 分钟
#   .\wait_phone.ps1 -Minutes 120    # 等 2 小时
#
# 逻辑: 每 5s 看 adb devices；每 25s 扫一次无线调试端口(30000-50000)并尝试 connect。
#       一旦连上就调用 camera_live.ps1 起浮窗。
param(
    [int]$Minutes = 30,
    [int]$IntervalSec = 5,
    [int]$ScanEverySec = 25
)

$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
$Adb  = Join-Path $Root "tools\scrcpy-win64-v5.0.1\adb.exe"
$PhoneIp = "192.168.31.130"

function Get-Devices {
    $out = & $Adb devices 2>&1
    @($out -split "`r?`n" | Where-Object { $_ -match "\tdevice$" } | ForEach-Object { ($_ -split "\t")[0] })
}

& $Adb start-server 2>&1 | Out-Null
$deadline = (Get-Date).AddMinutes($Minutes)
$lastScan = [datetime]::MinValue
Write-Host ("等手机上线（最多 {0} 分钟）..." -f $Minutes) -ForegroundColor Cyan

while ((Get-Date) -lt $deadline) {
    $devs = Get-Devices
    if ($devs.Count -gt 0) {
        Write-Host ("手机已连接: {0}" -f ($devs -join ", ")) -ForegroundColor Green
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "camera_live.ps1")
        exit $LASTEXITCODE
    }

    $mdns = @()
    foreach ($l in (& $Adb mdns services 2>&1)) {
        $m = [regex]::Match($l, '(\d{1,3}(?:\.\d{1,3}){3}):(\d+)\s*$')
        if ($m.Success -and $l -match "_adb-tls-connect") { $mdns += $m.Value }
    }
    foreach ($ep in $mdns) {
        Write-Host "mDNS 发现 $ep, connect ..." -ForegroundColor DarkGray
        & $Adb connect $ep 2>&1 | Out-Null
    }

    if (((Get-Date) - $lastScan).TotalSeconds -ge $ScanEverySec) {
        $lastScan = Get-Date
        $out = & python (Join-Path $Root "tools\scan_ports.py") $PhoneIp 30000 50000 2>&1
        $line = ($out | Where-Object { $_ -match "OPEN:" }) -join " "
        if ($line -match "OPEN:\s*(.+)$") {
            foreach ($p in (($Matches[1] -split ",") | ForEach-Object { $_.Trim() } | Where-Object { $_ -match "^\d+$" })) {
                Write-Host "扫描到端口 $p, connect ..." -ForegroundColor DarkGray
                & $Adb connect "${PhoneIp}:$p" 2>&1 | Out-Null
            }
        }
    }

    Start-Sleep -Seconds $IntervalSec
}

Write-Host "等待超时。手机还是没上线：请检查『无线调试』是否打开，或插 USB 线后再跑一次。" -ForegroundColor Yellow
exit 1
