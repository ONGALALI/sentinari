# ============================================================
# backup_sentinari.ps1 - (c)73 the nightly backup ritual
#
# Archives the IRREPLACEABLE state - data\ (SQLite library,
# assessments, ml artifacts, exports) + config\ - to a
# date-stamped folder on a DIFFERENT physical disk from D:.
#
#   Target today:  C:\SentinariBackups  (internal NVMe - different
#                  hardware from the USB D: drive)
#   Target later:  the Seagate 20TB Vault+Backup drive (one -Target
#                  argument or the default below flips to V:)
#
# Copies with robocopy (no zip size limits), verifies by comparing
# file counts and total bytes, prunes to the newest -Keep backups.
#
# Run:  powershell.exe -NoProfile -ExecutionPolicy Bypass -File Scripts\backup_sentinari.ps1
# Nightly (owner may schedule):
#   schtasks /Create /TN "Sentinari Backup" /SC DAILY /ST 03:00 /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\inpirari\Sentinari\Scripts\backup_sentinari.ps1"
# ASCII only. Never touches the live files (read-only source).
# ============================================================
param(
    [string]$Target = 'C:\SentinariBackups',
    [int]$Keep = 3,
    # 73b: the AIRLOCK. When the Seagate vault disk is attached, pass its
    # disk number: the script brings it ONLINE, backs up, verifies, then
    # takes it OFFLINE again - the backup exists ~15 min per night instead
    # of 24/7 (an always-connected backup dies with the machine in a
    # compromise; ransomware hunts backups first). NEVER use the system or
    # D: disk here - the script refuses by design.
    [int]$VaultDiskNumber = -1
)
$ErrorActionPreference = 'Continue'
$IC = [System.Globalization.CultureInfo]::InvariantCulture
$Root = Split-Path -Parent $PSScriptRoot   # ...\Sentinari
$Stamp = Get-Date -Format 'yyyy-MM-dd_HHmm'
$Dest = Join-Path $Target ('backup_' + $Stamp)

Write-Output ('SENTINARI BACKUP ' + $Stamp)
Write-Output ('  source: ' + $Root)
Write-Output ('  target: ' + $Dest)

# ---- AIRLOCK: bring the vault disk online (if one was designated) --------
$airlockActive = $false
if ($VaultDiskNumber -ge 0) {
    $disk = Get-Disk -Number $VaultDiskNumber -ErrorAction SilentlyContinue
    if (-not $disk) { Write-Output ('  AIRLOCK: vault disk ' + $VaultDiskNumber + ' not found - aborting (safer to do nothing).'); exit 1 }
    # HARD GUARDS: never the disk that hosts the live library, never the system disk.
    $rootDrive = (Get-Item $Root).PSDrive.Number
    $sysDrive = (Get-Item $env:SystemRoot).PSDrive.Number
    if ($disk.Number -eq $rootDrive -or $disk.Number -eq $sysDrive) {
        Write-Output ('  AIRLOCK REFUSED: disk ' + $disk.Number + ' is a live/system disk. Airlock may only ever target the dedicated vault disk.')
        exit 1
    }
    if ($disk.IsOffline) {
        Set-Disk -Number $VaultDiskNumber -IsOffline $false
        Start-Sleep -Seconds 3
        Write-Output ('  AIRLOCK: vault disk ' + $VaultDiskNumber + ' brought ONLINE (' + $disk.FriendlyName + ')')
    } else {
        Write-Output ('  AIRLOCK: vault disk ' + $VaultDiskNumber + ' was already online')
    }
    $airlockActive = $true
} else {
    Write-Output ('  AIRLOCK: not designated (target ' + $Target + ' must be a dedicated vault disk for airlock use)')
}

# 1) data\ (the irreplaceable library) - mirrored copy
 robocopy (Join-Path $Root 'data') (Join-Path $Dest 'data') /E /COPY:DAT /R:2 /W:5 /NFL /NDL /NP | Out-Null
$rcData = $LASTEXITCODE

# 2) config\ (the identity and settings)
 robocopy (Join-Path $Root 'config') (Join-Path $Dest 'config') /E /COPY:DAT /R:2 /W:5 /NFL /NDL /NP | Out-Null
$rcCfg = $LASTEXITCODE

if ($rcData -ge 8 -or $rcCfg -ge 8) {
    Write-Output ('  robocopy FAILED (data=' + $rcData + ' config=' + $rcCfg + ') - backup INCOMPLETE')
    exit 1
}

# 3) verify: file counts + bytes must match the sources
$srcFiles = Get-ChildItem (Join-Path $Root 'data'), (Join-Path $Root 'config') -Recurse -File
$dstFiles = Get-ChildItem $Dest -Recurse -File
$srcBytes = ($srcFiles | Measure-Object Length -Sum).Sum
$dstBytes = ($dstFiles | Measure-Object Length -Sum).Sum
Write-Output ('  verify: files src=' + $srcFiles.Count + ' dst=' + $dstFiles.Count +
    '  bytes src=' + ($srcBytes / 1GB).ToString('0.00', $IC) + ' GiB dst=' +
    ($dstBytes / 1GB).ToString('0.00', $IC) + ' GiB')
if ($srcFiles.Count -ne $dstFiles.Count -or $srcBytes -ne $dstBytes) {
    Write-Output '  VERIFY FAILED - counts or bytes differ. Backup INCOMPLETE.'
    exit 1
}
Write-Output '  VERIFY PASSED.'

# 4) retention: keep the newest $Keep backup folders
$all = Get-ChildItem $Target -Directory -Filter 'backup_*' | Sort-Object Name -Descending
$old = $all | Select-Object -Skip $Keep
foreach ($o in $old) {
    Write-Output ('  prune: removing ' + $o.Name)
    Remove-Item -LiteralPath $o.FullName -Recurse -Force
}
Write-Output ('  backups kept: ' + (@(Get-ChildItem $Target -Directory -Filter 'backup_*').Count) + ' of max ' + $Keep)

# ---- AIRLOCK: take the vault disk OFFLINE again ---------------------------
if ($airlockActive) {
    Set-Disk -Number $VaultDiskNumber -IsOffline $true
    $chk = Get-Disk -Number $VaultDiskNumber
    Write-Output ('  AIRLOCK: vault disk ' + $VaultDiskNumber + ' OFFLINE again (' +
        $(if ($chk.IsOffline) { 'confirmed invisible to the OS' } else { 'WARNING: still visible!' }) + ')')
}
Write-Output 'BACKUP COMPLETE.'
