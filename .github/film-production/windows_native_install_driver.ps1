# Actual existing controls + physical mouse. No product source/binary, trial or license modifications.
$ErrorActionPreference='Stop'
Add-Type @'
using System;using System.Text;using System.Collections.Generic;using System.Runtime.InteropServices;
public static class ActualControlClick {
 public delegate bool Callback(IntPtr w,IntPtr s);
 [StructLayout(LayoutKind.Sequential)]public struct RECT {public int L,T,R,B;}
 [DllImport("user32.dll")]static extern bool EnumWindows(Callback cb,IntPtr s);
 [DllImport("user32.dll")]static extern bool EnumChildWindows(IntPtr p,Callback cb,IntPtr s);
 [DllImport("user32.dll")]static extern bool IsWindowVisible(IntPtr w);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]static extern int GetClassName(IntPtr w,StringBuilder c,int n);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]static extern IntPtr SendMessageTimeout(IntPtr w,uint m,IntPtr n,StringBuilder text,uint flags,uint timeout,out IntPtr copied);
 [DllImport("user32.dll")]static extern bool GetWindowRect(IntPtr w,out RECT r);
 [DllImport("user32.dll")]static extern bool SetForegroundWindow(IntPtr w);
 [DllImport("user32.dll")]static extern int GetSystemMetrics(int metric);
 [DllImport("user32.dll")]static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")]static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
 public static string Text(long h){var b=new StringBuilder(2048);IntPtr got;SendMessageTimeout(new IntPtr(h),13,new IntPtr(2048),b,2,300,out got);return b.ToString();}
 public static string[] Controls(){var a=new List<string>();Callback cb=delegate(IntPtr w,IntPtr s){if(IsWindowVisible(w)){var c=new StringBuilder(256);GetClassName(w,c,256);if(c.ToString().Contains("BUTTON")){RECT r;GetWindowRect(w,out r);a.Add(w.ToInt64()+"|"+r.L+","+r.T+","+r.R+","+r.B+"|"+Text(w.ToInt64()).Replace("\n"," ").Replace("\r",""));}}return true;};EnumWindows(delegate(IntPtr w,IntPtr s){EnumChildWindows(w,cb,IntPtr.Zero);return true;},IntPtr.Zero);return a.ToArray();}
 public static int[] Click(long h){var w=new IntPtr(h);if(!IsWindowVisible(w))throw new Exception("Actual control is not visible");RECT r;GetWindowRect(w,out r);int x=(r.L+r.R)/2,y=(r.T+r.B)/2;if(x<0||y<0||x>=GetSystemMetrics(0)||y>=GetSystemMetrics(1))throw new Exception("Actual target outside real display");SetCursorPos(x,y);mouse_event(2,0,0,0,UIntPtr.Zero);mouse_event(4,0,0,0,UIntPtr.Zero);return new[]{x,y};}
}
'@
$installReport=@{scope='Actual Windows project GUI language selection and native IDM automatic installation; no EULA/Next/Finish claim';native_idm_initially_present=$false;physical_actions=@();native_install_completed=$false;manual_vendor_wizard_recorded=$false;final_film_export_allowed=$false}
function Save-Install {$installReport | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $out 'actual-windows-native-install.json')}
function Button-Match($pattern){
 $rows=@([ActualControlClick]::Controls() | Where-Object {($_.Split([char]'|',3)[2]) -match $pattern})
 if($rows.Count -ne 1){[ActualControlClick]::Controls() | Set-Content -Encoding utf8 (Join-Path $out 'stopped-actual-controls.txt');throw "Need one actual visible button matching $pattern, got $($rows.Count)"}
 return [long]$rows[0].Split([char]'|',3)[0]
}
function Actual-Click($handle,$purpose){
 $text=[ActualControlClick]::Text($handle);$point=[ActualControlClick]::Click($handle)
 $installReport.physical_actions+=@{purpose=$purpose;actual_caption=$text;handle=$handle;physical_point=$point;utc=[DateTime]::UtcNow.ToString('o')};Save-Install;Start-Sleep -Milliseconds 700
}
$nativePaths=@("${env:ProgramFiles(x86)}\Internet Download Manager\IDMan.exe","$env:ProgramFiles\Internet Download Manager\IDMan.exe")
if(@($nativePaths | Where-Object {Test-Path $_}).Count -ne 0){throw 'Expected clean native installation; never reset an existing installation'}
Save-Install
$installNav=Button-Match '^Install & Update$'
$start=Button-Match '^Start Operation Now$'
$languageNav=Button-Match '^Language Selection'
Actual-Click $languageNav 'Open actual language page'
Real-Shot 'native-install-01-language-page.png'
$turkish=Button-Match '^Türkçe'
Actual-Click $turkish 'Select actual Turkish option'
Real-Shot 'native-install-02-turkish-selected.png'
Actual-Click $installNav 'Return to actual installer page'
Real-Shot 'native-install-03-before-start.png'
$installReport.actual_turkish_start_caption=[ActualControlClick]::Text($start)
Actual-Click $start 'Start actual project native Windows IDM installation'
$deadline=[DateTime]::UtcNow.AddMinutes(12);$found=$null;$n=0
while([DateTime]::UtcNow -lt $deadline){
 Start-Sleep -Seconds 2
 Real-Shot ('native-install-progress-{0:d3}.png' -f $n);$n++
 $found=@($nativePaths | Where-Object {Test-Path $_}) | Select-Object -First 1
 if($found){Start-Sleep -Seconds 5;break}
}
$installReport.actual_buttons_after=[ActualControlClick]::Controls();Save-Install
if(-not $found){throw 'No native installed executable appeared; preserve real error/UI rather than declare success'}
$signature=Get-AuthenticodeSignature $found
$installReport.native_installed_path=$found
$installReport.native_executable_sha256=(Get-FileHash $found -Algorithm SHA256).Hash.ToLowerInvariant()
$installReport.authenticode_status=[string]$signature.Status
$installReport.signer_subject=if($signature.SignerCertificate){$signature.SignerCertificate.Subject}else{''}
$installReport.file_version=(Get-Item $found).VersionInfo.FileVersion
if($signature.Status -ne 'Valid' -or $installReport.signer_subject -notmatch 'Tonec'){Save-Install;throw 'Native executable must have a valid actual vendor signature'}
$registrations=@(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue | Where-Object {$_.DisplayName -eq 'Internet Download Manager'})
$installReport.native_uninstall_registration=@($registrations | Select-Object DisplayName,DisplayVersion,Publisher,InstallLocation)
if($registrations.Count -eq 0){Save-Install;throw 'Native installer registry registration not verified'}
$installReport.native_install_completed=$true
Save-Install
Real-Shot 'native-install-04-installed-verified.png'
