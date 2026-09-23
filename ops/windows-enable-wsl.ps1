param([string]$DistroName = 'Ubuntu')

$ErrorActionPreference = 'Stop'
$principal = [Security.Principal.WindowsPrincipal]::new(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script from an elevated PowerShell window'
}
$os = Get-CimInstance -ClassName Win32_OperatingSystem
if ($os.ProductType -ne 1 -or $os.Caption -notmatch 'Windows 11') {
    throw "Windows 11 workstation required; found $($os.Caption)"
}

& wsl.exe --set-default-version 2
if ($LASTEXITCODE -ne 0) { throw 'Failed to set WSL 2 as the default' }
$installed = @(& wsl.exe --list --quiet | ForEach-Object { ($_ -replace "`0", '').Trim() })
if ($installed -notcontains $DistroName) {
    & wsl.exe --install --distribution $DistroName
    if ($LASTEXITCODE -ne 0) { throw "Failed to install WSL distribution $DistroName" }
    Write-Output 'WSL installation requested. Restart Windows if prompted, complete the Ubuntu first-run user setup, then rerun this script.'
    exit 10
}

& wsl.exe --set-version $DistroName 2
if ($LASTEXITCODE -ne 0) { throw "Failed to configure $DistroName as WSL 2" }
$firewallRule = 'lnd-ops-block-k3s-api'
Get-NetFirewallRule -Name $firewallRule -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule
New-NetFirewallRule -Name $firewallRule `
    -DisplayName 'lnd-ops: block inbound Kubernetes API' `
    -Direction Inbound -Action Block -Enabled True -Profile Any `
    -Protocol TCP -LocalPort 6443 | Out-Null
$config = "[boot]`nsystemd=true`n"
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($config))
& wsl.exe --distribution $DistroName --user root -- sh -c "echo '$encoded' | base64 -d > /etc/wsl.conf && chmod 644 /etc/wsl.conf"
if ($LASTEXITCODE -ne 0) { throw 'Failed to enable systemd in /etc/wsl.conf' }
& wsl.exe --shutdown
if ($LASTEXITCODE -ne 0) { throw 'Failed to stop WSL after changing its configuration' }
Write-Output "OK: $DistroName is WSL 2 with systemd and Windows inbound TCP 6443 is blocked. Open Ubuntu again before continuing."
