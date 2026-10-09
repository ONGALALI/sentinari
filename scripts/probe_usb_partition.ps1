# Probe Disk 1's unmounted partition deeper - READ-ONLY.
$ErrorActionPreference = 'SilentlyContinue'
$IC = [System.Globalization.CultureInfo]::InvariantCulture

Write-Output '=== PARTITIONS ON USB DISK 1 (detail) ==='
Get-Partition -DiskNumber 1 | ForEach-Object {
    Write-Output ('  Partition ' + $_.PartitionNumber +
        '  type=' + $_.Type +
        '  size=' + ($_.Size / 1GB).ToString('0.0', $IC) + ' GiB' +
        '  letter=' + $(if ($_.DriveLetter) { $_.DriveLetter } else { '(none)' }))
}

Write-Output ''
Write-Output '=== VOLUMES WITHOUT LETTERS ==='
Get-Volume | Where-Object { -not $_.DriveLetter } | ForEach-Object {
    Write-Output ('  label="' + $_.FileSystemLabel + '"  fs=' + $_.FileSystem +
        '  size=' + ($_.Size / 1GB).ToString('0.0', $IC) + ' GiB' +
        '  health=' + $_.HealthStatus + '  objectId=' + $_.ObjectId)
}

Write-Output ''
Write-Output '=== BUSES OF ALL DISKS (count the SSDs actually attached) ==='
Get-Disk | ForEach-Object {
    Write-Output ('  Disk ' + $_.Number + '  bus=' + $_.BusType + '  ' + $_.FriendlyName)
}
Write-Output 'PROBE COMPLETE - nothing modified.'
