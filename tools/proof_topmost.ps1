# proof_topmost.ps1 - 取证：证明「摄像头投屏窗口」在最前端
# 1) 枚举可见窗口，打印 title / size / WS_EX_TOPMOST / 是否前台
# 2) 截整块桌面存 PNG（人眼可见证据）
param(
    [string]$Title = "Redmi K20 Pro - Camera Live",
    [string]$Out = "E:\ai_project\redmik20\evidence\camera_topmost.png"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class W32 {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr h);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr h, int i);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    public struct RECT { public int Left, Top, Right, Bottom; }
    public static string Dump() {
        var sb = new StringBuilder();
        EnumWindows((h, l) => {
            if (!IsWindowVisible(h)) return true;
            int n = GetWindowTextLength(h);
            if (n == 0) return true;
            var t = new StringBuilder(n + 2);
            GetWindowText(h, t, t.Capacity);
            RECT r; GetWindowRect(h, out r);
            int ex = GetWindowLong(h, -20);
            sb.AppendLine(String.Format("{0}|{1}|{2}|{3}x{4}|{5}",
                h.ToInt64(), t.ToString(), ((ex & 0x8) != 0) ? "TOPMOST" : "-",
                r.Right - r.Left, r.Bottom - r.Top,
                (GetForegroundWindow() == h) ? "FOREGROUND" : ""));
            return true;
        }, IntPtr.Zero);
        return sb.ToString();
    }
}
'@

$dump = [W32]::Dump()
Write-Host "== 目标窗口 ==" -ForegroundColor Cyan
$hits = @($dump -split "`r?`n" | Where-Object { $_ -match [regex]::Escape($Title) -and $_.Trim() })
if (-not $hits) {
    Write-Host "  未找到标题含 '$Title' 的可见窗口" -ForegroundColor Red
} else {
    foreach ($l in $hits) {
        $p = $l -split "\|"
        Write-Host ("  hwnd={0}  title='{1}'  {2}  {3}x{4}  {5}" -f $p[0], $p[1], $p[2], $p[3], $p[4], $p[5])
    }
}

Write-Host "== 全部可见窗口（前 15）==" -ForegroundColor DarkGray
$dump -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -First 15 | ForEach-Object {
    $p = $_ -split "\|"
    Write-Host ("  {0,-40} {1,-8} {2}" -f $p[1], $p[2], $p[5]) -ForegroundColor DarkGray
}

$vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $vs.Width, $vs.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($vs.Left, $vs.Top, 0, 0, $bmp.Size)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Host ("桌面截图: {0} ({1:N0} bytes)" -f $Out, (Get-Item $Out).Length) -ForegroundColor Green
