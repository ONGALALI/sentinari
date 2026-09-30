# Detached launcher for the weights download (survives this console).
$p = Start-Process -FilePath 'powershell.exe' `
    -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'D:\inpirari\Sentinari\engine\fetch_weights.ps1' `
    -WindowStyle Hidden `
    -RedirectStandardOutput 'D:\inpirari\Sentinari\engine\fetch_weights.log' `
    -RedirectStandardError 'D:\inpirari\Sentinari\engine\fetch_weights.err.log' `
    -PassThru
Write-Output ('download PID ' + $p.Id)
