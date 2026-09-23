param(
    [Parameter(Mandatory = $true)]
    [string]$PublicKey,
    [Parameter(Mandatory = $true)]
    [Alias('MacAddress')]
    [string]$AllowedClientIPv4,
    [string]$LinuxUser = 'miata',
    [string]$DistroName = 'Ubuntu',
    [ValidateRange(1024, 65535)]
    [int]$ListenPort = 2222
)

$ErrorActionPreference = 'Stop'
$principal = [Security.Principal.WindowsPrincipal]::new(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script from an elevated PowerShell window'
}
if ($LinuxUser -notmatch '^[a-z_][a-z0-9_-]*$') {
    throw 'LinuxUser contains unsupported characters'
}
if ($DistroName -notmatch '^[A-Za-z0-9._-]+$') {
    throw 'DistroName contains unsupported characters'
}
$parsedAddress = $null
if (-not [Net.IPAddress]::TryParse($AllowedClientIPv4, [ref]$parsedAddress) -or
    $parsedAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'AllowedClientIPv4 must be an IPv4 address'
}
$PublicKey = $PublicKey.Trim()
if ($PublicKey -notmatch '^ssh-ed25519 [A-Za-z0-9+/]+={0,3}(?: .*)?$') {
    throw 'PublicKey must be one OpenSSH Ed25519 public key'
}

$keyEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($PublicKey))
$linuxSetup = @'
set -euo pipefail
linux_user=$1
key_encoded=$2
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y openssh-server
home_dir=$(getent passwd "$linux_user" | cut -d: -f6)
[[ -n "$home_dir" && -d "$home_dir" ]] || { echo "Linux user not found: $linux_user" >&2; exit 1; }
group_name=$(id -gn "$linux_user")
[[ ! -L "$home_dir/.ssh" ]] || { echo 'Refusing a symlinked .ssh directory' >&2; exit 1; }
install -d -m 700 -o "$linux_user" -g "$group_name" "$home_dir/.ssh"
[[ ! -L "$home_dir/.ssh/authorized_keys" ]] || { echo 'Refusing a symlinked authorized_keys file' >&2; exit 1; }
key=$(printf '%s' "$key_encoded" | base64 -d)
key_check=$(mktemp)
trap 'rm -f "$key_check"' EXIT
printf '%s\n' "$key" > "$key_check"
ssh-keygen -l -f "$key_check" >/dev/null
touch "$home_dir/.ssh/authorized_keys"
grep -Fqx "$key" "$home_dir/.ssh/authorized_keys" || printf '%s\n' "$key" >> "$home_dir/.ssh/authorized_keys"
chown "$linux_user:$group_name" "$home_dir/.ssh/authorized_keys"
chmod 600 "$home_dir/.ssh/authorized_keys"
cat > /etc/ssh/sshd_config.d/00-lnd-ops.conf <<'EOF'
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sshd -t
systemctl enable --now ssh
systemctl restart ssh
systemctl is-active --quiet ssh
ss -H -ltn 'sport = :22' | grep -q .
effective=$(sshd -T -C "user=$linux_user,host=localhost,addr=127.0.0.1")
printf '%s\n' "$effective" | grep -qx 'pubkeyauthentication yes'
printf '%s\n' "$effective" | grep -qx 'passwordauthentication no'
printf '%s\n' "$effective" | grep -qx 'kbdinteractiveauthentication no'
'@
$setupEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($linuxSetup))
$command = "echo '$setupEncoded' | base64 -d | bash -s -- '$LinuxUser' '$keyEncoded'"
& wsl.exe --distribution $DistroName --user root -- bash -c $command
if ($LASTEXITCODE -ne 0) { throw 'WSL OpenSSH setup failed' }

$wslAddress = (& wsl.exe --distribution $DistroName -- sh -c `
    "ip -4 route get 1.1.1.1 | sed -n 's/.* src \([^ ]*\).*/\1/p'").Trim()
if (-not [Net.IPAddress]::TryParse($wslAddress, [ref]$parsedAddress) -or
    $parsedAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'Cannot determine the default-route WSL IPv4 address'
}

$privateProfile = Get-NetFirewallProfile -Name Private
if ($privateProfile.Enabled -ne 'True' -or $privateProfile.DefaultInboundAction -eq 'Allow') {
    throw 'The Windows Private firewall profile must be enabled with inbound traffic blocked by default'
}

Set-Service -Name iphlpsvc -StartupType Automatic
Start-Service -Name iphlpsvc
& netsh.exe interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$ListenPort | Out-Null
& netsh.exe interface portproxy add v4tov4 `
    listenaddress=0.0.0.0 listenport=$ListenPort `
    connectaddress=$wslAddress connectport=22
if ($LASTEXITCODE -ne 0) { throw 'Failed to create the Windows-to-WSL SSH port proxy' }

$firewallRule = 'lnd-ops-wsl-ssh'
Get-NetFirewallRule -Name $firewallRule -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule
New-NetFirewallRule -Name $firewallRule `
    -DisplayName 'lnd-ops: WSL SSH from operator Mac' `
    -Direction Inbound -Action Allow -Enabled True -Profile Private `
    -Protocol TCP -LocalPort $ListenPort -RemoteAddress $AllowedClientIPv4 | Out-Null

if (-not (Test-NetConnection -ComputerName 127.0.0.1 -Port $ListenPort -InformationLevel Quiet)) {
    throw 'Windows cannot reach the new WSL SSH port proxy'
}
Write-Output "OK: WSL SSH is available through Windows TCP $ListenPort for client $AllowedClientIPv4"
Write-Output "WSL target: ${wslAddress}:22; user: $LinuxUser; distro: $DistroName"
Write-Output "Rerun this script after WSL gets a different IPv4 address."
