# 手机侧准备

以 Redmi K20 Pro（`raphael`，Android 11 / MIUI 12.5，Magisk 26.1）为例，其他机型大同小异。

## 1. 让电脑能 adb 连上手机

### 无线调试（推荐，之后可拔线）

1. 手机：设置 → 搜索「无线调试」→ 打开开关
   - MIUI 的「开发者选项」页面可能是空白的（见排坑文档），**用设置里的搜索直达无线调试页**最稳
2. 点「使用配对码配对设备」→ 屏幕上有 6 位配对码和 `IP:端口`
3. 电脑上：

```powershell
$adb = "tools\scrcpy-win64-v5.0.1\adb.exe"
& $adb pair 192.168.31.130:40347 783963     # 用手机屏幕上的端口和配对码
& $adb connect 192.168.31.130:37979         # 无线调试页显示的"IP 地址和端口"
& $adb devices
```

> 无线调试端口**每次开关都会变**。`tools\scan_ports.py 192.168.31.130 30000 50000` 可以扫出来。

### USB

插线 → 手机弹「允许 USB 调试吗」→ 允许。`adb devices` 里出现序列号即可。

## 2. root（改 MIUI 白名单、装 APK 需要）

```powershell
adb shell su -c id     # 期望 uid=0(root) ... context=u:r:magisk:s0
```

Magisk 里三处设置（否则 `su` 秒拒）：
- 超级用户访问权限 = **应用和 ADB**
- 点按劫持保护 = **关**
- 超级用户列表里 `[SharedUID] Shell` = **允许**

## 3. 装 CamStream

```powershell
adb push dist\camstream.apk /data/local/tmp/camstream.apk
adb shell su -c 'pm install -r /data/local/tmp/camstream.apk'
adb shell su -c 'pm grant dev.local.camstream android.permission.CAMERA'
adb shell am start -n dev.local.camstream/.MainActivity
```

验证：

```powershell
curl http://<手机IP>:8088/          # 状态页：size / sensor_rotation
curl http://<手机IP>:8088/snapshot -o shot.jpg
```

> 装完第一次启动，MIUI 会弹自家安全中心的相机授权框（`com.lbe.security.miui`）。
> 如果画面一直黑：`adb shell am force-stop com.lbe.security.miui` 后再冷启 App。

## 4. MIUI 白名单（防止相机被系统收走 / 后台被限制）

`camera_live.ps1` 每次启动都会自动做这几步，手动做的话：

```powershell
# a) Android 原生
adb shell cmd deviceidle whitelist +dev.local.camstream
adb shell cmd appops set dev.local.camstream RUN_IN_BACKGROUND allow
adb shell cmd appops set dev.local.camstream RUN_ANY_IN_BACKGROUND allow

# b) MIUI 自启动 + 省电无限制（一条命令：拉库 → 改库 → 推回 → 重启服务）
python tools\miui_whitelist.py --push

#    只拉库/只改不推：
#    python tools\miui_whitelist.py --pull
#    python tools\miui_whitelist.py
```

落到库里长这样：

| 位置 | 值 |
|---|---|
| `com.lbe.security.miui/wake_path.db` → `WakePathWhiteList` | `('dev.local.camstream', 1)` = 允许自启动 |
| `com.miui.powerkeeper/user_configure.db` → `userTable` | `bgControl = 'noRestrict'` = 省电无限制 |

> 改库必须**先 `am force-stop` 宿主服务**，改完 `chown system:system` + `chmod 660` + `restorecon`，
> 否则会被服务盖回去或 SELinux 拒绝。MIUI 升级/清数据后可能重置，重跑一次即可。

## 5. 保持屏幕常亮

`camera_live.ps1` 会 `svc power stayon true`；APK 本身也带 `FLAG_KEEP_SCREEN_ON`。
不想让手机亮着，就用 `-Source adb` 备选路线（那条路必须亮屏开着相机）。

## 6. 换机型要改什么

| 项 | 文件 | 说明 |
|---|---|---|
| 包名 / 应用名 | `android/AndroidManifest.xml` | 改 `package` 后 `pm grant` 的包名也要跟着改 |
| 预览尺寸 | `MainActivity.java` 的 `TARGET_W/TARGET_H` | 默认 640×480 |
| 画面旋转 | `camera_live.ps1 -Rotation` | 前置常见 90/270 |
| 端口 | `MainActivity.PORT` + `camera_live.ps1` 里的 8088 | 改一处要改另一处 |
| adb 路径 | `camera_live.ps1` 顶部 `$ScrcpyDir` | 换 adb 位置时改 |
| 手机 IP | `camera_live.ps1` 的 `$PhoneIp` | 只在扫端口兜底时用 |
| 停止命令 | `--stop-package dev.local.camstream` | 换包名要同步 |
