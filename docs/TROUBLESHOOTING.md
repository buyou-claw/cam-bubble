# 排坑记录

按「现象 → 原因 → 处理」写，都是这个项目里真实踩过的。

---

## 手机端

### 画面卡住不动（一帧永远不变）

**原因**：MIUI 把相机访问收回去了，CamStream 进程还活着，HTTP 反复重发最后一帧。

```
I CameraService: Camera 1: Access for "dev.local.camstream" revoked
I Camera3-Device: disconnectImpl: E
```

**处理**：已内置三层自愈 —— App 内看门狗（2.5s 无帧重开相机）、PC 端看门狗（连续 2 次断流重启 App）、
启动器默认带 `-Watch`。确认活着：

```powershell
python tools\mjpeg_probe.py http://<IP>:8088/video 3
```

### 浮窗全黑，`/snapshot` 返回 503

**原因**：手机上 MIUI 安全中心（`com.lbe.security.miui`）的相机授权框盖在 App 上，相机没起来。

**处理**：

```powershell
adb shell am force-stop com.lbe.security.miui
adb shell su -c 'pm grant dev.local.camstream android.permission.CAMERA'
adb shell su -c 'am force-stop dev.local.camstream'
adb shell am start -n dev.local.camstream/.MainActivity
```

顺序很重要：**先停 LBE，再 grant，再冷启**。另外**别反复重装**，`pm install -r` 会把 MIUI 那边的授权重置。

### 手机重启后：LBE（安全中心）一直崩，相机权限链坏掉

**原因**：改 MIUI 白名单时把 `wake_path.db` 的属主写成了 `system:system`，但 LBE 的
`/data/data/com.lbe.security.miui` 目录属主是 `u0_a96:u0_a96`，于是开机时它打不开库：

```
java.lang.RuntimeException: Unable to create application com.lbe.security.LBEApplication:
SQLiteCantOpenDatabaseException: File .../wake_path.db is not readable
```

**处理**：属主要跟**目录本身**一致，不是固定的 `system`：

```powershell
adb shell su -c 'sh /data/local/tmp/fix_lbe_db_owner.sh'   # scripts/fix_lbe_db_owner.sh
```

`scripts/apply_miui_whitelist.sh` 已经改成 `chown $(stat -c %u:%g <目录>)`。

### 手机重启后没画面：其实是被锁屏挡住了

**原因**：重启后停在锁屏，`am start` 起的 Activity 不会 resume，相机自然不开。
另外 MIUI 剥了 shell(uid 2000) 的 `INJECT_EVENTS`，`adb shell input ...` 会报
`SecurityException: Injecting to another application requires INJECT_EVENTS permission`。

**处理**：唤醒/解锁必须走 root——

```powershell
adb shell su -c 'input keyevent KEYCODE_WAKEUP'
adb shell su -c 'input swipe 540 2000 540 800 200'
```

`camera_live.ps1` 的 `Wake-Unlock` 已经这么做，并且在启动 APK 前会先跑一次。

### `adb install` 报 `INSTALL_FAILED_USER_RESTRICTED: Install canceled by user`

**原因**：MIUI 限制普通 adb 安装（它要求开「USB 调试（安全设置）」）。

**处理**：走 root：

```powershell
adb push dist\camstream.apk /data/local/tmp/camstream.apk
adb shell su -c 'pm install -r /data/local/tmp/camstream.apk'
```

### 「开发者选项」打不开 / 「无线调试」页面一片空白

**原因**（扒 `Settings.apk` 确认的，不是猜）：

- `com.android.settings.Settings$DevelopmentSettingsDashboardActivity` 在清单里就是 `android:enabled="false"`，
  正常靠 `DevelopmentSettingsEnabler` 运行时打开；没被打开时点进去就是空白或秒退。
- 清单里**根本没有** `*WirelessDebugging*Activity`，无线调试只是 `SubSettings` 里的
  `WirelessDebuggingFragment`（还有一个同样 `enabled=false` 的 QS 磁贴）。宿主拿不到 fragment 参数，内容区就是空白。

**处理**（root 绕过 UI）：

```powershell
adb shell su -c 'settings put global development_settings_enabled 1'
adb shell su -c 'pm enable com.android.settings/.Settings$DevelopmentSettingsDashboardActivity'
adb shell su -c 'settings put global adb_enabled 1'
adb shell su -c 'settings put global adb_wifi_enabled 1'   # 这一条直接让无线调试起监听
```

最后一条实测有效：执行后无线调试端口就回来了，`adb connect IP:端口` 直接连上。
MIUI 仍可能在 ~100ms 后把开发者选项页面收掉，但它的功能已被 root 覆盖，不影响本工具。

### 无线调试端口每次都不一样 / `adb devices` 是空的

