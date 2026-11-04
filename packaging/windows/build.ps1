param([string]$BatFile = (Join-Path $PSScriptRoot '../../belgeselsemo-idm-windows-installer.bat'), [string]$OutputDirectory = (Join-Path $PSScriptRoot '../../artifacts/windows'))
$ErrorActionPreference = 'Stop'
$BatFile = (Resolve-Path $BatFile).Path
New-Item -ItemType Directory -Force $OutputDirectory | Out-Null
$OutputDirectory = (Resolve-Path $OutputDirectory).Path
$payload = Join-Path $OutputDirectory 'payload'
New-Item -ItemType Directory -Force $payload | Out-Null
$text = [IO.File]::ReadAllText($BatFile, [Text.Encoding]::UTF8)
$marker = "___SEMO_PAYLOAD___`r`n"
$i = $text.IndexOf($marker, [StringComparison]::Ordinal)
if ($i -lt 0) { throw 'BAT payload marker missing' }
$cab = Join-Path $OutputDirectory 'payload.cab'
[IO.File]::WriteAllBytes($cab, [Convert]::FromBase64String($text.Substring($i + $marker.Length)))
& "$env:WINDIR/System32/expand.exe" $cab '-F:*' $payload | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'CAB extraction failed' }
$sha = (Get-FileHash $BatFile -Algorithm SHA256).Hash.ToLowerInvariant()
$source = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'Launcher.cs')).Replace('@@BAT_SHA256@@', $sha)
$generated = Join-Path $OutputDirectory 'Launcher.generated.cs'
[IO.File]::WriteAllText($generated, $source, (New-Object Text.UTF8Encoding($false)))
$csc = Join-Path ([Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()) 'csc.exe'
if (!(Test-Path $csc)) { $csc = "$env:WINDIR/Microsoft.NET/Framework64/v4.0.30319/csc.exe" }
# Compile the actual CAB sources and exercise routing without starting IDM or altering its registry.
$sourceCheck = Join-Path $OutputDirectory 'WindowsSources.dll'
$payloadSources = @(Get-ChildItem (Join-Path $payload 'IDM_SEMO_*.cs') | ForEach-Object { $_.FullName })
& $csc /nologo /target:library /codepage:65001 "/out:$sourceCheck" /r:System.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll $payloadSources
if ($LASTEXITCODE -ne 0) { throw 'Authoritative CAB source compilation failed' }
$routeTest = Join-Path $OutputDirectory 'RouteRegression.exe'
& $csc /nologo /target:exe "/out:$routeTest" "/r:$sourceCheck" /r:System.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll (Join-Path $PSScriptRoot 'RouteRegression.cs')
if ($LASTEXITCODE -ne 0) { throw 'Windows routing test compilation failed' }
& $routeTest
if ($LASTEXITCODE -ne 0) { throw 'Windows routing regressions failed' }
$exe = Join-Path $OutputDirectory 'IDM-SEMO-1.0.0-x86_64.exe'
& $csc /nologo /target:winexe /platform:x64 /codepage:65001 "/out:$exe" "/win32icon:$PSScriptRoot/idm-semo.ico" "/win32manifest:$PSScriptRoot/launcher.manifest" "/resource:$BatFile,SEMO.Installer.bat" "/resource:$PSScriptRoot/idm-semo.ico,SEMO.Icon.ico" /r:System.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll $generated
if ($LASTEXITCODE -ne 0) { throw 'Windows EXE build failed' }
# Verify architecture, graphical subsystem and the byte-exact authoritative BAT resource.
$bytes = [IO.File]::ReadAllBytes($exe); $pe = [BitConverter]::ToInt32($bytes, 0x3c)
if ([BitConverter]::ToUInt16($bytes, $pe + 4) -ne 0x8664) { throw 'Expected AMD64 PE' }
if ([BitConverter]::ToUInt16($bytes, $pe + 24 + 68) -ne 2) { throw 'Expected Windows GUI subsystem, not console' }
$assembly = [Reflection.Assembly]::LoadFile($exe)
$stream = $assembly.GetManifestResourceStream('SEMO.Installer.bat')
$embeddedHash = [Security.Cryptography.SHA256]::Create().ComputeHash($stream); $stream.Dispose()
if ([BitConverter]::ToString($embeddedHash).Replace('-', '').ToLowerInvariant() -ne $sha) { throw 'Embedded BAT differs from repository BAT' }
$manifest = @{ bat_sha256=$sha; exe_sha256=(Get-FileHash $exe -Algorithm SHA256).Hash.ToLowerInvariant(); machine='AMD64'; subsystem='Windows GUI (2)'; console_shell_used_by_launcher=$false; source_commit=$env:GITHUB_SHA; runner_os=$env:RUNNER_OS; icon_sha256=(Get-FileHash "$PSScriptRoot/idm-semo.ico" -Algorithm SHA256).Hash.ToLowerInvariant() }
$manifest | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $OutputDirectory 'build-manifest.json')
Write-Host "Windows GUI EXE verified: $exe"
