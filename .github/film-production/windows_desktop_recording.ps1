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
 public static int Request1080(){IntPtr p=Marshal.AllocHGlobal(220);try{for(int i=0;i<220;i++)Marshal.WriteByte(p,i,0);Marshal.WriteInt16(p,68,220);if(!EnumDisplaySettings(null,-1,p))return -100;Marshal.WriteInt32(p,72,Marshal.ReadInt32(p,72)|0x180000);Marshal.WriteInt32(p,172,1920);Marshal.WriteInt32(p,176,1080);int test=ChangeDisplaySettings(p,2);return test==0?ChangeDisplaySettings(p,0):test;}finally{Marshal.FreeHGlobal(p);}}
}
'@
$modeResult=[FilmActualDisplay]::Request1080();Start-Sleep -Seconds 2
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
$args=@('-y','-v','warning','-f','gdigrab','-framerate','24','-draw_mouse','0','-i','desktop','-an','-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-threads','2','-movflags','+frag_keyframe+empty_moov','-t','1000',$video)
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
