<#
.SYNOPSIS
    Refreshes deploy/client and deploy/server from the canonical sources in the repo.

.DESCRIPTION
    Copies operator files into deploy/server and target + media bootstrap files
    into deploy/client. Run from anywhere; paths are resolved from this script's
    location.

.EXAMPLE
    PS> .\deploy\pack-deploy.ps1
#>

$ErrorActionPreference = "Stop"

$DeployRoot = $PSScriptRoot
$RepoRoot = Split-Path $DeployRoot -Parent

$ServerDir = Join-Path $DeployRoot "server"
$ClientDir = Join-Path $DeployRoot "client"
$ClientTarget = Join-Path $ClientDir "target"

New-Item -ItemType Directory -Force -Path $ServerDir | Out-Null
New-Item -ItemType Directory -Force -Path $ClientTarget | Out-Null

Copy-Item -Force (Join-Path $RepoRoot "operator\listener.py") (Join-Path $ServerDir "listener.py")
Copy-Item -Force (Join-Path $RepoRoot "operator\operator.ini") (Join-Path $ServerDir "operator.ini")

Copy-Item -Force (Join-Path $RepoRoot "target\connector.py") (Join-Path $ClientTarget "connector.py")
Copy-Item -Force (Join-Path $RepoRoot "target\target.ini") (Join-Path $ClientTarget "target.ini")
Copy-Item -Force (Join-Path $RepoRoot "target\launch.vbs") (Join-Path $ClientTarget "launch.vbs")

foreach ($name in @("cv2_hack.py", "requirements.txt", "install-target.ps1", "script.bat", "silent_run.vbs")) {
    Copy-Item -Force (Join-Path $RepoRoot $name) (Join-Path $ClientDir $name)
}

Write-Output "Pack complete:"
Write-Output "  Server -> $ServerDir"
Write-Output "  Client -> $ClientDir"
