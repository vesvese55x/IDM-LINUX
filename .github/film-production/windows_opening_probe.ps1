$ErrorActionPreference='Stop'
$out=Join-Path (Get-Location) 'out/film-windows-opening'
New-Item -ItemType Directory -Force $out | Out-Null
Add-Type -AssemblyName System.Drawing,System.Windows.Forms
Add-Type @'
using System; using System.Text; using System.Collections.Generic; using System.Runtime.InteropServices;
public static class RealDesktopProbe {
 public delegate bool Callback(IntPtr w,IntPtr state);
 [DllImport("user32.dll")]static extern bool EnumWindows(Callback cb,IntPtr state);
 [DllImport("user32.dll")]static extern bool IsWindowVisible(IntPtr w);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]static extern int GetWindowText(IntPtr w,StringBuilder text,int n);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]static extern int GetClassName(IntPtr w,StringBuilder text,int n);
 public static string[] Windows(){var a=new List<string>();EnumWindows(delegate(IntPtr w,IntPtr s){if(IsWindowVisible(w)){var t=new StringBuilder(2048);var c=new StringBuilder(256);GetWindowText(w,t,2048);GetClassName(w,c,256);a.Add(w+"|"+c+"|"+t);}return true;},IntPtr.Zero);return a.ToArray();}
}
'@
$os=Get-CimInstance Win32_OperatingSystem
$bounds=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$report=@{scope='Real Windows desktop EXE OPENING only; not a complete installation or CMD lesson';os_caption=$os.Caption;os_version=$os.Version;platform=[Environment]::OSVersion.ToString();user_interactive=[Environment]::UserInteractive;screen_width=$bounds.Width;screen_height=$bounds.Height;source_commit=$env:GITHUB_SHA;actual_screenshots=@();installation_completed=$false;cmd_installation_verified=$false;final_film_export_allowed=$false;draw_to_bitmap_used=$false}
function Save-Report {$report | ConvertTo-Json -Depth 7 | Set-Content -Encoding utf8 (Join-Path $out 'actual-native-windows-opening.json')}
Save-Report
if(-not [Environment]::UserInteractive){throw 'Runner is not interactive; no native screen success claim'}
function Real-Shot($name){
 $b=New-Object System.Drawing.Bitmap($bounds.Width,$bounds.Height)
 $g=[System.Drawing.Graphics]::FromImage($b)
 try{$g.CopyFromScreen($bounds.Location,[System.Drawing.Point]::Empty,$bounds.Size);$b.Save((Join-Path $out $name),[System.Drawing.Imaging.ImageFormat]::Png)}finally{$g.Dispose();$b.Dispose()}
}
Real-Shot '00-actual-windows-desktop.png'
$exe=(Resolve-Path 'artifacts/windows/IDM-SEMO-1.0.0-x86_64.exe').Path
$report.exe_sha256=(Get-FileHash $exe -Algorithm SHA256).Hash.ToLowerInvariant()
$baseline=@([RealDesktopProbe]::Windows())
$watch=[Diagnostics.Stopwatch]::StartNew()
$p=Start-Process -FilePath $exe -PassThru
try {
 # Short bounded opening probe; stop before the documented sixteen-second auto path.
 for($i=0;$i -lt 6;$i++){
  if($watch.Elapsed.TotalSeconds -gt 9){throw "Safe opening deadline reached; stop rather than enter installer path"}
  Start-Sleep -Milliseconds 700
  $name=('actual-desktop-{0:d2}.png' -f $i);Real-Shot $name
  $windows=@([RealDesktopProbe]::Windows())
  $report.actual_screenshots+=@{file=$name;elapsed_seconds=$watch.Elapsed.TotalSeconds;visible_windows=$windows;new_windows=@($windows | Where-Object {$_ -notin $baseline})}
  Save-Report
 }
 $setup=@(Get-Process setup_gui -ErrorAction SilentlyContinue)
 $report.setup_process_seen=($setup.Count -gt 0)
 $report.native_opening_verified=($setup.Count -gt 0 -and $report.actual_screenshots.Count -eq 6)
 Save-Report
 if(-not $report.native_opening_verified){throw 'Real setup process did not appear within safe opening probe; inspect actual screen, do not simulate it'}
} finally {
 Get-Process setup_gui,IDM-SEMO -ErrorAction SilentlyContinue | Stop-Process -Force
 $report.probe_elapsed_seconds=$watch.Elapsed.TotalSeconds
 $report.stopped_before_installation=$true
 Save-Report
}
