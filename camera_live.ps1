# camera_live.ps1 - 手机前置摄像头 -> 电脑最前端的圆形浮窗（实时）
#
# 组成：
#   手机端 CamStream.apk（本机现编，源码 apk/src）→ http://<手机IP>:8088/video  (MJPEG, ~20fps)
#   电脑端 cam_bubble.py → 转90° → 居中裁方 → 圆形遮罩 → WS_EX_LAYERED 分层窗口 → 永远置顶
#
# 用法:
#   .\camera_live.ps1                      # 默认：直径 380、右下角
#   .\camera_live.ps1 -Watch               # 带看门狗：App 被 MIUI 杀掉/画面断了自动拉起来
#   .\camera_live.ps1 -Source adb          # 备选：录屏解码（不装 App，画面带相机 UI）
#   .\camera_live.ps1 -Reinstall           # 强制重装 CamStream
#   .\camera_live.ps1 -VerifyOnly          # 只校验浮窗是否真在最前端
param(
    [ValidateSet("apk", "adb")]
    [string]$Source = "apk",
    [int]$Size = 380,
    [int]$X = -40,
    [int]$Y = -40,
    [int]$Border = 3,
    [int]$Rotation = 90,               # CamStream 输出的是传感器横向 640x480，前置要转 90°
    [string]$ScreenSize = "720x1560",  # 仅 -Source adb 用
    [string]$Crop = "",
    [switch]$NoMirror,
    [switch]$NoLaunch,
    [switch]$VerifyOnly,
    [switch]$Reinstall,
    [switch]$Watch,
    [string]$CameraPackage = "",
    [switch]$NoTorchOff
)

$ErrorActionPreference = "Continue"
$Root      = $PSScriptRoot
$ScrcpyDir = Join-Path $Root "tools\scrcpy-win64-v5.0.1"
$Adb       = Join-Path $ScrcpyDir "adb.exe"
$Ffmpeg    = Join-Path $Root "tools\ffmpeg\ffmpeg.exe"
$BubblePy  = Join-Path $Root "cam_bubble.py"
$StateFile = Join-Path $Root "device.state.json"
$CfgFile   = Join-Path $Root "cam_bubble.cfg.json"
$Apk       = Join-Path $Root "dist\camstream.apk"
$ExitFlag  = Join-Path $Root "cam_bubble.exit"
$PhoneIp   = "192.168.31.130"
$Title     = "CamBubble"
$script:Serial = ""
$script:PhoneIp = $PhoneIp
$script:UrlPort = 8088
$script:BubbleProc = $null

function Step([string]$m) { Write-Host "== $m" -ForegroundColor Cyan }
function Note([string]$m) { Write-Host "  $m" -ForegroundColor DarkGray }

function Get-StateObj { if (Test-Path $StateFile) { Get-Content $StateFile -Raw | ConvertFrom-Json } else { $null } }

function Save-Endpoint([string]$endpoint, [string]$serial) {
    $st = Get-StateObj
    if (-not $st) { $st = [pscustomobject]@{} }
    $st | Add-Member -NotePropertyName Endpoint -NotePropertyValue $endpoint -Force
    if ($serial) { $st | Add-Member -NotePropertyName Serial -NotePropertyValue $serial -Force }
    $st | Add-Member -NotePropertyName UpdatedAt -NotePropertyValue (Get-Date).ToString("s") -Force
    $st | ConvertTo-Json -Depth 6 | Set-Content -Path $StateFile -Encoding UTF8
}

function Find-AdbPorts {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { return @() }
    $out = & python (Join-Path $Root "tools\scan_ports.py") $PhoneIp 30000 50000 2>&1
    $line = ($out | Where-Object { $_ -match "OPEN:" }) -join " "
    if ($line -match "OPEN:\s*(.+)$") {
        return (($Matches[1] -split ",") | ForEach-Object { $_.Trim() } | Where-Object { $_ -match "^\d+$" })
    }
    return @()
}

