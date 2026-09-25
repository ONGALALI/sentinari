# One-shot ACL hardening for D:\inpirari (owner directive, 2026-09-25).
# Grants 1I6\m3isd Full Control recursively, then removes Authenticated
# Users and BUILTIN\Users from the tree. SYSTEM/Administrators untouched.
# Progress + completion marker written to harden-acl.log beside this script.
$ErrorActionPreference = "Continue"
$log = Join-Path $PSScriptRoot "harden-acl.log"
"[$(Get-Date -Format 'HH:mm:ss')] START grant pass (m3isd full control, recursive)" | Out-File $log -Encoding utf8

icacls "D:\inpirari" /grant:r "1I6\m3isd:(OI)(CI)F" /t /c /q 2>&1 | Select-Object -Last 1 | Out-File $log -Append -Encoding utf8
"[$(Get-Date -Format 'HH:mm:ss')] grant pass done" | Out-File $log -Append -Encoding utf8

"[$(Get-Date -Format 'HH:mm:ss')] START removal pass (Authenticated Users, Users)" | Out-File $log -Append -Encoding utf8
icacls "D:\inpirari" /remove:g "*S-1-5-11" "*S-1-5-32-545" /t /c /q 2>&1 | Select-Object -Last 1 | Out-File $log -Append -Encoding utf8
"[$(Get-Date -Format 'HH:mm:ss')] removal pass done" | Out-File $log -Append -Encoding utf8

"DONE" | Out-File (Join-Path $PSScriptRoot "harden-acl.done") -Encoding utf8
"[$(Get-Date -Format 'HH:mm:ss')] ALL DONE" | Out-File $log -Append -Encoding utf8
