$ErrorActionPreference='Stop'
$nativeInstall=$env:FILM_WINDOWS_INSTALL_IDM -eq 'true'
$followup=($env:FILM_WINDOWS_PANEL_FOLLOWUP -eq 'true') -or $nativeInstall
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
# Preserve authoritative public C# sources for inspection before any native IDM install.
$sourceOut=Join-Path $out 'authoritative-csharp';New-Item -ItemType Directory -Force $sourceOut | Out-Null
Get-ChildItem 'artifacts/windows/payload' -Filter '*.cs' | Copy-Item -Destination $sourceOut
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
if($env:FILM_WINDOWS_LAUNCH_CMD -eq 'true'){
 $bat=(Resolve-Path 'belgeselsemo-idm-windows-installer.bat').Path
 $report.scope='Actual original BAT launched via Windows CMD; actual native desktop evidence, not a simulated terminal'
 $report.actual_cmd_launch=$true;$report.actual_bat_sha256=(Get-FileHash $bat -Algorithm SHA256).Hash.ToLowerInvariant()
 $p=Start-Process -FilePath $env:ComSpec -ArgumentList ('/c ""'+$bat+'""') -PassThru
}else{$p=Start-Process -FilePath $exe -PassThru}
try {
 # Short bounded opening probe; stop before the documented sixteen-second auto path.
 $frames=if($followup){40}else{6}
 for($i=0;$i -lt $frames;$i++){
  if(-not $followup -and $watch.Elapsed.TotalSeconds -gt 9){throw "Safe opening deadline reached; stop rather than enter installer path"}
  if(Get-Process IDMan -ErrorAction SilentlyContinue){throw 'Unexpected native IDM launch; no install is authorized by this opening-only probe'}
  Start-Sleep -Milliseconds 700
  $name=('actual-desktop-{0:d2}.png' -f $i);Real-Shot $name
  $windows=@([RealDesktopProbe]::Windows())
  $report.actual_screenshots+=@{file=$name;elapsed_seconds=$watch.Elapsed.TotalSeconds;visible_windows=$windows;new_windows=@($windows | Where-Object {$_ -notin $baseline})}
  Save-Report
 }
 $setup=@(Get-Process setup_gui -ErrorAction SilentlyContinue)
 $report.setup_process_seen=($setup.Count -gt 0)
 $report.automatic_panel_followup_requested=$followup
 $report.authoritative_sources_preserved=$true
 $report.native_idm_installation_started=$false
 $report.wrapper_setup_may_extract_files=$true
 $report.native_opening_verified=($report.actual_screenshots.Count -eq $frames -and @($report.actual_screenshots | Where-Object {$_.new_windows.Count -gt 0}).Count -gt 0)
 Save-Report
 if($nativeInstall){& './.github/film-production/windows_native_install_driver.ps1';if(-not $?){throw 'Actual native install driver failed'}}
 if(-not $report.native_opening_verified){throw 'Real setup process did not appear within safe opening probe; inspect actual screen, do not simulate it'}
} finally {
 Get-Process setup_gui,IDM-SEMO,IDM_SEMO_GUI -ErrorAction SilentlyContinue | Stop-Process -Force
 if(-not $p.HasExited){Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue}
 $report.probe_elapsed_seconds=$watch.Elapsed.TotalSeconds
 $report.stopped_before_native_idm_installation=(-not $nativeInstall)
 $report.stopped_before_installation=$null
 $report.note='Wrapper setup itself extracts and compiles application files. This is not proof of native IDM installation.'
 Save-Report
}
