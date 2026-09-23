param(
    [Parameter(Mandatory = $true)]
    [string]$DistroName,
    [switch]$RequireEncryption,
    [switch]$OutputDrive
)

$ErrorActionPreference = 'Stop'

$os = Get-CimInstance -ClassName Win32_OperatingSystem
if ($os.ProductType -ne 1 -or $os.Caption -notmatch 'Windows 11') {
    throw "Windows 11 workstation required; found $($os.Caption)"
}

$distro = Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' |
    ForEach-Object { Get-ItemProperty $_.PSPath } |
    Where-Object { $_.DistributionName -eq $DistroName } |
    Select-Object -First 1
if ($null -eq $distro) {
    throw "Cannot find WSL distribution metadata for $DistroName"
}
if ($distro.Version -ne 2) {
    throw "$DistroName is not a WSL 2 distribution"
}

$basePath = [Environment]::ExpandEnvironmentVariables($distro.BasePath)
$vhdPath = Join-Path $basePath 'ext4.vhdx'
if (-not (Test-Path -LiteralPath $vhdPath -PathType Leaf)) {
    throw "Cannot find the WSL 2 virtual disk for $DistroName"
}
if ($basePath -notmatch '^(?:\\\\\?\\)?([A-Za-z]:)\\') {
    throw "Cannot determine the Windows volume containing $DistroName"
}
$drive = $Matches[1].ToUpperInvariant()

$protected = $null
if ($RequireEncryption) {
    & manage-bde.exe -status $drive -protectionaserrorlevel | Out-Null
    $protected = $LASTEXITCODE -eq 0
    if (-not $protected) {
        throw "Windows volume $drive protection is off, unavailable, or cannot be queried"
    }
}

if ($OutputDrive) {
    Write-Output $drive
    exit 0
}

[ordered]@{
    osCaption = $os.Caption
    osVersion = $os.Version
    distroName = $DistroName
    wslVersion = [int]$distro.Version
    vhdPath = $vhdPath
    backingDrive = $drive
    encryptionRequired = [bool]$RequireEncryption
    encrypted = $protected
} | ConvertTo-Json -Compress
