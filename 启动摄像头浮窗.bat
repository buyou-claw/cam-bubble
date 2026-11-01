@echo off
cd /d "%~dp0"
echo ============================================================
echo   手机前置摄像头 -^> 电脑最前端的圆形浮窗
echo   滚轮 = 改圆形大小    左键拖动 = 移动    右键 = 退出
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0camera_live.ps1" -Source apk -Size 380 -Watch
if errorlevel 1 (
  echo.
  echo 启动失败：看上面的提示。手机没连上就先把 USB 插上。
  pause
  exit /b 1
)
echo.
echo 浮窗已起来。这个窗口是看门狗：App 被杀/画面断了会自动重启，别关；关掉只是不再自愈。
