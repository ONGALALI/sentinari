# ============================================================
# 71d verify_weights.ps1 - verify the big artifact before use
#
# Checks: (1) exact size in bytes, (2) SHA-256 vs the HF LFS
# pointer. Exit 0 = trustworthy; nonzero = do NOT load it.
# ASCII only. No admin.
# ============================================================
param(
    [string]$WeightsDir = (Join-Path $PSScriptRoot 'custom_engine_weights'),
    [long]$ExpectedBytes = 23919549408,
    [string]$ExpectedSha256 = ''
)
$ErrorActionPreference = 'Stop'
$Big = Join-Path $WeightsDir 'model.safetensors'
if (-not (Test-Path $Big)) { Write-Output 'VERIFY FAIL: model.safetensors missing'; exit 1 }
$size = (Get-Item $Big).Length
Write-Output ('size on disk : ' + $size + ' bytes')
Write-Output ('expected size: ' + $ExpectedBytes + ' bytes')
if ($size -ne $ExpectedBytes) { Write-Output 'VERIFY FAIL: size mismatch'; exit 2 }
Write-Output 'size check   : PASS'
if ($ExpectedSha256 -ne '') {
    Write-Output 'hashing (22.28 GiB - takes a few minutes)...'
    $h = (Get-FileHash -Path $Big -Algorithm SHA256).Hash
    Write-Output ('sha256 disk   : ' + $h)
    Write-Output ('sha256 expect : ' + $ExpectedSha256.ToUpper())
    if ($h -ne $ExpectedSha256.ToUpper()) { Write-Output 'VERIFY FAIL: hash mismatch'; exit 3 }
    Write-Output 'hash check   : PASS'
} else {
    Write-Output 'hash check   : SKIPPED (no expected hash given)'
}
Write-Output 'VERIFY OK'
exit 0
