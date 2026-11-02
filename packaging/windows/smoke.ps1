param([string]$Exe = (Join-Path $PSScriptRoot '../../artifacts/windows/IDM-SEMO-1.0.0-x86_64.exe'))
$ErrorActionPreference='Stop'
Add-Type @'
using System; using System.Text; using System.Collections.Generic; using System.Runtime.InteropServices;
public static class ConsoleWatch {
 public delegate bool Callback(IntPtr window,IntPtr state);
 [DllImport("user32.dll")]static extern bool EnumWindows(Callback callback,IntPtr state);
 [DllImport("user32.dll")]static extern bool IsWindowVisible(IntPtr window);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]static extern int GetClassName(IntPtr window,StringBuilder name,int length);
 public static string[] VisibleConsoles(){var result=new List<string>();EnumWindows(delegate(IntPtr w,IntPtr s){var name=new StringBuilder(256);GetClassName(w,name,256);if(IsWindowVisible(w)&&(name.ToString()=="ConsoleWindowClass"||name.ToString()=="CASCADIA_HOSTING_WINDOW_CLASS"))result.Add(w.ToString());return true;},IntPtr.Zero);return result.ToArray();}
}
'@
$baseline=@([ConsoleWatch]::VisibleConsoles())
$process=Start-Process -FilePath (Resolve-Path $Exe).Path -PassThru
$unexpected=New-Object 'Collections.Generic.HashSet[string]'
$seenSetup=$false
$end=[DateTime]::UtcNow.AddSeconds(45)
while([DateTime]::UtcNow -lt $end){
 foreach($window in [ConsoleWatch]::VisibleConsoles()){if($baseline -notcontains $window){[void]$unexpected.Add($window)}}
 if(Get-Process setup_gui -ErrorAction SilentlyContinue){$seenSetup=$true}
 Start-Sleep -Milliseconds 35
}
@{setup_process_seen=$seenSetup;new_visible_console_windows=@($unexpected | ForEach-Object { $_ });monitor_seconds=45;launcher_subsystem='Windows GUI';launcher_shell='none'} | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path (Split-Path (Resolve-Path $Exe).Path) 'no-console-smoke.json')
# Only this disposable runner's SEMO setup/app processes are stopped.
Get-Process setup_gui,IDM-SEMO -ErrorAction SilentlyContinue | Stop-Process -Force
if(!$seenSetup){throw 'EXE did not start the actual setup GUI'}
if($unexpected.Count -ne 0){throw 'A newly visible console window was observed'}
Write-Host 'NATIVE_EXE_SMOKE_PASS: setup GUI launched, no newly visible CMD/PowerShell console in 45 seconds.'
