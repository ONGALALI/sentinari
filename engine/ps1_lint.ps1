# ============================================================
# 71d ps1_lint.ps1 - PowerShell syntax check for engine scripts
# Validates a .ps1 via the PowerShell parser WITHOUT running it
# (same trick proven in 73b for backup_sentinari.ps1).
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File engine\ps1_lint.ps1
# ASCII only. No admin.
# ============================================================
$ErrorActionPreference = 'Stop'
$files = @('watch_download.ps1', 'start_watch.ps1', 'verify_weights.ps1', 'ps1_lint.ps1')
$bad = 0
foreach ($f in $files) {
    $path = Join-Path $PSScriptRoot $f
    $tokens = $null; $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors -and $errors.Count -gt 0) {
        $bad++
        Write-Output ('SYNTAX FAIL ' + $f)
        $errors | ForEach-Object { Write-Output ('  line ' + $_.Extent.StartLineNumber + ': ' + $_.Message) }
    } else {
        Write-Output ('SYNTAX OK   ' + $f)
    }
}
if ($bad -gt 0) { exit 1 }
Write-Output 'ALL CLEAN'
