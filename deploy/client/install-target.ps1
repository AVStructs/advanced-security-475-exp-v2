<#
.SYNOPSIS
    Installs or removes the per-user Run-key persistence entry that launches
    the target connector at user logon.

.DESCRIPTION
    Writes an HKCU\Software\Microsoft\Windows\CurrentVersion\Run value that
    invokes launch.vbs via wscript.exe. This is the standard-user scope path:
    it does not require admin, survives reboots, and runs at interactive
    logon for the installing user only.

    The script does not modify system-wide keys, services, or scheduled tasks.

.PARAMETER TargetDir
    Folder that contains launch.vbs, connector.py, and target.ini. Defaults
    to the "target" folder next to this script.

.PARAMETER Name
    Registry value name under the Run key. Defaults to "ControlChannelTarget".

.PARAMETER Remove
    If specified, deletes the Run-key value instead of creating it.

.EXAMPLE
    PS> .\install-target.ps1

.EXAMPLE
    PS> .\install-target.ps1 -Remove
#>

[CmdletBinding()]
param(
    [string] $TargetDir = (Join-Path $PSScriptRoot "target"),
    [string] $Name = "ControlChannelTarget",
    [switch] $Remove
)

$ErrorActionPreference = "Stop"

$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

if ($Remove) {
    if (Get-ItemProperty -Path $runKey -Name $Name -ErrorAction SilentlyContinue) {
        Remove-ItemProperty -Path $runKey -Name $Name
        Write-Output "Removed Run-key value '$Name'."
    } else {
        Write-Output "No Run-key value '$Name' present; nothing to do."
    }
    return
}

$launcher = Join-Path $TargetDir "launch.vbs"
if (-not (Test-Path -LiteralPath $launcher)) {
    throw "launch.vbs not found at: $launcher"
}

# Quote the path so spaces in folder names are preserved when the shell runs it.
$command = 'wscript.exe "{0}"' -f $launcher

if (-not (Test-Path $runKey)) {
    New-Item -Path $runKey -Force | Out-Null
}

Set-ItemProperty -Path $runKey -Name $Name -Value $command
Write-Output "Installed Run-key value '$Name' -> $command"
