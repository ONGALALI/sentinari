# ============================================================
# 71d watch_download.ps1 - finish-the-task watcher (detached)
#
# Loops until the weights artifact is complete, then:
#   1. verifies exact size + SHA-256 vs the HF LFS pointer
#   2. runs the loader weight-index report on the real artifact
# Self-heals: relaunches the resume-safe fetcher if it dies
# short of target. Everything lands in watch_download.log.
# NEVER deletes or re-downloads on verify failure - that is the
# operator's call.
# ASCII only. No admin.
# ============================================================
$ErrorActionPreference = 'Continue'
$Dir = Join-Path $PSScriptRoot 'custom_engine_weights'
$Big = Join-Path $Dir 'model.safetensors'
$ExpectedBytes = 23919549408          # exact, from HF raw LFS pointer (live-checked 71d)
$ExpectedSha = '5A84CB313260AC447237B890387116DFA8682E49A6B44BC585AE8353ABBFF18D'
$Log = Join-Path $PSScriptRoot 'watch_download.log'

# All logging goes to stdout only - the detached launcher's
# -RedirectStandardOutput is the single writer of watch_download.log
# (Add-Content on a redirect-held file risks a sharing violation).
function Log($msg) {
    Write-Output ('[' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '] ' + $msg)
}

Log 'watcher started'

# ---- phase 1: wait for the artifact (max ~6 h), self-heal the fetcher ----
$deadline = (Get-Date).AddHours(6)
$heals = 0
while ($true) {
    $have = 0
    if (Test-Path $Big) { $have = (Get-Item $Big).Length }
    if ($have -ge $ExpectedBytes) { break }
    if ((Get-Date) -gt $deadline) { Log 'TIMEOUT waiting for download (6 h)'; exit 1 }

    # growth sample: alive if any bytes landed in the last 120 s
    $s1 = $have; Start-Sleep -Seconds 120
    $s2 = 0; if (Test-Path $Big) { $s2 = (Get-Item $Big).Length }
    $pct = [math]::Round(100.0 * $s2 / $ExpectedBytes, 1)
    if ($s2 -gt $s1) {
        Log ('progress ' + [math]::Round($s2 / 1GB, 2) + ' GiB / 22.28 GiB (' + $pct + '%) - flowing')
    } else {
        $heals++
        if ($heals -le 10) {
            Log ('no growth at ' + $pct + '% - relaunching resume-safe fetcher (heal ' + $heals + ')')
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'start_download.ps1') | Out-Null
        } else {
            Log 'no growth after 10 heals - giving up, operator must look'
            exit 2
        }
    }
}
Log ('download complete: ' + [math]::Round((Get-Item $Big).Length / 1GB, 2) + ' GiB on disk')

# ---- phase 2: verify size + SHA-256 ----
Log 'verifying size and SHA-256 (hashing 22.28 GiB, takes minutes)...'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'verify_weights.ps1') `
    -ExpectedBytes $ExpectedBytes -ExpectedSha256 $ExpectedSha 2>&1 | ForEach-Object { Log ('verify| ' + $_) }
if ($LASTEXITCODE -ne 0) {
    Log 'VERIFY FAILED - artifact NOT trusted; loader report skipped (operator decides next move)'
    exit 3
}
Log 'VERIFY OK'

# ---- phase 3: loader weight-index report on the real artifact ----
Log 'running loader weight-index report (mimimul_engine_Init via .venv)...'
$py = 'D:\inpirari\Sentinari\.venv\Scripts\python.exe'
& $py (Join-Path $PSScriptRoot 'run_loader_report.py') 2>&1 | ForEach-Object { Log ('loader| ' + $_) }
if ($LASTEXITCODE -eq 0) { Log 'TASK COMPLETE: weights verified and loader report PASSED' }
else { Log ('loader report FAILED with exit ' + $LASTEXITCODE) }
exit $LASTEXITCODE
