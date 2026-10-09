# ============================================================
# inventory_drives.ps1 - READ-ONLY reconnaissance of all disks.
# Nothing is wiped, moved, or written. ASCII only.
# Run: powershell.exe -NoProfile -ExecutionPolicy Bypass -File Scripts\inventory_drives.ps1
# ============================================================
$ErrorActionPreference = 'SilentlyContinue'
$IC = [System.Globalization.CultureInfo]::InvariantCulture

Write-Output '=== PHYSICAL DISKS (as Windows sees them) ==='
Get-Disk | Sort-Object Number | ForEach-Object {
    Write-Output ('  Disk ' + $_.Number + '  ' + $_.FriendlyName + '  bus=' + $_.BusType +
        '  health=' + $_.HealthStatus + '  size=' + ($_.Size / 1GB).ToString('0.0', $IC) + ' GiB' +
        '  partitioned=' + ($_.NumberOfPartitions -gt 0))
}

Write-Output ''
Write-Output '=== VOLUMES (drive letters today) ==='
Get-Volume | Where-Object { $_.DriveLetter } | Sort-Object DriveLetter | ForEach-Object {
    Write-Output ('  ' + $_.DriveLetter + ':  ' + $_.FileSystemLabel.PadRight(20) +
        ' size=' + ($_.Size / 1GB).ToString('0.0', $IC) + ' GiB  free=' +
        ($_.SizeRemaining / 1GB).ToString('0.0', $IC) + ' GiB  fs=' + $_.FileSystem)
}

Write-Output ''
Write-Output '=== USB DRIVES, TOP-LEVEL CONTENTS (read-only peek) ==='
Get-Disk | Where-Object { $_.BusType -eq 'USB' } | ForEach-Object {
    $disk = $_
    Write-Output ('-- Disk ' + $disk.Number + ' (' + $disk.FriendlyName + ') --')
    Get-Partition -DiskNumber $disk.Number | ForEach-Object {
        $vol = Get-Volume -ObjectId $_.ObjectId
        if ($vol -and $vol.DriveLetter) {
            $root = $vol.DriveLetter + ':\'
            Write-Output ('   ' + $root)
            Get-ChildItem -Path $root -Force | Select-Object -First 12 | ForEach-Object {
                $kind = if ($_.PSIsContainer) { '<dir>' } else { ($_.Length / 1MB).ToString('0.0', $IC) + ' MB' }
                Write-Output ('      ' + $_.Name.PadRight(40) + $kind)
            }
        } else {
            Write-Output ('   (partition without drive letter - RAW or unlabelled)')
        }
    }
}
Write-Output ''
Write-Output 'INVENTORY COMPLETE - nothing was modified.'
