# Builds desktop\dist\ShugoTracker.exe: the Electron app (with the Python core in resources\core) zipped into a
# small launcher that unpacks it once per version. Run from the desktop folder after building the core
# (python -m PyInstaller --noconfirm --clean ShugoCore.spec, from the repository root).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

npx electron-builder --win dir --publish never
if ($LASTEXITCODE -ne 0) { throw "electron-builder failed" }

$work = "dist\launcher"
Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $work | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory((Resolve-Path "dist\win-unpacked").Path, "$PWD\$work\app.zip",
    [IO.Compression.CompressionLevel]::Optimal, $false)

# The unpacked folder is named after the version plus the zip's hash, so every build unpacks fresh exactly once.
$version = (Get-Content package.json -Raw | ConvertFrom-Json).version
$hash = (Get-FileHash "$work\app.zip" -Algorithm SHA256).Hash.Substring(0, 8).ToLower()
Set-Content -NoNewline "$work\build.txt" "$version-$hash"

$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$fw = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319"
& $csc /nologo /target:winexe /optimize+ /out:dist\ShugoTracker.exe /win32icon:build\icon.ico `
    /resource:"$work\app.zip,app.zip" /resource:"$work\build.txt,build.txt" `
    /r:"$fw\System.IO.Compression.dll" /r:"$fw\System.IO.Compression.FileSystem.dll" launcher\Launcher.cs
if ($LASTEXITCODE -ne 0) { throw "csc failed" }
$mb = [math]::Round((Get-Item dist\ShugoTracker.exe).Length / 1MB, 1)
Write-Output "Built dist\ShugoTracker.exe ($mb MB, build $version-$hash)"
