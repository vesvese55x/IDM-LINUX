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
 [DllImport("user32.dll")]public static extern bool IsWindowEnabled(IntPtr w);
 [DllImport("user32.dll")]static extern uint GetWindowThreadProcessId(IntPtr w,out uint pid);
 [DllImport("user32.dll",EntryPoint="SendMessageTimeoutW")]static extern IntPtr ReadMessage(IntPtr w,uint msg,IntPtr a,IntPtr b,uint flags,uint timeout,out IntPtr value);
 public static bool Checked(long h){IntPtr v;ReadMessage(new IntPtr(h),240,IntPtr.Zero,IntPtr.Zero,2,300,out v);return v.ToInt64()==1;}
 public static int OwnerPid(long h){uint pid;GetWindowThreadProcessId(new IntPtr(h),out pid);return (int)pid;}
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]static extern int GetClassName(IntPtr w,StringBuilder c,int n);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]static extern IntPtr SendMessageTimeout(IntPtr w,uint m,IntPtr n,StringBuilder text,uint flags,uint timeout,out IntPtr copied);
 [DllImport("user32.dll")]static extern bool GetWindowRect(IntPtr w,out RECT r);
 [DllImport("user32.dll")]static extern bool SetForegroundWindow(IntPtr w);
 [DllImport("user32.dll")]static extern int GetSystemMetrics(int metric);
 [DllImport("user32.dll")]static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")]static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
 public static string Text(long h){var b=new StringBuilder(2048);IntPtr got;SendMessageTimeout(new IntPtr(h),13,new IntPtr(2048),b,2,300,out got);return b.ToString();}
 public static string[] Controls(){var a=new List<string>();Callback cb=delegate(IntPtr w,IntPtr s){if(IsWindowVisible(w)){var c=new StringBuilder(256);GetClassName(w,c,256);if(c.ToString().ToUpperInvariant().Contains("BUTTON")){RECT r;GetWindowRect(w,out r);a.Add(w.ToInt64()+"|"+r.L+","+r.T+","+r.R+","+r.B+"|"+Text(w.ToInt64()).Replace("\n"," ").Replace("\r",""));}}return true;};EnumWindows(delegate(IntPtr w,IntPtr s){EnumChildWindows(w,cb,IntPtr.Zero);return true;},IntPtr.Zero);return a.ToArray();}
 public static int[] Click(long h){var w=new IntPtr(h);if(!IsWindowVisible(w))throw new Exception("Actual control is not visible");RECT r;GetWindowRect(w,out r);int x=(r.L+r.R)/2,y=(r.T+r.B)/2;if(x<0||y<0||x>=GetSystemMetrics(0)||y>=GetSystemMetrics(1))throw new Exception("Actual target outside real display");SetCursorPos(x,y);mouse_event(2,0,0,0,UIntPtr.Zero);mouse_event(4,0,0,0,UIntPtr.Zero);return new[]{x,y};}
}
'@
$installReport=@{scope='Actual Windows project GUI language selection and native IDM installation; wizard steps only reported when actual signed vendor controls were physically clicked';native_idm_initially_present=$false;physical_actions=@();native_install_completed=$false;manual_vendor_wizard_recorded=$false;final_film_export_allowed=$false}
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
# Choose the ordinary manual browser-extension route, explicitly not auto-store success.
# The previous default run genuinely opened an unavailable store link; preserve that
# evidence for troubleshooting instead of claiming the extension installed.
$autoBrowser=Button-Match '^Tarayıcı Eklentisini Otomatik Aç & Kur$'
if([ActualControlClick]::Checked($autoBrowser)){Actual-Click $autoBrowser 'Choose manual separate browser-extension setup, not automatic store opening'}
$installReport.browser_extension_step_separate_and_not_verified=$true
$installReport.auto_store_open_disabled_by_explicit_normal_UI_choice=$true
Real-Shot 'native-install-03b-manual-browser-extension-choice.png'
$installReport.actual_turkish_start_caption=[ActualControlClick]::Text($start)
Actual-Click $start 'Start actual project native Windows IDM installation'
$deadline=[DateTime]::UtcNow.AddMinutes(12);$found=$null;$n=0
while([DateTime]::UtcNow -lt $deadline){
 Start-Sleep -Seconds 2
 Real-Shot ('native-install-progress-{0:d3}.png' -f $n);$n++
 # Official fallback really opens its vendor wizard: /VERYSILENT is not honored.
 # Only physically click enabled, explicitly whitelisted controls whose owning
 # executable has a VALID Tonec signature. Never registration, purchase or reset.
 $wizardClicked=$false
 foreach($row in [ActualControlClick]::Controls()){
  $parts=$row.Split([char]'|',3);$h=[long]$parts[0];$caption=$parts[2].Replace('&','').Trim()
  if($caption -notmatch '^(Next\s*>?|Install|Finish\s*>?|I accept the terms.*|I agree.*)$'){continue}
  if(-not [ActualControlClick]::IsWindowEnabled([IntPtr]$h)){continue}
  $owner=Get-Process -Id ([ActualControlClick]::OwnerPid($h)) -ErrorAction SilentlyContinue
  if(-not $owner -or -not $owner.Path){continue}
  if($caption -match '^I (accept|agree)' -and [ActualControlClick]::Checked($h)){continue}
  # The signed SFX may create its real wizard in an extracted child process.
  # Trust only the actual signed official setup or a bounded, observed descendant.
  $current=$owner;$trusted=$false;$chain=@();$sig=$null
  for($depth=0;$depth -lt 6 -and $current;$depth++){
   $chain+=@{id=$current.Id;name=$current.ProcessName;path=$current.Path}
   if($current.ProcessName -eq 'semo_idm_setup'){
    $sig=Get-AuthenticodeSignature $current.Path
    $trusted=($sig.Status -eq 'Valid' -and $sig.SignerCertificate.Subject -match 'Tonec');break
   }
   $pi=Get-CimInstance Win32_Process -Filter ('ProcessId='+$current.Id) -ErrorAction SilentlyContinue
   if(-not $pi -or -not $pi.ParentProcessId){break}
   $current=Get-Process -Id $pi.ParentProcessId -ErrorAction SilentlyContinue
  }
  if(-not $trusted){
   $package=Join-Path $env:TEMP 'semo_idm_setup.exe'
   if(Test-Path $package){
    $sig=Get-AuthenticodeSignature $package
    $installReport.actual_original_setup_signature_status=[string]$sig.Status
    if($sig.Status -eq 'Valid' -and $sig.SignerCertificate.Subject -match 'Tonec'){
     $env:PYTHONPATH=Join-Path $PWD 'src'
     & python './.github/film-production/verify_vendor_wizard_payload.py' $package $owner.Path (Join-Path $out 'actual-vendor-wizard-payload-equality.json')
     $trusted=($LASTEXITCODE -eq 0)
    }
   }
  }
  if(-not $trusted){
   $installReport.unverified_wizard_candidate=@{caption=$caption;chain=$chain;signature_status=if($sig){[string]$sig.Status}else{'No signed setup ancestor found'}}
   Save-Install;Real-Shot 'stopped-unverified-vendor-wizard.png'
   throw 'Visible installer wizard owner/signature could not be verified; do not click or wait falsely'
  }
  $installReport.actual_verified_vendor_wizard_process_chain=$chain
  Real-Shot ('vendor-wizard-before-{0:d3}.png' -f $n)
  Actual-Click $h ('Actual signed Tonec installer control: '+$caption)
  $installReport.manual_vendor_wizard_recorded=$true
  $installReport.vendor_wizard_signer_subject=$sig.SignerCertificate.Subject
  Save-Install;$wizardClicked=$true;break
 }
 $found=@($nativePaths | Where-Object {Test-Path $_}) | Select-Object -First 1
 $wizardAlive=@(Get-Process -ErrorAction SilentlyContinue | Where-Object {$_.ProcessName -like 'IDM*.tmp' -and $_.Path -like (Join-Path $env:TEMP 'IDM_Setup_Temp\*')})
 if($found -and -not $wizardClicked -and $wizardAlive.Count -eq 0 -and -not (Get-Process semo_idm_setup -ErrorAction SilentlyContinue)){Start-Sleep -Seconds 5;break}
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
$installReport.actual_finish_button_clicked=@($installReport.physical_actions | Where-Object {$_.actual_caption.Replace('&','').Trim() -match '^Finish\s*>?$'}).Count -gt 0
$installReport.native_install_completed=$true
Save-Install
Real-Shot 'native-install-04-installed-verified.png'
