# Editorial reference only: unmodified public CAB sources, actual Windows desktop.
# Never starts an IDM install, download, registration, purchase, trial reset or license action.
$ErrorActionPreference='Stop'
$out=Join-Path $PWD 'out/film-english-windows-reference'
$work=Join-Path $env:RUNNER_TEMP 'film-english-semo-reference'
New-Item -ItemType Directory -Force $out,$work | Out-Null
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
if(-not [Environment]::UserInteractive){throw 'Actual interactive Windows desktop required'}
$report=@{scope='English SEMO reference, not a movie or download demonstration';source_commit=$env:GITHUB_SHA;product_source_modified=$false;source_type='Authoritative repository BAT CAB sources, compiled unchanged';native_idm_installed=$false;download_executed=$false;license_or_trial_action=$false;draw_to_bitmap_used=$false;screenshots=@();navigation=@()}
function Receipt {$report | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $out 'reference-receipt.json')}
Receipt
$text=[IO.File]::ReadAllText((Join-Path $PWD 'belgeselsemo-idm-windows-installer.bat'),[Text.Encoding]::UTF8)
$marker="___SEMO_PAYLOAD___`r`n";$i=$text.IndexOf($marker,[StringComparison]::Ordinal)
if($i -lt 0){throw 'Authoritative CAB marker missing'}
$cab=Join-Path $work 'payload.cab';[IO.File]::WriteAllBytes($cab,[Convert]::FromBase64String($text.Substring($i+$marker.Length)))
& "$env:WINDIR/System32/expand.exe" $cab '-F:*' $work | Out-Null
if($LASTEXITCODE -ne 0){throw 'CAB extraction failed'}
# Preserve the CAB's complete Windows dictionaries. Linux dictionaries lack SEMO-only keys.
$english=Join-Path $work 'en.txt'
if(-not (Test-Path $english) -or -not (Select-String -Path $english -Pattern '^semo\.nav_p2p\s*=' -Quiet)){throw 'Authoritative Windows English dictionary missing'}
$report.english_dictionary_sha256=(Get-FileHash $english -Algorithm SHA256).Hash.ToLowerInvariant()
Copy-Item $english (Join-Path $out 'authoritative-Windows-en.txt')
Copy-Item (Join-Path $work 'tr.txt') (Join-Path $out 'authoritative-Windows-tr.txt')
$settingsDir=Join-Path $env:APPDATA 'IDM_SEMO';New-Item -ItemType Directory -Force $settingsDir | Out-Null
[IO.File]::WriteAllText((Join-Path $settingsDir 'settings.ini'),"lang=en`r`nwarm=0`r`ncapture=0`r`nclip=0`r`n",[Text.Encoding]::UTF8)
$paths=@("${env:ProgramFiles(x86)}\Internet Download Manager\IDMan.exe","$env:ProgramFiles\Internet Download Manager\IDMan.exe")
if(@($paths | Where-Object {Test-Path $_}).Count -gt 0){throw 'Expected clean reference runner; do not touch an existing IDM installation'}
$csc="$env:WINDIR/Microsoft.NET/Framework64/v4.0.30319/csc.exe";$exe=Join-Path $work 'IDM-SEMO-reference.exe'
$sources=@(Get-ChildItem $work -Filter 'IDM_SEMO_*.cs' | ForEach-Object {$_.FullName})
if($sources.Count -lt 3){throw 'Original application sources missing'}
$report.source_hashes=@($sources | ForEach-Object {@{name=[IO.Path]::GetFileName($_);sha256=(Get-FileHash $_ -Algorithm SHA256).Hash.ToLowerInvariant()}})
& $csc /nologo /target:winexe /codepage:65001 "/out:$exe" /r:System.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll $sources
if($LASTEXITCODE -ne 0){throw 'Compilation of unmodified application failed'}
$report.executable_sha256=(Get-FileHash $exe -Algorithm SHA256).Hash.ToLowerInvariant()
Add-Type @'
using System;using System.Collections.Generic;using System.Runtime.InteropServices;using System.Text;
public static class EnglishReferenceDesktop {
 public delegate bool CB(IntPtr h,IntPtr p);
 [StructLayout(LayoutKind.Sequential)]public struct R {public int L,T,X,B;}
 [DllImport("user32.dll")]static extern bool EnumChildWindows(IntPtr p,CB cb,IntPtr x);
 [DllImport("user32.dll")]static extern bool IsWindowVisible(IntPtr w);
 [DllImport("user32.dll")]static extern bool IsWindowEnabled(IntPtr w);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]static extern int GetClassName(IntPtr w,StringBuilder s,int n);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]static extern int GetWindowText(IntPtr w,StringBuilder s,int n);
 [DllImport("user32.dll")]static extern bool GetWindowRect(IntPtr w,out R r);
 [DllImport("user32.dll")]static extern bool SetForegroundWindow(IntPtr w);
 [DllImport("user32.dll")]static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")]static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
 public static string[] Buttons(long root){var a=new List<string>();EnumChildWindows(new IntPtr(root),delegate(IntPtr w,IntPtr p){var c=new StringBuilder(256);GetClassName(w,c,256);if(IsWindowVisible(w)&&IsWindowEnabled(w)&&c.ToString().ToUpperInvariant().Contains("BUTTON")){var s=new StringBuilder(1024);GetWindowText(w,s,1024);R r;GetWindowRect(w,out r);a.Add(w+"|"+r.L+","+r.T+","+r.X+","+r.B+"|"+s);}return true;},IntPtr.Zero);return a.ToArray();}
 public static void Click(long h,long root){var w=new IntPtr(h);if(!IsWindowVisible(w)||!IsWindowEnabled(w))throw new Exception("Not visible or enabled");SetForegroundWindow(new IntPtr(root));R r;GetWindowRect(w,out r);SetCursorPos((r.L+r.X)/2,(r.T+r.B)/2);mouse_event(2,0,0,0,UIntPtr.Zero);mouse_event(4,0,0,0,UIntPtr.Zero);}
}
'@
function Shot($name){$bounds=[Windows.Forms.Screen]::PrimaryScreen.Bounds;$b=New-Object Drawing.Bitmap($bounds.Width,$bounds.Height);$g=[Drawing.Graphics]::FromImage($b);try{$g.CopyFromScreen($bounds.Location,[Drawing.Point]::Empty,$bounds.Size);$b.Save((Join-Path $out $name),[Drawing.Imaging.ImageFormat]::Png)}finally{$g.Dispose();$b.Dispose()};$report.screenshots+=@{file=$name;width=$bounds.Width;height=$bounds.Height};Receipt}
$p=Start-Process $exe -WorkingDirectory $work -PassThru
try {
 Start-Sleep -Seconds 5;$p.Refresh();if($p.HasExited -or $p.MainWindowHandle -eq 0){throw 'Actual SEMO window did not open'}
 Shot '00-actual-English-SEMO-installation-page.png'
 $root=$p.MainWindowHandle.ToInt64();$rows=@([EnglishReferenceDesktop]::Buttons($root));$rows | Set-Content -Encoding utf8 (Join-Path $out 'actual-button-captions.txt')
 $jobs=@(@('Overview','01-overview'),@('Browsers','02-browsers'),@('Capture','03-settings'),@('Doctor','04-doctor'),@('Other Projects','05-projects'),@('Language Selection','06-languages'),@('About IDM','07-about'),@('Torrent.*eD2K','08-p2p'))
 foreach($job in $jobs){
  $matches=@([EnglishReferenceDesktop]::Buttons($root) | Where-Object {($_.Split([char]'|',3)[2]) -match $job[0]})
  if($matches.Count -ne 1){throw "Expected one actual sidebar control: $($job[0]); got $($matches.Count)"}
  $row=$matches[0];$caption=$row.Split([char]'|',3)[2]
  if($caption -match '(?i)reset|trial|license|start operation|install now'){throw 'Forbidden action caption'}
  [EnglishReferenceDesktop]::Click([long]$row.Split([char]'|',3)[0],$root);Start-Sleep -Milliseconds 900
  $report.navigation+=@{caption=$caption;purpose='Read-only page navigation'};Shot ($job[1]+'.png')
 }
 if(Get-Process IDMan -ErrorAction SilentlyContinue){throw 'Unexpected native IDM process: reference is not authorized to install or run it'}
 $report.status='ACTUAL_ENGLISH_SEMO_REFERENCE_CAPTURED';Receipt
}finally{if(-not $p.HasExited){Stop-Process -Id $p.Id -Force};Receipt}
