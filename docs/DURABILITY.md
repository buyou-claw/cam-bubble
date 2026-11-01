# 重启稳定性（实测）

目标：**电脑重启、手机重启之后，都不用人工干预就能恢复出画面。**

## 1. 结论先给

| 场景 | 需要做什么 | 实测结果 |
|---|---|---|
| **手机重启** | 什么都不用做 | ✅ 30 秒内自动恢复（adb 回来 → 解锁 → 重开相机 → 出图） |
| **电脑重启** | 装一次开机自启（`tools/autostart.ps1`），之后什么都不用做 | ✅ 自启脚本已在用（VBS 拉 `camera_live.ps1 -Watch`） |
| **手机 + 电脑一起重启** | 谁先起来都行，看门狗会重试 | ✅ 同上，最慢 ~40s |
| **拔掉 USB** | 不用管 | ✅ adb 走 `IP:5555`，视频走 Wi-Fi |
| **无线调试开关被关** | 不用管 | ✅ `persist.adb.tcp.port=5555` 让 adbd 一直监听，不依赖无线调试 UI |

## 2. 手机上做了什么（一次性）

```powershell
# 1) adbd 固定监听 5555，重启后仍在（这条最关键：不再依赖"无线调试"开关）
adb shell su -c 'setprop persist.adb.tcp.port 5555'
adb shell su -c 'settings put global adb_enabled 1'

# 2) CamStream 装好 + 相机权限（camera_live.ps1 会自动做）
# 3) MIUI 白名单（自启动 / 省电无限制，见 DEVICE-SETUP.md）
```

`persist.*` 属性会持久化，所以手机重启后 `adb connect <IP>:5555` 依旧可用——这条
不依赖「无线调试」页面（那个页面在 MIUI 上是空白的，见 TROUBLESHOOTING）。

## 3. 电脑上做了什么（一次性）

```powershell
.\tools\autostart.ps1            # 装到当前用户启动项（不需要管理员）
.\tools\autostart.ps1 -Status    # 看装了没
.\tools\autostart.ps1 -Remove    # 卸载
```

装的是一个 VBS：`%APPDATA%\...\Startup\cam-bubble.vbs`，开机延迟 25 秒后最小化拉起
`camera_live.ps1 -Source apk -Size 380 -Watch`。延迟是为了等网络和 adb 服务就绪。

## 4. 恢复是怎么发生的

```
手机重启
  └─ adbd 起来后监听 <IP>:5555 (persist.adb.tcp.port)
       └─ PC 看门狗每 5s 探 /snapshot，失败两次 → 重启 CamStream
            └─ Get-ValidSerial：原 serial 不在了 → 重新找（5555 → mDNS → 端口扫描）
                 └─ Wake-Unlock：su 注入 POWER + 上滑解锁（重启后是锁屏状态）
                      └─ am start CamStream → 相机开 → 出图
```

看门狗日志实测（第二次重启）：

```
画面断了 (1/2)
画面断了 (2/2)
-> 重启 CamStream
CAMERA android.permission.CAMERA: granted=true
锁屏中，上滑解锁 ...
```

## 5. 这套恢复踩过的三个坑（都已修）

1. **锁屏挡住启动**：手机重启后停在锁屏，`am start` 起的 Activity 不会 resume，相机不开。
   → 启动前先 `su -c 'input keyevent KEYCODE_WAKEUP'` + 上滑解锁。
   注意 MIUI 剥了 shell(2000) 的 `INJECT_EVENTS`，注入必须走 `su`。

2. **serial 写死**：USB 拔掉后 `-s 52d162c6` 失效。
   → 每次用前 `Get-ValidSerial` 重新解析；`5555` 排在最前面。

3. **改 MIUI 库把 LBE 搞崩**：`wake_path.db` 的属主被我们设成 `system:system`，
   但 LBE 的 data 目录属主是 `u0_a96:u0_a96` → 开机时 LBE 打不开库直接 crash，
   相机权限链跟着坏掉。
   → `scripts/apply_miui_whitelist.sh` 改成 `chown $(stat -c %u:%g <目录>)`，
   并且提供了 `scripts/fix_lbe_db_owner.sh` 一键修回来。

## 6. 还是起不来怎么办

按顺序排查：

```powershell
# 1) adb 在不在
adb devices                       # 期望看到 <IP>:5555  device

# 2) adbd 有没有监听 5555
adb shell getprop persist.adb.tcp.port     # 期望 5555

# 3) 相机服务活着吗
curl http://<IP>:8088/            # 期望 size=640x480 sensor_rotation=270

# 4) 手动跑一次（能看到完整日志）
.\camera_live.ps1 -Source apk -Watch

# 5) 看门狗日志
Get-Content .\build\watchdog.log -Tail 30
```

最坏情况（手机彻底连不上）：插 USB → `camera_live.ps1` 会自动走 adb + forward 隧道。
