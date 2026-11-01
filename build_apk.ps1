# build_apk.ps1 - 编译 CamStream.apk（手机端前置摄像头 MJPEG 服务）
#
# 依赖（都在 tools/ 里，已 gitignore，需自行准备）：
#   tools/android/android-14            build-tools（aapt2 / d8 / zipalign / apksigner）
#   tools/android/android-11/android.jar  Android 11 平台包
#   JDK 8+（javac / keytool / java 在 PATH 里）
#
# 用法：
#   .\build_apk.ps1                  # 产出 dist\camstream.apk
#   .\build_apk.ps1 -Out D:\x.apk
#
# 两个坑（写在这里免得下次再踩）：
#   1) javac 必须用 -bootclasspath android.jar（-cp 会让 d8 编出问题）
#   2) 源码里不能用「匿名内部类 + 合成访问器(access$N)」，本机 d8 8.2.2-dev 会 NPE
param(
    [string]$Out = ""
)

$ErrorActionPreference = "Continue"
$Root     = $PSScriptRoot
$BT       = Join-Path $Root "tools\android\android-14"
$Platform = Join-Path $Root "tools\android\android-11\android.jar"
$Src      = Join-Path $Root "android\src"
$Manifest = Join-Path $Root "android\AndroidManifest.xml"
$Ks       = Join-Path $Root "android\debug.keystore"
$Build    = Join-Path $Root "build"
if (-not $Out) { $Out = Join-Path $Root "dist\camstream.apk" }

foreach ($need in @($BT, $Platform, $Src, $Manifest)) {
    if (-not (Test-Path $need)) { throw "缺少依赖: $need" }
}

if (Test-Path $Build) { Remove-Item $Build -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Build, "$Build\classes", "$Build\dex", (Split-Path $Out -Parent) | Out-Null

Write-Host "[1/5] aapt2 link" -ForegroundColor Cyan
$unsigned = Join-Path $Build "unsigned.apk"
& "$BT\aapt2.exe" link -o $unsigned --manifest $Manifest -I $Platform --min-sdk-version 23 --target-sdk-version 30
if ($LASTEXITCODE -ne 0) { throw "aapt2 link 失败" }

Write-Host "[2/5] javac" -ForegroundColor Cyan
$srcs = @(Get-ChildItem $Src -Recurse -Filter *.java | ForEach-Object { $_.FullName })
& javac -source 8 -target 8 -nowarn -bootclasspath $Platform -d "$Build\classes" @srcs 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "javac 失败" }

Write-Host "[3/5] d8" -ForegroundColor Cyan
$cls = @(Get-ChildItem "$Build\classes" -Recurse -Filter *.class | ForEach-Object { $_.FullName })
& "$BT\d8.bat" --lib $Platform --min-api 23 --output "$Build\dex" @cls 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "d8 失败" }

Write-Host "[4/5] 塞 classes.dex + zipalign" -ForegroundColor Cyan
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($unsigned, 'Update')
$entry = $zip.CreateEntry('classes.dex', [System.IO.Compression.CompressionLevel]::NoCompression)
$st = $entry.Open()
$dexBytes = [IO.File]::ReadAllBytes((Join-Path $Build "dex\classes.dex"))
$st.Write($dexBytes, 0, $dexBytes.Length)
$st.Close(); $zip.Dispose()

$aligned = Join-Path $Build "aligned.apk"
& "$BT\zipalign.exe" -f 4 $unsigned $aligned
if ($LASTEXITCODE -ne 0) { throw "zipalign 失败" }

Write-Host "[5/5] 签名" -ForegroundColor Cyan
if (-not (Test-Path $Ks)) {
    Write-Host "  没有 debug.keystore，生成一个（密码 android，别名 androiddebugkey）" -ForegroundColor Yellow
    & keytool -genkeypair -keystore $Ks -storepass android -keypass android `
        -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 `
        -dname "CN=Android Debug,O=Android,C=US" 2>&1 | Out-Null
}
& java -jar "$BT\lib\apksigner.jar" sign --ks $Ks --ks-pass pass:android --key-pass pass:android `
    --ks-key-alias androiddebugkey --out $Out $aligned
if ($LASTEXITCODE -ne 0) { throw "apksigner 失败" }

Write-Host "== 校验" -ForegroundColor Cyan
& java -jar "$BT\lib\apksigner.jar" verify --print-certs $Out 2>&1 | Select-Object -First 2
& "$BT\aapt2.exe" dump badging $Out 2>&1 | Select-Object -First 1

Write-Host ""
Write-Host ("APK: {0}  ({1:N0} bytes)" -f $Out, (Get-Item $Out).Length) -ForegroundColor Green