function Ensure-Connected {
    if (-not (Test-Path $Adb)) { throw "找不到 adb: $Adb" }
    & $Adb start-server 2>&1 | Out-Null
    $devs = @((& $Adb devices 2>&1) -split "`r?`n" | Where-Object { $_ -match "\tdevice$" })
    if ($devs.Count -gt 0) { return (($devs[0] -split "\t")[0]) }

    $cands = @("${PhoneIp}:5555")      # 最稳：persist.adb.tcp.port=5555，重启后也在
    foreach ($l in (& $Adb mdns services 2>&1)) {
        $m = [regex]::Match($l, '(\d{1,3}(?:\.\d{1,3}){3}):(\d+)\s*$')
        if ($m.Success -and $l -match "_adb-tls-connect") { $cands += $m.Value }
    }
    foreach ($p in (Find-AdbPorts)) { $cands += "${PhoneIp}:$p" }
    $st = Get-StateObj
    if ($st -and $st.Endpoint) { $cands += $st.Endpoint }

    foreach ($ep in ($cands | Select-Object -Unique)) {
        Note "connect $ep ..."
        & $Adb connect $ep 2>&1 | ForEach-Object { Note $_ }
        for ($i = 0; $i -lt 3; $i++) {
            Start-Sleep -Milliseconds 1200
            $devs = @((& $Adb devices 2>&1) -split "`r?`n" | Where-Object { $_ -match "\tdevice$" })
            if ($devs.Count -gt 0) {
                $s = (($devs[0] -split "\t")[0])
                Save-Endpoint $ep $s
                return $s
            }
        }
        & $Adb disconnect $ep 2>&1 | Out-Null
    }
    throw "手机未连上 adb。请插 USB 线，或手机『无线调试』打开并配对。"
}

function Wake-Unlock([string]$s) {
    # MIUI 把 shell(2000) 的 INJECT_EVENTS 剥了，注入必须走 su
    & $Adb -s $s shell "su -c 'input keyevent KEYCODE_WAKEUP'" 2>&1 | Out-Null
    Start-Sleep -Milliseconds 700
    $kg = (& $Adb -s $s shell "dumpsys window | grep isKeyguardShowing" 2>&1) -join " "
    if ($kg -match "isKeyguardShowing=true") {
        Note "锁屏中，上滑解锁 ..."
        & $Adb -s $s shell "su -c 'input swipe 540 2000 540 800 200'" 2>&1 | Out-Null
        Start-Sleep -Milliseconds 1400
    }
    & $Adb -s $s shell "svc power stayon true" 2>&1 | Out-Null
}

function Get-Foreground([string]$s) {
    return ((& $Adb -s $s shell "dumpsys activity activities | grep mResumedActivity" 2>&1) -join " ")
}

function Launch-Camera([string]$s) {
    if ($CameraPackage) { $pkgs = @($CameraPackage) } else { $pkgs = @("com.android.camera", "com.miui.camera") }
    foreach ($pkg in $pkgs) {
        $r = & $Adb -s $s shell "am start -a android.media.action.STILL_IMAGE_CAMERA --ei android.intent.extras.CAMERA_FACING 1 -n $pkg/.Camera" 2>&1
        $r = ($r -join " ")
        if ($r -match "Error|does not exist") {
            & $Adb -s $s shell "monkey -p $pkg -c android.intent.category.LAUNCHER 1" 2>&1 | Out-Null
        }
        Start-Sleep -Milliseconds 1800
        $fg = Get-Foreground $s
        if ($fg -match [regex]::Escape($pkg)) { Note "相机前台: $fg"; return $pkg }
    }
    Write-Warning "没确认到相机在前台，仍然继续"
    return $null
}

