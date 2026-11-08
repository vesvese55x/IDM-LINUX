# Genuine desktop video, ordinary supported display mode; no synthetic window captures.
$ErrorActionPreference='Stop'
$out=Join-Path $PWD 'out/film-windows-opening'
New-Item -ItemType Directory -Force $out | Out-Null
Add-Type @'
using System;using System.Runtime.InteropServices;
public static class FilmActualDisplay {
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]static extern bool EnumDisplaySettings(string name,int mode,IntPtr dev);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]static extern int ChangeDisplaySettings(IntPtr dev,int flags);
 [DllImport("user32.dll")]public static extern int GetSystemMetrics(int metric);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]public static extern bool SystemParametersInfo(uint action,uint param,string value,uint flags);
 public delegate bool Callback(IntPtr w,IntPtr s);
 [DllImport("user32.dll")]static extern bool EnumWindows(Callback cb,IntPtr s);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)]static extern int GetWindowText(IntPtr w,System.Text.StringBuilder text,int n);
 [DllImport("user32.dll")]static extern bool ShowWindow(IntPtr w,int how);
 public static void MinimizeAgentConsole(){EnumWindows(delegate(IntPtr w,IntPtr s){var t=new System.Text.StringBuilder(2048);GetWindowText(w,t,2048);if(t.ToString().Contains("HostedComputeAgent"))ShowWindow(w,6);return true;},IntPtr.Zero);}
 public static int Request1080(){IntPtr p=Marshal.AllocHGlobal(220);try{for(int i=0;i<220;i++)Marshal.WriteByte(p,i,0);Marshal.WriteInt16(p,68,220);if(!EnumDisplaySettings(null,-1,p))return -100;Marshal.WriteInt32(p,72,Marshal.ReadInt32(p,72)|0x180000);Marshal.WriteInt32(p,172,1920);Marshal.WriteInt32(p,176,1080);int test=ChangeDisplaySettings(p,2);return test==0?ChangeDisplaySettings(p,0):test;}finally{Marshal.FreeHGlobal(p);}}
}
'@
$modeResult=[FilmActualDisplay]::Request1080();Start-Sleep -Seconds 2
# Ordinary real desktop preparation, never altering application pixels.
Set-TimeZone -Id 'Turkey Standard Time'
Add-Type -AssemblyName System.Drawing
$os=Get-CimInstance Win32_OperatingSystem;$cpu=Get-CimInstance Win32_Processor | Select-Object -First 1
$wall=[System.Drawing.Image]::FromFile((Join-Path $PWD '.github/film-production/wallpaper.png'))
$bmp=New-Object System.Drawing.Bitmap(1920,1080);$g=[System.Drawing.Graphics]::FromImage($bmp)
try{
 $g.DrawImage($wall,0,0,1920,1080)
 $bg=New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(220,14,20,30));$fg=[System.Drawing.Brushes]::White
 $g.FillRectangle($bg,20,820,350,195)
 $font=New-Object System.Drawing.Font('Segoe UI',10)
 $title=New-Object System.Drawing.Font('Segoe UI',16,[System.Drawing.FontStyle]::Bold)
 $g.DrawString('Windows',$title,$fg,30,830)
 $text=$os.Caption+"`n"+$os.Version+"`n"+$cpu.Name+"`n"+$env:NUMBER_OF_PROCESSORS+' mantıksal işlemci | '+[Math]::Round($os.TotalVisibleMemorySize/1MB,1)+' GiB RAM'
 $g.DrawString($text,$font,$fg,(New-Object System.Drawing.RectangleF(30,868,325,140)))
 $jpg=Join-Path $out 'actual-windows-wallpaper-and-hardware-card.jpg';$bmp.Save($jpg,[System.Drawing.Imaging.ImageFormat]::Jpeg)
}finally{$g.Dispose();$bmp.Dispose();$wall.Dispose()}
[void][FilmActualDisplay]::SystemParametersInfo(20,0,$jpg,3)
[FilmActualDisplay]::MinimizeAgentConsole()
$ff=Get-Command ffmpeg -ErrorAction SilentlyContinue
if(-not $ff){
 $zip=Join-Path $env:TEMP 'film-ffmpeg-official-linked-build.zip'
 Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $zip
 $tools=Join-Path $env:TEMP 'film-ffmpeg-tools'
 Expand-Archive $zip -DestinationPath $tools -Force
 $ff=Get-ChildItem $tools -Filter ffmpeg.exe -Recurse | Select-Object -First 1
 $ffmpeg=$ff.FullName
}else{$ffmpeg=$ff.Source}
if(-not $ffmpeg){throw 'No actual desktop recorder available'}
$meta=@{scope='Actual Windows gdigrab desktop, not DrawToBitmap or recreated UI';requested_display=@(1920,1080);display_change_return=$modeResult;actual_display=@([FilmActualDisplay]::GetSystemMetrics(0),[FilmActualDisplay]::GetSystemMetrics(1));frame_rate=24;finished_lesson=$false;final_film_export_allowed=$false}
$meta | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $out 'actual-video-capture-metadata.json')
$video=Join-Path $out 'uncut-windows-exe-and-native-wizard.mp4'
$err=Join-Path $out 'actual-desktop-recorder.log'
$args=@('-y','-v','warning','-f','gdigrab','-framerate','24','-draw_mouse','0','-i','desktop','-an','-c:v','libx264','-preset','ultrafast','-crf','18','-pix_fmt','yuv420p','-threads','2','-movflags','+frag_keyframe+empty_moov','-t','1000',$video)
$psi=New-Object Diagnostics.ProcessStartInfo
$psi.FileName=$ffmpeg;$psi.UseShellExecute=$false;$psi.CreateNoWindow=$true
$psi.RedirectStandardInput=$true;$psi.RedirectStandardError=$true
foreach($arg in $args){[void]$psi.ArgumentList.Add($arg)}
$rec=New-Object Diagnostics.Process;$rec.StartInfo=$psi;[void]$rec.Start()
$stderrRead=$rec.StandardError.ReadToEndAsync()
try{
 Start-Sleep -Seconds 2
 if($rec.HasExited){throw 'Actual desktop recorder exited before original EXE launch'}
 & './.github/film-production/windows_opening_probe.ps1'
 if(-not $?){throw 'Actual Windows opening/install probe failed'}
 Start-Sleep -Seconds 8
}finally{
 # Ask ffmpeg itself to close the real video cleanly, never kill mid-packet.
 if(-not $rec.HasExited){$rec.StandardInput.WriteLine('q');$rec.StandardInput.Flush();if(-not $rec.WaitForExit(15000)){$rec.Kill();$rec.WaitForExit()}}
 $stderrRead.GetAwaiter().GetResult() | Set-Content -Encoding utf8 $err
 $meta.recorder_exit_code=$rec.ExitCode
 if(Test-Path $video){$meta.video_bytes=(Get-Item $video).Length}
 $meta | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $out 'actual-video-capture-metadata.json')
}
if(-not (Test-Path $video) -or (Get-Item $video).Length -lt 10000){throw 'No genuine desktop video captured'}
