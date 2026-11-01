#!/system/bin/sh
# 把改好的 MIUI 白名单库推回手机（在手机上以 root 执行）
#
# 用法：
#   adb push build/miui/pk_user_mod.db    /data/local/tmp/pk_user_mod.db
#   adb push build/miui/lbe_wake_mod.db   /data/local/tmp/lbe_wake_mod.db
#   adb push scripts/apply_miui_whitelist.sh /data/local/tmp/
#   adb shell su -c 'sh /data/local/tmp/apply_miui_whitelist.sh'
#
# 要点：必须先停宿主服务，否则它会把文件盖回去；改完要修 owner/权限/SELinux。

echo "== 停宿主服务 =="
am force-stop com.miui.powerkeeper
am force-stop com.lbe.security.miui
sleep 1

echo "== powerkeeper: 省电策略 = 无限制 =="
cp /data/local/tmp/pk_user_mod.db /data/data/com.miui.powerkeeper/databases/user_configure.db
rm -f /data/data/com.miui.powerkeeper/databases/user_configure.db-journal
chown $(stat -c %u:%g /data/data/com.miui.powerkeeper/databases) /data/data/com.miui.powerkeeper/databases/user_configure.db
chmod 660 /data/data/com.miui.powerkeeper/databases/user_configure.db
restorecon /data/data/com.miui.powerkeeper/databases/user_configure.db

echo "== lbe: 自启动 = 允许 =="
cp /data/local/tmp/lbe_wake_mod.db /data/data/com.lbe.security.miui/databases/wake_path.db
rm -f /data/data/com.lbe.security.miui/databases/wake_path.db-journal
chown $(stat -c %u:%g /data/data/com.lbe.security.miui/databases) /data/data/com.lbe.security.miui/databases/wake_path.db
chmod 660 /data/data/com.lbe.security.miui/databases/wake_path.db
restorecon /data/data/com.lbe.security.miui/databases/wake_path.db

echo "== 结果 =="
ls -lZ /data/data/com.miui.powerkeeper/databases/user_configure.db
ls -lZ /data/data/com.lbe.security.miui/databases/wake_path.db
echo done
