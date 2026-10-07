<#
.SYNOPSIS
Build the portable Windows x64 application at dist/Tourney.exe.
.DESCRIPTION
Requires uv and Windows x64. Installs the locked dependencies and Python 3.12
as needed through uv, then bundles the app into one unsigned executable.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) {
    throw 'Build Tourney on Windows x64.'
}
if (-not (Get-Command uv.exe -ErrorAction SilentlyContinue)) {
    throw 'uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/ and reopen PowerShell.'
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$buildDirectory = Join-Path $projectRoot 'build'
$outputDirectory = Join-Path $projectRoot 'dist'
$specification = Join-Path $projectRoot 'packaging/tourney.spec'

Push-Location -LiteralPath $projectRoot
try {
    Write-Host 'Installing locked application and build dependencies...'
    & uv.exe sync --locked --group build --python 3.12
    if ($LASTEXITCODE -ne 0) {
        throw 'Dependency installation failed. Check network access and uv.lock.'
    }

    & uv.exe run --no-sync python -c "import platform, sys; sys.exit(0 if sys.version_info[:2] == (3, 12) and platform.machine().lower() == 'amd64' else 'The build requires x64 Python 3.12.')"
    if ($LASTEXITCODE -ne 0) {
        throw 'The build requires x64 Python 3.12.'
    }

    Write-Host 'Building the portable executable...'
    & uv.exe run --no-sync python -m PyInstaller --clean --noconfirm --workpath $buildDirectory --distpath $outputDirectory $specification
    if ($LASTEXITCODE -ne 0) {
        throw 'PyInstaller failed. See its output above for details.'
    }

    $executable = Get-Item -LiteralPath (Join-Path $outputDirectory 'Tourney.exe')
    Write-Host ('Built: {0} ({1:N1} MB)' -f $executable.FullName, ($executable.Length / 1MB))
    Write-Host 'Distribute this file alone. It is unsigned; Windows may show a download warning.'
}
finally {
    Pop-Location
}
