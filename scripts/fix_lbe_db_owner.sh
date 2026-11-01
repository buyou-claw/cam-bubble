#!/system/bin/sh
# 修 LBE(AuthManager) 库的属主：必须是它自己（u0_a96:u0_a96），不是 system
D=/data/data/com.lbe.security.miui/databases
OWNER=$(stat -c %u:%g $D)
echo "dir owner = $OWNER"
for f in wake_path.db wake_path.db-journal; do
  if [ -f "$D/$f" ]; then
    chown $OWNER "$D/$f"
    chmod 660 "$D/$f"
    restorecon "$D/$f"
  fi
done
ls -lZ $D
echo "--- powerkeeper ---"
P=/data/data/com.miui.powerkeeper/databases
POWNER=$(stat -c %u:%g $P)
echo "dir owner = $POWNER"
ls -lZ $P | head -5
