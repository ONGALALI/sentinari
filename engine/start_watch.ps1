# Detached launcher for the download watcher (survives this console).
$p = Start-Process -FilePath 'powershell.exe' `
    -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'D:\inpirari\Sentinari\engine\watch_download.ps1' `
    -WindowStyle Hidden `
    -RedirectStandardOutput 'D:\inpirari\Sentinari\engine\watch_download.log' `
    -RedirectStandardError 'D:\inpirari\Sentinari\engine\watch_download.err.log' `
    -PassThru
Write-Output ('watcher PID ' + $p.Id)