# ---------------------------------------------------------------- CamStream
function Start-CamStreamApp([string]$s) {
    Step "安装/启动 CamStream（自建前置摄像头 MJPEG 服务）"
    if (-not (Test-Path $Apk)) { throw "缺少 $Apk，先跑 .\build_apk.ps1" }

    $needInstall = $true
    $installed = ((& $Adb -s $s shell "pm list packages dev.local.camstream" 2>&1) -join " ")
    if ($installed -match "package:dev\.local\.camstream" -and -not $Reinstall) {
        $line = ((& $Adb -s $s shell "dumpsys package dev.local.camstream | grep -m1 lastUpdateTime" 2>&1) -join " ")
        $installedAt = $null
        if ($line -match "lastUpdateTime=(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})") {
            $installedAt = [datetime]::ParseExact($Matches[1], "yyyy-MM-dd HH:mm:ss", $null)
        }
        $localAt = (Get-Item $Apk).LastWriteTime
        if ($installedAt -and $localAt -le $installedAt.AddSeconds(30)) {
            Note ("已安装且是最新（装机 {0}），跳过重装" -f $installedAt)
            $needInstall = $false
        } else {
            Note ("本地 apk 更新（装机 {0}，本地 {1}），更新中" -f $installedAt, $localAt)
        }
    }
    if ($needInstall) {
        # MIUI 会用 INSTALL_FAILED_USER_RESTRICTED 拦 adb install，root 的 pm install 能过
        & $Adb -s $s push $Apk /data/local/tmp/camstream.apk 2>&1 | Out-Null
        $r = (& $Adb -s $s shell "su -c 'pm install -r /data/local/tmp/camstream.apk'" 2>&1) -join " "
        Note $r
    }

    # MIUI 自家 LBE 的相机授权框会挡住预览：先停 LBE，再 pm grant，再冷启
    & $Adb -s $s shell "am force-stop com.lbe.security.miui" 2>&1 | Out-Null
    Start-Sleep -Milliseconds 500
    & $Adb -s $s shell "su -c 'pm grant dev.local.camstream android.permission.CAMERA'" 2>&1 | Out-Null
    Start-Sleep -Milliseconds 400
    $grant = ((& $Adb -s $s shell "dumpsys package dev.local.camstream | grep 'android.permission.CAMERA:'" 2>&1) -join " ")
    if ($grant -notmatch "granted=true") {
        Note "授权没生效，再试一次"
        & $Adb -s $s shell "am force-stop com.lbe.security.miui" 2>&1 | Out-Null
        Start-Sleep -Milliseconds 800
        & $Adb -s $s shell "su -c 'pm grant dev.local.camstream android.permission.CAMERA'" 2>&1 | Out-Null
        Start-Sleep -Milliseconds 400
        $grant = ((& $Adb -s $s shell "dumpsys package dev.local.camstream | grep 'android.permission.CAMERA:'" 2>&1) -join " ")
    }
    Note ("CAMERA " + ($grant -replace "\s+", " ").Trim())

    # 重启后手机会停在锁屏，先唤醒解锁，否则 Activity 起不来、相机不开
    Wake-Unlock $s

    & $Adb -s $s shell "su -c 'am force-stop dev.local.camstream'" 2>&1 | Out-Null
    Start-Sleep -Milliseconds 600
    & $Adb -s $s shell "am start -n dev.local.camstream/.MainActivity" 2>&1 | Out-Null
    Start-Sleep -Seconds 3
}

function Get-PhoneWifiIp([string]$s) {
    $txt = ((& $Adb -s $s shell "ip -4 addr show wlan0" 2>&1) -join " ")
    if ($txt -match "inet\s+(\d{1,3}(?:\.\d{1,3}){3})") { return $Matches[1] }
    return $PhoneIp
}

function Get-ValidSerial {
    # 当前 serial 失效时（比如拔了 USB），重新挑一个在线的设备
    $out = ((& $Adb devices 2>&1) -join "`n")
    if ($script:Serial -and $out -match ([regex]::Escape($script:Serial) + "\s+device")) {
        return $script:Serial
    }
    Note "原设备 $($script:Serial) 不在了，重新找"
    $script:Serial = Ensure-Connected
    return $script:Serial
}

