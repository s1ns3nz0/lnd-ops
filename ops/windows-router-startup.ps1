param(
    [ValidateSet('Preview', 'Install', 'Status')][string]$Mode = 'Preview',
    [string]$DistroName,
    [string]$LinuxUser,
    [string]$Confirm
)

$ErrorActionPreference = 'Stop'

function New-RouterWslSpecification {
    param([string]$Name, [string]$User, [string]$Id, [string]$BasePath)
    if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$' -or
        $User -notmatch '^[a-z_][a-z0-9_-]*[$]?$' -or $User -eq 'root' -or
        $Id -notmatch '^\{[0-9a-fA-F-]{36}\}$' -or $BasePath -match '[\x00-\x1f]') {
        throw 'Invalid existing WSL distribution or non-root Linux user'
    }
    $null = [guid]::Parse($Id)
    $registry = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss\$Id"
    $quotedPath = $BasePath.Replace("'", "''")
    # This action is stored in Task Scheduler, not in a mutable WSL script.
    # A foreground Linux command keeps wsl.exe attached after shell closure.
    $action = @"
`$ErrorActionPreference = 'Stop'
try {
    `$distro = Get-ItemProperty -LiteralPath '$registry'
    if (`$distro.DistributionName -cne '$Name' -or `$distro.Version -ne 2 -or `$distro.BasePath -cne '$quotedPath') {
        throw 'Approved WSL distribution identity changed'
    }
    & (Join-Path `$env:SystemRoot 'System32\wsl.exe') --distribution '$Name' --user '$User' --exec /bin/sleep infinity
    # Even an unexpected clean exit requires bounded Task Scheduler recovery.
    exit 1
} catch {
    Write-Error -ErrorAction Continue 'Router WSL startup failed; inspect the registered distribution and task result.'
    exit 1
}
"@
    [pscustomobject]@{
        TaskName = 'LndOps-Router-' + $Id.Trim('{}')
        Description = 'lnd-ops managed WSL Router login startup v1'
        Script = $action
        Arguments = '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand ' +
            [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($action))
    }
}

function Get-RouterWindowsUser {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    [pscustomobject]@{ Sid = $identity.User.Value
        Administrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
}

function Invoke-RouterWslStartup {
    if ($env:OS -ne 'Windows_NT') { throw 'Run from the existing Windows WSL host' }
    $items = @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' |
        ForEach-Object { Get-ItemProperty $_.PSPath } |
        Where-Object { $_.DistributionName -ceq $DistroName })
    if ($items.Count -ne 1 -or $items[0].Version -ne 2) { throw 'Exactly one existing WSL 2 distribution is required' }
    $spec = New-RouterWslSpecification $DistroName $LinuxUser $items[0].PSChildName $items[0].BasePath
    $user = Get-RouterWindowsUser
    $sid = $user.Sid
    if ($Mode -eq 'Preview') {
        [ordered]@{ task = $spec.TaskName; userSid = $sid; distro = $DistroName; linuxUser = $LinuxUser
            trigger = 'Current user logon'; restartCount = 3; restartMinutes = 1
            unattendedBoot = $false; walletUnlock = 'manual'; action = $spec.Script } | ConvertTo-Json
        return
    }
    $existing = Get-ScheduledTask -TaskPath '\' -ErrorAction Stop |
        Where-Object { $_.TaskName -eq $spec.TaskName }
    if ($Mode -eq 'Status') {
        if ($null -eq $existing) { Write-Output 'Router WSL login task: not installed'; return }
        $info = $existing | Get-ScheduledTaskInfo
        [ordered]@{ task = $spec.TaskName; state = [string]$existing.State
            lastRunTime = [string]$info.LastRunTime; lastResult = $info.LastTaskResult
            routerVerified = $false } | ConvertTo-Json
        return
    }
    if ($Confirm -cne 'INSTALL WSL STARTUP') { throw 'INSTALL WSL STARTUP confirmation is required' }
    if (-not $user.Administrator) {
        throw 'Open WSL as Windows Administrator for registration; no password is saved'
    }
    if ($null -ne $existing -and ($existing.Description -cne $spec.Description -or $existing.Principal.UserId -ne $sid)) {
        throw 'Refusing to replace a task not managed for this Windows user'
    }
    $executable = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $action = New-ScheduledTaskAction -Execute $executable -Argument $spec.Arguments
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $sid
    $owner = New-ScheduledTaskPrincipal -UserId $sid -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    if ($null -ne $existing) { Stop-ScheduledTask -TaskName $spec.TaskName -TaskPath '\' }
    Register-ScheduledTask -TaskName $spec.TaskName -TaskPath '\' -Action $action -Trigger $trigger `
        -Principal $owner -Settings $settings -Description $spec.Description -Force | Out-Null
    Start-ScheduledTask -TaskName $spec.TaskName -TaskPath '\'
    Write-Output 'Registered and requested WSL login startup. This does not verify Router readiness or wallet unlock.'
    Get-ScheduledTask -TaskName $spec.TaskName -TaskPath '\' | Select-Object TaskName, State
}

if ($MyInvocation.InvocationName -ne '.') { Invoke-RouterWslStartup }
