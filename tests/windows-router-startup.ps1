# Execute in maintained Linux PowerShell; Task Scheduler and registry are mocked.
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/../ops/windows-router-startup.ps1"
function Assert-True($Value, $Message) { if (-not $Value) { throw $Message } }
function Assert-Throws([scriptblock]$Action) {
    $failed = $false
    try { & $Action | Out-Null } catch { $failed = $true }
    Assert-True $failed 'Expected rejection'
}
$guid = '{01234567-89ab-cdef-0123-456789abcdef}'
$spec = New-RouterWslSpecification 'Ubuntu' 'miata' $guid "C:\Users\O'Brien\WSL"
$encoded = $spec.Arguments.Split(' ')[-1]
Assert-True ([Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($encoded)) -ceq $spec.Script) 'Encoded action drift'
$tokens = $null; $errors = $null
$null = [Management.Automation.Language.Parser]::ParseInput($spec.Script, [ref]$tokens, [ref]$errors)
Assert-True ($errors.Count -eq 0) 'Generated action does not parse'
foreach ($bad in @('root', 'bad;user', 'user name')) {
    Assert-Throws { New-RouterWslSpecification 'Ubuntu' $bad $guid 'C:\WSL' }
}
Assert-Throws { New-RouterWslSpecification 'Ubuntu;bad' 'miata' $guid 'C:\WSL' }
Assert-Throws { New-RouterWslSpecification 'Ubuntu' 'miata' '{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}' 'C:\WSL' }

$env:OS = 'Windows_NT'
$env:SystemRoot = '/tmp/windows-test'
$script:metadata = [pscustomobject]@{ DistributionName = 'Ubuntu'; Version = 2; PSChildName = $guid; BasePath = 'C:\WSL' }
$script:existing = $null
$script:registered = 0
$script:started = 0
$script:admin = $true
function Get-ChildItem { [pscustomobject]@{ PSPath = 'mock-distro' } }
function Get-ItemProperty { $script:metadata }
function Get-RouterWindowsUser { [pscustomobject]@{ Sid = 'S-1-5-21-test'; Administrator = $script:admin } }
function Get-ScheduledTask { param($TaskName, $TaskPath, $ErrorAction); $script:existing }
function Get-ScheduledTaskInfo { [pscustomobject]@{ LastRunTime = 'test-time'; LastTaskResult = 0 } }
function New-ScheduledTaskAction { param($Execute, $Argument); $script:action = $PSBoundParameters; 'action' }
function New-ScheduledTaskTrigger { param([switch]$AtLogOn, $User); $script:trigger = $PSBoundParameters; 'trigger' }
function New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel); $script:owner = $PSBoundParameters; 'owner' }
function New-ScheduledTaskSettingsSet {
    param($RestartCount, $RestartInterval, $ExecutionTimeLimit, $MultipleInstances,
          [switch]$StartWhenAvailable, [switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries)
    $script:settings = $PSBoundParameters; 'settings'
}
function Register-ScheduledTask {
    param($TaskName, $TaskPath, $Action, $Trigger, $Principal, $Settings, $Description, [switch]$Force)
    $script:registered++
}
function Start-ScheduledTask { param($TaskName, $TaskPath); $script:started++ }
function Stop-ScheduledTask { param($TaskName, $TaskPath); throw 'Unexpected existing-task stop' }

$DistroName = 'Ubuntu'; $LinuxUser = 'miata'; $Mode = 'Preview'
$null = Invoke-RouterWslStartup
Assert-True ($script:registered -eq 0 -and $script:started -eq 0) 'Preview changed host state'
$Mode = 'Install'; $Confirm = ''
Assert-Throws { Invoke-RouterWslStartup }
$Confirm = 'INSTALL WSL STARTUP'; $script:admin = $false
Assert-Throws { Invoke-RouterWslStartup }
$script:admin = $true
$script:existing = [pscustomobject]@{ TaskName = $spec.TaskName; Description = 'unmanaged'; Principal = [pscustomobject]@{ UserId = 'S-1-5-21-test' } }
Assert-Throws { Invoke-RouterWslStartup }
$script:existing.Description = $spec.Description
$script:existing.Principal.UserId = 'S-1-5-21-another-user'
Assert-Throws { Invoke-RouterWslStartup }
Assert-True ($script:registered -eq 0 -and $script:started -eq 0) 'Rejected request changed host state'
$script:existing = $null
$null = Invoke-RouterWslStartup
Assert-True ($script:registered -eq 1 -and $script:started -eq 1) 'Approved installation not requested'
Assert-True ($script:settings.RestartCount -eq 3 -and $script:settings.RestartInterval.TotalSeconds -eq 60) 'Unbounded retry settings'
Assert-True ($script:settings.ExecutionTimeLimit.TotalSeconds -eq 0 -and $script:settings.MultipleInstances -eq 'IgnoreNew') 'Keepalive lifetime or instance rule wrong'
Assert-True ($script:owner.LogonType -eq 'Interactive' -and $script:owner.RunLevel -eq 'Highest') 'Unexpected credentials mode'
Assert-True ($script:trigger.AtLogOn -and $script:trigger.User -eq $script:owner.UserId) 'Wrong user trigger'
$script:metadata.Version = 1
Assert-Throws { Invoke-RouterWslStartup }
Assert-True ($script:registered -eq 1) 'WSL1 accepted'

# Run the exact stored action in a child process. Only registry/WSL are fakes;
# native exit and argument handling are exercised by Linux PowerShell.
$temporary = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString())
try {
    $bin = Join-Path $temporary 'System32'
    $null = New-Item -ItemType Directory -Path $bin -Force
    $env:SystemRoot = $temporary
    $env:LND_TEST_CALL_RECORD = Join-Path $temporary 'called.txt'
    $wsl = Join-Path $bin 'wsl.exe'
    [IO.File]::WriteAllText($wsl, "#!/bin/sh`nprintf '%s\n' `"`$@`" > `"`$LND_TEST_CALL_RECORD`"`nexit 0`n")
    & chmod 700 $wsl
    foreach ($name in @('Ubuntu', 'Replaced')) {
        $metadata = @{ DistributionName = $name; Version = 2; BasePath = "C:\Users\O'Brien\WSL" } | ConvertTo-Json -Compress
        $prefix = "function Get-ItemProperty { param(`$LiteralPath); '" + $metadata.Replace("'", "''") + "' | ConvertFrom-Json }`n"
        $runner = Join-Path $temporary 'action.ps1'
        [IO.File]::WriteAllText($runner, $prefix + $spec.Script)
        $null = & pwsh -NoLogo -NoProfile -File $runner 2>&1
        Assert-True ($LASTEXITCODE -eq 1) 'Ended keepalive must report failure for bounded recovery'
        if ($name -eq 'Ubuntu') {
            $arguments = [IO.File]::ReadAllLines($env:LND_TEST_CALL_RECORD)
            Assert-True (($arguments -join '|') -ceq '--distribution|Ubuntu|--user|miata|--exec|/bin/sleep|infinity') 'Wrong WSL command'
            Remove-Item -LiteralPath $env:LND_TEST_CALL_RECORD
        } else {
            Assert-True (-not (Test-Path -LiteralPath $env:LND_TEST_CALL_RECORD)) 'Changed distribution reached WSL'
        }
    }
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Output 'PASS: stored action execution, identity rejection, approval, ownership and bounded task settings'
