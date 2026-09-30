# ============================================================
# 71b download_status.ps1 - eyes on the weights download
#
# Shows: files present, big-file progress vs declared total,
# live growth rate (5s sample), ETA, and whether the fetcher
# process is alive.
#
# Double-click download_status.bat (or run this file). ASCII only.
# ============================================================
$ErrorActionPreference = 'SilentlyContinue'
$Dir = Join-Path $PSScriptRoot 'custom_engine_weights'
$Big = Join-Path $Dir 'model.safetensors'
$TotalBytes = 22280000000  # HEAD-declared total from the fetcher log (22.28 decimal GB = 20.75 GiB)
$IC = [System.Globalization.CultureInfo]::InvariantCulture  # dot decimals regardless of locale

Write-Output '=============================================='
Write-Output ' SENTINARI ENGINE WEIGHTS - DOWNLOAD STATUS'
Write-Output ' (google/gemma-4-12B-it -> engine\custom_engine_weights)'
Write-Output '=============================================='

Get-ChildItem $Dir | ForEach-Object {
    $gb = $_.Length / 1GB
    Write-Output ('  ' + $_.Name.PadRight(26) + ($gb.ToString('0.000', $IC) + ' GiB').PadLeft(12))
}

if (Test-Path $Big) {
    $have = (Get-Item $Big).Length
    $pct = 100 * $have / $TotalBytes
    Write-Output ''
    Write-Output ('  PROGRESS: ' + ($have / 1GB).ToString('0.00', $IC) + ' GiB of ' + ($TotalBytes / 1GB).ToString('0.00', $IC) + ' GiB  (' + $pct.ToString('0.0', $IC) + '%)')

    $s1 = (Get-Item $Big).Length
    Start-Sleep -Seconds 5
    $s2 = (Get-Item $Big).Length
    $rate = ($s2 - $s1) / 5
    if ($rate -gt 1024) {
        $mbps = $rate / 1MB
        Write-Output ('  RATE:     ' + $mbps.ToString('0.00', $IC) + ' MB/s  (LIVE - fetcher running)')
        $remain = ($TotalBytes - $s2) / $rate
        if ($remain -gt 0 -and $remain -lt 86400) {
            $h = [math]::Floor($remain / 3600); $m = [math]::Floor(($remain % 3600) / 60)
            Write-Output ('  ETA:      about ' + $h + ' h ' + $m + ' min remaining')
        }
    } else {
        Write-Output '  RATE:     no growth in 5s  (fetcher paused or dead)'
        Write-Output '  FIX:      re-run engine\fetch_weights.ps1 - it RESUMES from current bytes'
    }
} else {
    Write-Output '  model.safetensors not present yet - run engine\fetch_weights.ps1'
}

Write-Output ''
Write-Output '  (re-run this script any time for a fresh sample)'
