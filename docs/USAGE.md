# 使用手册

## 1. 一键启动

```
双击 启动摄像头浮窗.bat
```

等价于：

```powershell
.\camera_live.ps1 -Source apk -Size 380 -Watch
```

它会依次做：连 adb → 装/启 CamStream → 授相机权限 → 等出图 → 起浮窗 → 校验置顶 → 进看门狗。

> 双击后那个**黑窗口就是看门狗，别关**。关掉它只是不再自愈，浮窗本身还在。
> 想彻底停：浮窗右键 → **退出（并关掉手机摄像头）**。

## 2. camera_live.ps1 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `-Source apk\|adb` | `apk` | `apk`：自建 CamStream（干净画面）；`adb`：录屏解码（免装 App，带相机 UI） |
| `-Size` | `380` | 圆形直径（物理像素） |
| `-X` `-Y` | `-40` `-40` | 左上角坐标；**负数=相对屏幕右下角** |
| `-Border` | `3` | 白色描边宽度，0=不要 |
| `-Rotation` | `90` | 画面旋转角（0/90/180/270），换机型可能要改 |
| `-NoMirror` | 关 | 关掉左右镜像 |
| `-Reinstall` | 关 | 强制重装 CamStream（平时按 APK 时间自动判断） |
| `-Watch` | 关 | 开看门狗 |
| `-NoLaunch` | 关 | 不碰手机，只起浮窗 |
| `-VerifyOnly` | 关 | 只检查浮窗是否置顶 |
| `-ScreenSize` `-Crop` | `720x1560` / 空 | 仅 `-Source adb`：采集分辨率与裁剪区 |

示例：

```powershell
.\camera_live.ps1 -Size 560 -X 60 -Y 60            # 大一号，放左上角
.\camera_live.ps1 -Source adb -ScreenSize 720x1560 -Crop "720:720:0:170"
.\camera_live.ps1 -VerifyOnly                      # 只验置顶
```

## 3. 浮窗操作与右键菜单

| 菜单项 | 作用 | 描边颜色 |
|---|---|---|
| 暂停画面 / 继续画面 | 冻结当前帧（读流不停，松手即恢复） | 黄 `(240,200,60)` |
| 固定位置大小 / 解除固定 | 锁住拖动和滚轮，防手滑 | 橙 `(255,150,60)` |
| 取消置顶 / 恢复置顶 | 临时让别的窗口盖住它 | 灰 `(160,160,160)` |
| 画面大小 ▸ | 200/260/320/380/460/560/700 px，放大/缩小 40px，当前值打勾 | — |
| 镜像画面 | 左右翻转（前置默认开） | 打勾=开 |
| 重新连接摄像头 | 重建读流线程 | — |
| 退出（并关掉手机摄像头） | 写退出标记 + force-stop 手机 App + 关浮窗 | — |

鼠标：**滚轮**改直径（±20px/格，圆心不动）｜**左键拖动**移动｜**右键**开菜单。

## 4. 状态文件

| 文件 | 内容 | 说明 |
|---|---|---|
| `cam_bubble.cfg.json` | `{"size":380,"x":2332,"y":732}` | 浮窗尺寸位置，拖动/缩放/退出时保存 |
| `device.state.json` | adb 端点、序列号、更新时间 | 无线调试端口变化后的兜底缓存 |
| `cam_bubble.exit` | 退出标记 | 只存在一瞬间，看门狗读到就删 |

三个文件都在 `.gitignore` 里。

## 5. 单独跑浮窗（调试用）

```powershell
python .\cam_bubble.py --source mjpeg --url http://192.168.31.130:8088/video --rotation 90 --size 380
python .\cam_bubble.py --test --size 240          # 合成画面自检，不需要手机
python .\cam_bubble.py --source adb --adb tools\scrcpy-win64-v5.0.1\adb.exe --serial 52d162c6 `
    --ffmpeg tools\ffmpeg\ffmpeg.exe --screen-size 720x1560
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--size N` `--x N` `--y N` | 尺寸与位置（负数=右下角） |
| `--rotation 0/90/180/270` | 旋转 |
| `--no-mirror` | 关镜像 |
| `--border N` | 描边宽度 |
| `--config FILE` | 尺寸位置持久化文件 |
| `--exit-flag FILE` | 退出时写这个文件（配合看门狗） |
| `--adb` `--serial` `--stop-package` | 退出时关掉手机摄像头的三件套 |
| `--seconds N` | 自检用（注意：`PostQuitMessage` 是线程内的，这个开关只用于快速演示） |

## 6. 编译手机端 APK

```powershell
.\build_apk.ps1                 # 产出 dist\camstream.apk
.\build_apk.ps1 -Out D:\x.apk
```

依赖：JDK 8+、`tools/android/android-14`（build-tools）、`tools/android/android-11/android.jar`。
签名用 `android/debug.keystore`（密码 `android`，别名 `androiddebugkey`），换签名会导致
`pm install -r` 失败，需要先卸载。

手动装：

```powershell
adb push dist\camstream.apk /data/local/tmp/camstream.apk
adb shell su -c 'pm install -r /data/local/tmp/camstream.apk'
adb shell su -c 'pm grant dev.local.camstream android.permission.CAMERA'
adb shell am start -n dev.local.camstream/.MainActivity
```

> MIUI 会用 `INSTALL_FAILED_USER_RESTRICTED` 拦普通 `adb install`，所以走 root 的 `pm install`。

## 7. 自检脚本（tools/）

| 脚本 | 用途 |
|---|---|
| `python tools\mjpeg_probe.py http://IP:8088/video 3` | 统计帧率/首帧时间，判断「实时」 |
| `powershell -File tools\proof_topmost.ps1` | 打印窗口 TOPMOST 状态 + 截桌面 |
| `python tools\test_menu_click.py` | 模拟点菜单第一项，验证暂停/继续 |
| `python tools\test_menu_ring.py` | 用描边色判定 暂停/固定/置顶 状态 |
| `python tools\test_menu_lock.py` | 验证「固定」后滚轮失效 |
| `python tools\test_menu_top.py` | 验证「取消置顶/恢复置顶」 |
| `python tools\test_resize.py` | 连续发滚轮消息，断言直径按 20px/格变化 |
| `python tools\scan_ports.py 192.168.31.130 30000 50000` | 扫无线调试端口 |
