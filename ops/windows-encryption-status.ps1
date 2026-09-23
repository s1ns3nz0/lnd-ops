param(
    [Parameter(Mandatory = $true)]
    [string]$DistroName,
    [switch]$OutputDrive
)

$ErrorActionPreference = 'Stop'
$stateScript = Join-Path $PSScriptRoot 'windows-host-state.ps1'
$drive = & $stateScript -DistroName $DistroName -RequireEncryption -OutputDrive
if ($OutputDrive) {
    Write-Output $drive
    exit 0
}
Write-Output "OK: Windows volume $drive containing the WSL 2 data is protected"