**原因**：Android 11 的无线调试端口随机，且 mDNS 在息屏后常不应答。

**处理**：

```powershell
python tools\scan_ports.py 192.168.31.130 30000 50000
adb connect 192.168.31.130:<扫到的端口>
```

---

## 编译

### d8 抛 `NullPointerException: String.length() ... null`

**原因**：本机 build-tools 里的 **d8 8.2.2-dev** 处理「匿名内部类 + 合成访问器(`access$N`)」时会崩。

**处理**：源码里**不要用匿名内部类**，改成普通嵌套类；被内部类访问的成员改成包级可见（默认可见性），
避免 javac 生成 `access$N`。`MainActivity.java` 顶部的注释就是在讲这个。

### javac 编过了但 d8 各种奇怪报错

**处理**：`javac` 必须用 `-bootclasspath android.jar`，不要用 `-cp`（见 `build_apk.ps1`）。

---

## PC 端

### 浮窗圆外是黑底/白底，不是真透明

**原因**：`UpdateLayeredWindow` 要求 **预乘 alpha**（color × alpha / 255），直接用普通 RGBA 会出错。

**处理**：`compose()` 里已经预乘；自检 `python tools\dev_compose_check.py` 会打印
`corner alpha 0 / center alpha 255`，并生成白底合成图看边缘。

### 滚轮没反应 / 变的是窗口大小而不是画面

**原因**：改动后**滚轮默认是变焦**，改尺寸要按 `Ctrl+滚轮`；另一个可能是手机端 APK 还是旧版
（旧版没有 `/zoom`，状态页里不会出现 `zoom=0/99` 这一行）。

**处理**：

```powershell
curl http://<IP>:8088/          # 有 zoom=x/max supported=true 就是新版
.\build_apk.ps1                # 重新编译
.\camera_live.ps1 -Reinstall    # 重装
```

### 尺寸不对，`--size 380` 量出来只有 304

**原因**：进程不是 DPI 感知的，Windows 按 125% 缩放把窗口缩小了。

**处理**：启动时 `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)`（已内置）。
另外**测量脚本自己也要 DPI 感知**，否则 `GetWindowRect` 会返回虚拟化后的 0.8 倍数值。

### 右键菜单贴屏幕右下角时被裁掉

**原因**：`TrackPopupMenu` 在 `WS_EX_NOACTIVATE` 窗口上没有做边缘回弹。

**处理**：按光标位置补 `TPM_RIGHTALIGN` / `TPM_BOTTOMALIGN`（已内置）。

### 点「退出」后浮窗自己又弹回来，手机摄像头还亮着

**原因**：看门狗把「进程消失」一律当成崩溃；手机端 App 是独立进程，关浮窗不会关它。

**处理**：退出时写 `cam_bubble.exit` 标记 + `adb shell su -c 'am force-stop dev.local.camstream'`，
看门狗看到标记就不再重启并自行退出（已内置）。

### PowerShell 脚本报一堆 `Unexpected token`，中文变乱码

**原因**：Windows PowerShell 5.1 把**无 BOM 的 UTF-8** 当 ANSI 读，中文字符串会把引号吃掉。

**处理**：`.ps1` 存成 **UTF-8 with BOM**。

```powershell
$c = Get-Content -Raw -Encoding UTF8 $p
[IO.File]::WriteAllText($p, $c, (New-Object Text.UTF8Encoding($true)))
```

### `.bat` 里的中文导致语法错误

**原因**：cmd 默认代码页 936，UTF-8 的中文会被拆成乱码甚至吃掉括号。

**处理**：`.bat` 存成 **GBK**（`[Text.Encoding]::GetEncoding(936)`）。

### 浮窗跑到屏幕外找不回来

**原因**：`cam_bubble.cfg.json` 里存过屏幕外的坐标。

**处理**：启动时会把坐标夹进屏幕内（已内置）；实在乱套就删掉 `cam_bubble.cfg.json` 重启。

### `--seconds` 到点不退出

**原因**：`PostQuitMessage` 只作用于调用它的线程，Timer 线程里调用无效。

**处理**：这个参数只用于演示，别当生产功能用。要测菜单/缩放请用 `tools\test_*.py` 系列。

---

## 其他通用坑（过程记录）

- `adb exec-out screencap -p > x.png` 在 PowerShell 里会按文本编码写盘，得到坏 PNG；要用 `cmd /c "... > x.png"`。
- `screencap` 实测约 2.45s/帧，绝对不能当视频流；实时只能走 H.264 / MJPEG。
- `uiautomator dump` 对自绘界面（MIUI 相机、计算器键盘）拿不到节点，只能按坐标点。
- MIUI 有叠加层时 Magisk 会**静默拒绝** `su` 请求并把 DENY 写进策略库，需要去超级用户列表改成允许。
