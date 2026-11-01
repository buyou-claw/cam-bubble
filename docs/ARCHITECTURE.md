# 架构与实现

## 1. 总览

```
┌──────────────────────── 手机 (Android 11) ────────────────────────┐
│  CamStream.apk  (dev.local.camstream)                             │
│    Camera1 前置相机 → NV21 → YuvImage → JPEG(q70) 640×480          │
│    自建 HTTP 服务 :8088                                            │
│      GET /video     multipart/x-mixed-replace（每 45ms 推一帧）     │
│      GET /snapshot  单帧 JPEG（探活/取证用）                        │
│    看门狗：2.5s 没有预览帧 → release 重开；无相机时每 3s 重试        │
└───────────────────────────────┬──────────────────────────────────┘
                                │ Wi-Fi / USB 局域网 TCP 8088
┌───────────────────────────────▼──────────────────────────────────┐
│  PC (Windows)  cam_bubble.py                                      │
│    mjpeg_reader 线程：找 SOI/EOI 切帧 → PIL 解 JPEG（保留最后一帧） │
│    渲染：旋转 90° → 居中裁正方形 → 圆形遮罩(4× 超采样 + LANCZOS)   │
│          → 预乘 alpha 的 BGRA → UpdateLayeredWindow (ULW_ALPHA)   │
│    窗口：WS_POPUP + WS_EX_LAYERED + WS_EX_TOPMOST + NOACTIVATE     │
│    交互：滚轮缩放 / 左键拖动 / 右键原生菜单                        │
└───────────────────────────────────────────────────────────────────┘
```

编排脚本 `camera_live.ps1` 负责：找设备 → 装/启 APK → 授相机权限 → 等出图 → 起浮窗 → 校验置顶 → 进看门狗循环。

## 2. 为什么不用 `scrcpy --video-source=camera`

scrcpy 5.0.1 的帮助里写死了：

```
--video-source=source
    Select the video source (display or camera).
    Camera mirroring requires Android 12+.
```

目标机是 **Android 11（SDK 30）**，这条路直接堵死。`--source adb` 的备选路线（录屏 + ffmpeg 解码）能跑，
但画面里必然带相机 App 的顶栏和快门，所以最终选了「自建 APK 直出 MJPEG」。

## 3. 手机端：CamStream

一个不到 400 行的 `Activity`，刻意保持「零资源、零依赖」：

| 设计点 | 原因 |
|---|---|
| Camera1（`android.hardware.Camera`）而不是 Camera2 | 代码量小；`setPreviewCallbackWithBuffer` 直接拿 NV21；预览尺寸自由选 640×480 |
| `YuvImage.compressToJpeg` | 系统 API，稳定，640×480 q70 约 8~12ms/帧 |
| 自建 `ServerSocket`，每连接一个线程 | 不引入 Netty/NanoHTTPD；支持多客户端（浮窗 + 探针同时看） |
| `/video` 每 45ms 推一帧 | 约 22fps 上限，实际 20~21fps，带宽 ~1.5MB/s |
| `FLAG_KEEP_SCREEN_ON` | 相机预览期间屏幕不能灭 |
| 单独 `SurfaceView` 做预览 | 某些机型不设 preview display 就不回调帧 |

### 相机自愈（App 内看门狗）

MIUI 会在重装后、它自己重启后、息屏切后台等时点把相机访问收回去：

```
I CameraService: Camera 1: Access for "dev.local.camstream" revoked
I Camera3-Device: disconnectImpl: E
```

被 revoke 后预览回调停止，但进程还活着，HTTP 会一直重发最后一帧 → 画面冻住。所以 App 内有三道：

1. `Camera.ErrorCallback` 触发 → `stopCamera()` + 300ms 后重开
2. `Watchdog` 线程：`now - lastFrameAt > 2500ms` → 重开
3. 相机为 null 时每 3s 重试一次（权限恢复后自动接上）

`onResume()` 也会检查一次。所有重开都走主线程 Handler，避免多线程碰 Camera。

## 4. PC 端：浮窗

### 4.1 分层窗口与圆形

