param([string]$BuildDirectory = (Join-Path $PSScriptRoot '../../artifacts/windows'), [string]$ScreenshotDirectory = (Join-Path $PSScriptRoot '../../promo/assets/screens/idm-semo'))
$ErrorActionPreference = 'Stop'
$BuildDirectory = (Resolve-Path $BuildDirectory).Path
New-Item -ItemType Directory -Force $ScreenshotDirectory | Out-Null
$ScreenshotDirectory = (Resolve-Path $ScreenshotDirectory).Path
$csc = "$env:WINDIR/Microsoft.NET/Framework64/v4.0.30319/csc.exe"
$payload = Join-Path $BuildDirectory 'payload'
# Keep production assets next to the capture binary, just as the installed app.
Get-ChildItem $payload -File | Copy-Item -Destination $BuildDirectory -Force
$sources = @(Get-ChildItem $payload -Filter 'IDM_SEMO_*.cs' | ForEach-Object { $_.FullName })
$capture = Join-Path $BuildDirectory 'NativeCapture.exe'
$harnessSource = (Resolve-Path (Join-Path $PSScriptRoot 'Capture.cs')).Path
$harnessManifest = (Resolve-Path (Join-Path $PSScriptRoot 'launcher.manifest')).Path
Write-Host "Native harness source: $harnessSource"
& $csc /nologo /target:exe /main:NativeCapture /codepage:65001 "/out:$capture" "/win32manifest:$harnessManifest" /r:System.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll @sources $harnessSource
if ($LASTEXITCODE -ne 0) { throw 'Native capture compilation failed' }
& $capture $ScreenshotDirectory | Tee-Object (Join-Path $BuildDirectory 'native-capture.log')
if ($LASTEXITCODE -ne 0) { throw 'Native GUI layout/capture failed' }
$files = @(Get-ChildItem $ScreenshotDirectory -Filter '*.png' | ForEach-Object { @{ name=$_.Name; sha256=(Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); bytes=$_.Length } })
if ($files.Count -lt 10) { throw 'Expected all ten real GUI pages' }
@{ platform=[Environment]::OSVersion.ToString(); runner=$env:RUNNER_OS; source_commit=$env:GITHUB_SHA; renderer='Real Windows WinForms controls, DrawToBitmap; no synthetic UI'; capture_utc=[DateTime]::UtcNow.ToString('o'); images=$files } | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $ScreenshotDirectory 'capture-manifest.json')
