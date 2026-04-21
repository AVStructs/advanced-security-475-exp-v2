<#
.SYNOPSIS
    Builds two one-file executables for the Windows target: connector + media player.

.DESCRIPTION
    Produces ``ControlChannelTarget.exe`` (control channel) and ``cv2_hack.exe``
    (fullscreen player) in ``deploy/client/target-exe-bundle/``. Copy that entire
    folder to the target PC together with ``target.ini`` (written here with a flat
    ``project_root``) and your video/audio assets.

    Requires Python on the build machine with project ``requirements.txt`` plus
    ``pyinstaller`` (installed automatically if missing).

.PARAMETER Console
    If set, builds the connector with a console window (easier debugging). Default
    is windowed (no console) for Startup-folder use.

.EXAMPLE
    PS> .\deploy\client\build-exe.ps1
#>

[CmdletBinding()]
param([switch] $Console)

$ErrorActionPreference = "Stop"

$ClientRoot = $PSScriptRoot
$DeployRoot = Split-Path $ClientRoot -Parent
$RepoRoot = Split-Path $DeployRoot -Parent

$OutDir = Join-Path $ClientRoot "target-exe-bundle"
$WorkRoot = Join-Path $ClientRoot "build-tmp"
$WorkConn = Join-Path $WorkRoot "connector"
$WorkMedia = Join-Path $WorkRoot "cv2_hack"

$ConnectorSrc = Join-Path $RepoRoot "target\connector.py"
$MediaSrc = Join-Path $RepoRoot "cv2_hack.py"
$IniSrc = Join-Path $RepoRoot "target\target.ini"

foreach ($p in @($ConnectorSrc, $MediaSrc, $IniSrc)) {
    if (-not (Test-Path -LiteralPath $p)) {
        throw "Missing source file: $p"
    }
}

Push-Location $RepoRoot
try {
    python -m pip install --upgrade pip | Out-Null
    python -m pip install -r (Join-Path $RepoRoot "requirements.txt") | Out-Null
    python -m pip install "pyinstaller>=6.0" | Out-Null
} finally {
    Pop-Location
}

if (Test-Path -LiteralPath $OutDir) {
    Remove-Item -Recurse -Force $OutDir
}
if (Test-Path -LiteralPath $WorkRoot) {
    Remove-Item -Recurse -Force $WorkRoot
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
New-Item -ItemType Directory -Force -Path $WorkConn | Out-Null
New-Item -ItemType Directory -Force -Path $WorkMedia | Out-Null

function Invoke-TargetExeBuild {
    param(
        [string[]] $ExtraArgs,
        [string] $Source,
        [string] $Work
    )
    $pyi = @(
        "--noconfirm", "--clean",
        "--distpath", $OutDir,
        "--workpath", $Work,
        "--specpath", $Work
    ) + $ExtraArgs + @($Source)
    & python -m PyInstaller @pyi
}

$connMode = if ($Console) { "--console" } else { "--windowed" }

Push-Location $RepoRoot
try {
    Write-Output "Building ControlChannelTarget.exe ..."
    Invoke-TargetExeBuild -Work $WorkConn -Source $ConnectorSrc -ExtraArgs @(
        "--onefile", $connMode, "--name", "ControlChannelTarget"
    )
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed on connector." }

    Write-Output "Building cv2_hack.exe (large; OpenCV + pygame) ..."
    Invoke-TargetExeBuild -Work $WorkMedia -Source $MediaSrc -ExtraArgs @(
        "--onefile", "--windowed", "--name", "cv2_hack",
        "--hidden-import=pygame",
        "--hidden-import=pycaw.pycaw",
        "--hidden-import=comtypes",
        "--hidden-import=keyboard"
    )
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed on cv2_hack." }
} finally {
    Pop-Location
}

# Flat bundle: target.ini beside exes -> use project_root = . so media_root matches folder.
$iniFlat = Join-Path $OutDir "target.ini"
(Get-Content -LiteralPath $IniSrc -Encoding UTF8) | ForEach-Object {
    if ($_ -match '^\s*project_root\s*=') {
        "project_root = ."
    } else {
        $_
    }
} | Set-Content -LiteralPath $iniFlat -Encoding UTF8

Write-Output ""
Write-Output "Done. Output folder:"
Write-Output "  $OutDir"
Write-Output "Contents: ControlChannelTarget.exe, cv2_hack.exe, target.ini"
Write-Output "Add giraffe_clipped.mp4 / .mp3 (or edit target.ini) next to those files, then copy the whole folder to the target PC."