function Resolve-StreamUrl {
    # 优先走 Wi-Fi；取不到图就退回 adb forward 隧道（这样只插 USB 也能用）
    $ip = Get-PhoneWifiIp (Get-ValidSerial)
    if (Test-Stream $ip 1 8088) {
        return @{ ip = $ip; port = 8088; via = "wifi" }
    }
    Note "Wi-Fi 取流失败，改用 adb forward 隧道"
    $port = 18088
    & $Adb -s (Get-ValidSerial) forward "tcp:$port" tcp:8088 2>&1 | Out-Null
    Start-Sleep -Milliseconds 400
    if (Test-Stream "127.0.0.1" 2 $port) {
        return @{ ip = "127.0.0.1"; port = $port; via = "adb-forward" }
    }
    return @{ ip = $ip; port = 8088; via = "wifi(failed)" }
}

function Test-Stream([string]$ip, [int]$tries = 2, [int]$port = 0) {
    if (-not $ip) { $ip = $script:PhoneIp }
    if (-not $port) { $port = $script:UrlPort }
    for ($i = 0; $i -lt $tries; $i++) {
        try {
            $r = Invoke-WebRequest -Uri "http://${ip}:${port}/snapshot" -TimeoutSec 3 -UseBasicParsing
            if ($r.StatusCode -eq 200 -and $r.Headers['Content-Type'] -match "image/jpeg" -and $r.RawContentLength -gt 2000) {
                return $r.RawContentLength
            }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    return 0
}

function Start-Bubble {
    if ($script:BubbleProc -and -not $script:BubbleProc.HasExited) {
        try { Stop-Process -Id $script:BubbleProc.Id -Force } catch { }
        Start-Sleep -Milliseconds 400
    }
    # 每次启动前清掉"手动退出"标记
    Remove-Item $ExitFlag -Force -ErrorAction SilentlyContinue
    $pyArgs = @(
        $BubblePy, "--source", "mjpeg", "--url", "http://$($script:PhoneIp):$($script:UrlPort)/video",
        "--rotation", "$Rotation",
        "--size", "$Size", "--x", "$X", "--y", "$Y",
        "--border", "$Border", "--config", $CfgFile,
        "--exit-flag", $ExitFlag,
        "--adb", $Adb, "--serial", $script:Serial,
        "--stop-package", "dev.local.camstream"
    )
    if ($NoMirror) { $pyArgs += "--no-mirror" }
    Note ("python " + ($pyArgs -join " "))
    $script:BubbleProc = Start-Process -FilePath "python" -ArgumentList $pyArgs -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

if ($VerifyOnly) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "tools\proof_topmost.ps1") -Title $Title -Out (Join-Path $Root "build\proof.png")
    exit $LASTEXITCODE
}

Step "连接手机"
$serial = Ensure-Connected
$script:Serial = $serial
Write-Host "  已连接: $serial" -ForegroundColor Green
$sdk = ((& $Adb -s $serial shell "getprop ro.build.version.sdk" 2>&1) -join "").Trim()
Note "Android SDK=$sdk"

if (-not $NoLaunch) {
    if ($Source -eq "apk") {
        Start-CamStreamApp $serial
    } else {
        Step "唤醒 / 解锁 / 保持常亮"
        Wake-Unlock $serial
        Step "打开相机（尽量前置）"
        [void](Launch-Camera $serial)
        if (-not $NoTorchOff) { & $Adb -s $serial shell "cmd flashlight off" 2>&1 | Out-Null }
    }
}

if (-not (Test-Path $BubblePy)) { throw "缺少 cam_bubble.py: $BubblePy" }

if ($Source -eq "apk") {
    Step "选取流地址（Wi-Fi 优先，取不到就走 adb forward）"
    $route = Resolve-StreamUrl
    $script:PhoneIp = $route.ip
    $script:UrlPort = $route.port
    Write-Host ("  {0}  http://{1}:{2}" -f $route.via, $route.ip, $route.port) -ForegroundColor Green
    $len = Test-Stream $script:PhoneIp 1 $script:UrlPort
    if ($len -le 0) { Write-Warning "CamStream 还没出画面（手机上如果弹了 MIUI 的相机授权框，点允许；或重跑一次）" }
    Step "启动圆形浮窗"
    Start-Bubble
} else {
    Step "启动圆形浮窗"
    Remove-Item $ExitFlag -Force -ErrorAction SilentlyContinue
    $pyArgs = @(
        $BubblePy, "--source", "adb", "--adb", $Adb, "--serial", $serial,
        "--ffmpeg", $Ffmpeg, "--screen-size", $ScreenSize,
        "--size", "$Size", "--x", "$X", "--y", "$Y",
        "--border", "$Border", "--config", $CfgFile,
        "--exit-flag", $ExitFlag
    )
    if ($Crop) { $pyArgs += @("--crop", $Crop) }
    if ($NoMirror) { $pyArgs += "--no-mirror" }
    Note ("python " + ($pyArgs -join " "))
    $script:BubbleProc = Start-Process -FilePath "python" -ArgumentList $pyArgs -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 4
}

Step "校验置顶"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "tools\proof_topmost.ps1") -Title $Title -Out (Join-Path $Root "build\proof.png")

