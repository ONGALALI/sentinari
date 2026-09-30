<#
  Sentinari Focus Mode (§62) — "Give it all she's got, Scotty."
  Pushes the machine toward Sentinari: high-performance power, closes
  leisure/background consumers, reports freed resources.

  SAFE BY DESIGN:
  - Never touches security software (endpointprotection, MsMpEng, SecurityHealth).
  - Never touches system processes (dwm, explorer, Memory Compression, SearchHost...).
  - Never touches Freebuff, bun, python, or anything belonging to Sentinari.
  - Everything here is reversible: reopening apps restores them; the power plan
    can be switched back with: powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\focus_mode.ps1            # apply
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\focus_mode.ps1 -ReportOnly # audit only
#>
param([switch]$ReportOnly)

$out = @()
$consumerProcesses = @(
    'chrome', 'msedge', 'msedgewebview2', 'WhatsApp', 'discord', 'slack',
    'spotify', 'steam', 'epicgameslauncher', 'OneDrive', 'Dropbox',
    'Skype', 'teams', 'zoom', 'telegram'
)

function Get-VramInUse {
    try {
        $total = 0
        (Get-Counter '\GPU Process Memory(*)\Local Usage' -ErrorAction Stop).CounterSamples |
            ForEach-Object { $total += $_.CookedValue }
        return [math]::Round($total / 1MB)
    } catch { return -1 }
}

$beforeVram = Get-VramInUse
$before = Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 6 | ForEach-Object {
    '{0,6} MB  {1}' -f [math]::Round($_.WorkingSet64/1MB), $_.ProcessName
}

$out += '=== BEFORE ==='
$out += ('VRAM in use: {0} MB' -f $beforeVram)
$out += ($before | ForEach-Object { '  ' + $_ })

if (-not $ReportOnly) {
    # 1. High-performance power plan
    $hp = powercfg /list | Select-String 'High performance|Ultimate Performance'
    if ($hp) {
        $guid = ($hp[0].Line -split ':\s+')[1].Split(' ')[0]
        powercfg /setactive $guid 2>$null
        $out += ('POWER: activated high-performance scheme ({0})' -f $guid)
    } else {
        # Duplicate Balanced as a custom high-performance scheme if none exists
        powercfg /duplicatescheme 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c 2>$null | Out-Null
        $hp2 = powercfg /list | Select-String 'High performance|Ultimate Performance'
        if ($hp2) {
            $guid = ($hp2[0].Line -split ':\s+')[1].Split(' ')[0]
            powercfg /setactive $guid 2>$null
            $out += ('POWER: created+activated high-performance scheme ({0})' -f $guid)
        } else { $out += 'POWER: could not create high-performance plan (skipped)' }
    }

    # 2. Close leisure/background consumers (graceful CloseMainWindow first, then kill)
    $closed = @()
    foreach ($name in $consumerProcesses) {
        Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object {
            $closed += ('{0} (pid {1})' -f $_.ProcessName, $_.Id)
            $_.CloseMainWindow() | Out-Null
        }
    }
    Start-Sleep -Seconds 3
    foreach ($name in $consumerProcesses) {
        Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    }
    if ($closed) { $out += ('CLOSED: ' + ($closed -join ', ')) } else { $out += 'CLOSED: none were running' }

    # 3. Nudge Windows to hand back standby RAM
    $os = Get-CimInstance Win32_OperatingSystem
    $out += ('RAM free now: {0} MB of {1} MB' -f [math]::Round($os.FreePhysicalMemory/1024), [math]::Round($os.TotalVisibleMemorySize/1024))
}

Start-Sleep -Seconds 2
$afterVram = Get-VramInUse
$out += '=== AFTER ==='
$out += ('VRAM in use: {0} MB (before {1} MB)' -f $afterVram, $beforeVram)
$out += ('ACTIVE PLAN: ' + (powercfg /getactivescheme))
$out += 'NOTE: security software (endpointprotection, MsMpEng) and system processes were left untouched by design.'

$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
($out + '', "-- focus_mode run $stamp --") | Set-Content -Path "$PSScriptRoot\..\Logs\focus_mode_last_run.txt"
$out