- 窗口样式：`WS_POPUP | WS_VISIBLE` + `WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE`
  （`NOACTIVATE` = 点它不抢焦点，不打断工作）
- 每帧：`UpdateLayeredWindow(..., ULW_ALPHA)`，DIB 是 **top-down 32bpp BGRA**，颜色已**预乘 alpha**
- 圆形遮罩：`size×4` 超采样上画椭圆 → `LANCZOS` 缩回，边缘抗锯齿
- 描边颜色即状态：白=正常、黄=暂停、橙=固定、灰=未置顶

### 4.2 尺寸与 DPI

进程启动时 `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)`，所以 `--size` 就是**物理像素**。
启动时会把窗口坐标夹进屏幕内（配置文件可能存过屏幕外的值）。滚轮/菜单改尺寸都以圆心为基准。

### 4.3 右键菜单

原生 `CreatePopupMenu` / `AppendMenuW` / `TrackPopupMenu(TPM_RETURNCMD)`：

- 靠近屏幕右/下半屏时自动加 `TPM_RIGHTALIGN` / `TPM_BOTTOMALIGN`，避免菜单被挤出屏幕
- 菜单不抢焦点；点空白或 Esc 关掉

### 4.4 三种画面源

| `--source` | 用途 |
|---|---|
| `mjpeg` | 默认，读 CamStream 的 `/video` |
| `adb` | 备选：`adb exec-out screenrecord --output-format=h264` → ffmpeg 解码裁剪（需要 ffmpeg.exe） |
| `test` | 合成画面，自检遮罩/缩放/菜单用，不需要手机 |

`reconnect()`（菜单「重新连接摄像头」）会按当前源类型重建读流线程。

## 5. 看门狗与退出协议

PC 端看门狗（`camera_live.ps1 -Watch`）每 5s 一轮：

```
有 cam_bubble.exit 标记?  ──是──> 主动退出：force-stop 手机 App，删标记，自己退出
        │否
浮窗进程还活着?          ──否──> 重开浮窗
        │是
/snapshot 连续 2 次失败?  ──是──> 重装/授权/冷启 CamStream
```

**退出协议**（解决「点了退出又被弹回来」）：

1. 浮窗退出时写 `cam_bubble.exit`
2. `adb shell su -c 'am force-stop dev.local.camstream'` 关掉手机摄像头
3. 看门狗看到标记 → 不再重启，自己收工

只有「进程被强杀 / 断流」才算故障，才会自动拉起；正常启动前会先删掉旧标记。

## 6. MIUI 白名单

MIUI 没有 CLI 开关，直接改它自己的库（root，改前必须 `am force-stop` 宿主服务）：

| 目的 | 库 / 表 | 值 |
|---|---|---|
| 自启动允许 | `com.lbe.security.miui/wake_path.db` → `WakePathWhiteList` | `(pkg, userSettings=1)`（`=2` 才是拒绝） |
| 省电策略无限制 | `com.miui.powerkeeper/user_configure.db` → `userTable` | `bgControl='noRestrict'` |
| 电池优化不优化 | Android Doze | `cmd deviceidle whitelist +pkg` |
| 后台运行 | appops | `RUN_IN_BACKGROUND` / `RUN_ANY_IN_BACKGROUND = allow` |

枚举值是从 APK 的 dex 里核过的（powerkeeper 只有 `miuiAuto` / `noRestrict` / `restrictBg`）。
脚本：`tools/miui_whitelist.py`（PC 侧改库）+ `scripts/apply_miui_whitelist.sh`（手机侧落位）。

## 7. 已知限制

- 手机端画面是**传感器横向**的，PC 侧统一 `--rotation 90`；换机型可能要 0/180/270
- 手机端 JPEG 640×480，想更清楚改 `TARGET_W/TARGET_H` 重新编译（带宽和延迟会跟着涨）
- 依赖手机的「无线调试/USB 调试」；MIUI 的开发者选项页面本身可能是空白的（见排坑文档）
- 只做了 Windows；浮窗是纯 Win32，换平台要重写渲染部分