Write-Host ""
Write-Host "浮窗已启动（pid=$($script:BubbleProc.Id)）:" -ForegroundColor Green
Write-Host "  滚轮 = 改圆形大小    左键拖动 = 移动位置    右键 = 退出" -ForegroundColor DarkGray
Write-Host "  大小/位置存进 cam_bubble.cfg.json，下次照旧" -ForegroundColor DarkGray

if ($Watch) {
    Write-Host ""
    Write-Host "看门狗已开：App 被杀 / 画面断了会自动重启（Ctrl+C 结束）" -ForegroundColor Cyan
    Write-Host "  注意：在浮窗上点『退出』是正常退出 —— 看门狗会跟着停，并把手机摄像头关掉" -ForegroundColor DarkGray
    $fails = 0
    while ($true) {
        Start-Sleep -Seconds 5

        # 手动退出优先：浮窗写标记，这里收工（顺手确保手机摄像头也关掉）
        if (Test-Path $ExitFlag) {
            Write-Host "浮窗被手动退出 -> 停止看门狗，关掉手机摄像头" -ForegroundColor Yellow
            try {
                $s = Get-ValidSerial
                & $Adb -s $s shell "su -c 'am force-stop dev.local.camstream'" 2>&1 | Out-Null
            } catch { }
            Remove-Item $ExitFlag -Force -ErrorAction SilentlyContinue
            break
        }

        $alive = $script:BubbleProc -and -not $script:BubbleProc.HasExited
        $len = Test-Stream $script:PhoneIp 1 $script:UrlPort
        if ($len -le 0) {
            $fails++
            Note ("画面断了 ({0}/2)" -f $fails)
            if ($fails -ge 2) {
                Write-Host "  -> 重启 CamStream" -ForegroundColor Yellow
                try {
                    $script:Serial = Get-ValidSerial
                    Start-CamStreamApp $script:Serial
                    $route = Resolve-StreamUrl
                    $script:PhoneIp = $route.ip
                    $script:UrlPort = $route.port
                } catch { Write-Warning "  重启失败: $($_.Exception.Message)" }
                Start-Sleep -Seconds 2
                $fails = 0
            }
        } else {
            $fails = 0
        }
        if (-not $alive) {
            Write-Host "  -> 浮窗进程没了，重开" -ForegroundColor Yellow
            Start-Bubble
        }
    }
}
