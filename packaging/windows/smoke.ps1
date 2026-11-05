param([string]$Exe = (Join-Path $PSScriptRoot '../../artifacts/windows/IDM-SEMO-1.0.0-x86_64.exe'))
$ErrorActionPreference='Stop'
Add-Type @'
using System; using System.Text; using System.Collections.Generic; using System.Runtime.InteropServices;
public static class ConsoleWatch {
 public delegate bool Callback(IntPtr window,IntPtr state);
 [DllImport("user32.dll")]static extern bool EnumWindows(Callback callback,IntPtr state);
 [DllImport("user32.dll")]static extern bool IsWindowVisible(IntPtr window);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]static extern int GetClassName(IntPtr window,StringBuilder name,int length);
 public static string[] VisibleConsoles(){var result=new List<string>();foreach(var pair in VisibleWindowMap()){var parts=pair.Split(new[]{'|'},3);if(parts[1]=="ConsoleWindowClass"||parts[1]=="CASCADIA_HOSTING_WINDOW_CLASS")result.Add(parts[0]);}return result.ToArray();}
 public static string[] VisibleWindows(){var result=new List<string>();foreach(var pair in VisibleWindowMap()){result.Add(pair.Split(new[]{'|'},2)[1]);}return result.ToArray();}
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]static extern int GetWindowText(IntPtr window,StringBuilder text,int length);
 public static string[] VisibleWindowMapStub(){return VisibleWindowMap();}
 public static List<string> VisibleWindowMap(){var result=new List<string>();EnumWindows(delegate(IntPtr w,IntPtr s){var name=new StringBuilder(256);GetClassName(w,name,256);if(IsWindowVisible(w)){var text=new StringBuilder(256);GetWindowText(w,text,256);result.Add(w.ToString()+"|"+name.ToString()+"|"+text.ToString().Replace("|","/"));}return true;},IntPtr.Zero);return result;}
}
'@
$baseline=@()
foreach($entry in [ConsoleWatch]::VisibleWindowMap()){
 $parts=$entry.Split([char]'|',3)
 if($parts[1] -eq 'ConsoleWindowClass' -or $parts[1] -eq 'CASCADIA_HOSTING_WINDOW_CLASS'){$baseline+=$parts[0]}
}
$process=Start-Process -FilePath (Resolve-Path $Exe).Path -PassThru
# A console window that is merely mapped for a few milliseconds belongs to Windows'
# own startup noise (conhost of the shell host); a leaked CMD/PowerShell window
# stays visible. Track every new window, its class and title, plus visible length.
$firstSeen=@{}
$windowInfo=@{}
$unexpected=New-Object 'Collections.Generic.HashSet[string]'
$seenSetup=$false
$end=[DateTime]::UtcNow.AddSeconds(45)
while([DateTime]::UtcNow -lt $end){
 foreach($entry in [ConsoleWatch]::VisibleWindowMap()){
  $parts=$entry.Split([char]'|',3)
  $handle=$parts[0]; $class=$parts[1]; $title=if($parts.Count -gt 2){$parts[2]}else{''}
  if($baseline -contains $handle){continue}
  if(-not $firstSeen.ContainsKey($handle)){$firstSeen[$handle]=[DateTime]::UtcNow}
  $windowInfo[$handle]=@{class=$class;title=$title;visible_seconds=[math]::Round(([DateTime]::UtcNow-$firstSeen[$handle]).TotalSeconds,2)}
  if($class -eq 'ConsoleWindowClass' -or $class -eq 'CASCADIA_HOSTING_WINDOW_CLASS'){
   if($windowInfo[$handle].visible_seconds -ge 1.0){[void]$unexpected.Add($handle)}
  }
 }
 if(Get-Process setup_gui -ErrorAction SilentlyContinue){$seenSetup=$true}
 Start-Sleep -Milliseconds 35
}
$summary=@($windowInfo.Keys | ForEach-Object { [pscustomobject]@{handle=$_;class=$windowInfo[$_].class;title=$windowInfo[$_].title;visible_seconds=$windowInfo[$_].visible_seconds} })
@{setup_process_seen=$seenSetup;new_visible_console_windows=@($unexpected | ForEach-Object { $_ });new_visible_windows=$summary;console_visible_threshold_seconds=1.0;monitor_seconds=45;launcher_subsystem='Windows GUI';launcher_shell='none'} | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 (Join-Path (Split-Path (Resolve-Path $Exe).Path) 'no-console-smoke.json')
# Only this disposable runner's SEMO setup/app processes are stopped.
Get-Process setup_gui,IDM-SEMO -ErrorAction SilentlyContinue | Stop-Process -Force
if(!$seenSetup){throw 'EXE did not start the actual setup GUI'}
if($unexpected.Count -ne 0){throw 'A newly visible console window stayed visible for at least one second'}
Write-Host 'NATIVE_EXE_SMOKE_PASS: setup GUI launched, no newly visible CMD/PowerShell console in 45 seconds.'
