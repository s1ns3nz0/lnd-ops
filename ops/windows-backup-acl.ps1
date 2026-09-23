param([Parameter(Mandatory=$true)][string]$Path, [switch]$Verify)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Path)) { throw "Backup path does not exist: $Path" }
$isDirectory = (Get-Item -LiteralPath $Path).PSIsContainer
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = Get-Acl -Path $Path
$principals = @($identity, [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18'))
$principalSids = @($principals | ForEach-Object { $_.Value })
$inheritance = if ($isDirectory) {
  [System.Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
} else {
  [System.Security.AccessControl.InheritanceFlags]::None
}
if ($Verify) {
  if (-not $acl.AreAccessRulesProtected) { throw "Inherited backup ACL: $Path" }
  $rules = @($acl.Access)
  if ($rules.Count -ne $principals.Count) { throw "Unexpected backup ACL rule count: $Path" }
  foreach ($rule in $rules) {
    $ruleSid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
    if ($principalSids -notcontains $ruleSid -or
        $rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
        $rule.FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::FullControl -or
        $rule.InheritanceFlags -ne $inheritance -or
        $rule.PropagationFlags -ne [System.Security.AccessControl.PropagationFlags]::None -or
        $rule.IsInherited) {
      throw "Unexpected backup ACL rule: $Path"
    }
  }
  return
}
$acl.SetAccessRuleProtection($true, $false)
$acl.Access | ForEach-Object { $acl.RemoveAccessRuleAll($_) | Out-Null }
$propagation = [System.Security.AccessControl.PropagationFlags]::None
$allow = [System.Security.AccessControl.AccessControlType]::Allow
foreach ($principal in $principals) {
  $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
    $principal, [System.Security.AccessControl.FileSystemRights]::FullControl,
    $inheritance, $propagation, $allow
  )
  $acl.AddAccessRule($rule)
}
Set-Acl -Path $Path -AclObject $acl
