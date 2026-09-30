# ============================================================
# 71 fetch_weights.ps1 - one-time minimal weights download
#
# Downloads ONLY the bare minimum for the custom engine:
#   model.safetensors + config.json + tokenizer files
# from google/gemma-4-12B-it (UNGATED, Apache-2.0 - verified 71).
# Lands in engine\custom_engine_weights\ (gitignored).
#
# ASCII only. No admin. Run:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File engine\fetch_weights.ps1
# Re-run safely: finished files are skipped; partial files resume.
# ============================================================
$ErrorActionPreference = 'Stop'
# PowerShell 5.1 defaults to old TLS - force modern TLS up front.
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12 -bor [System.Net.SecurityProtocolType]::Tls13
$Base = 'https://huggingface.co/google/gemma-4-12B-it/resolve/main'
$Dest = Join-Path $PSScriptRoot 'custom_engine_weights'
if (-not (Test-Path $Dest)) { New-Item -ItemType Directory -Path $Dest | Out-Null }

$files = @(
    @{ name = 'config.json' }
    @{ name = 'tokenizer.json' }
    @{ name = 'tokenizer_config.json' }
    @{ name = 'generation_config.json' }
    @{ name = 'chat_template.jinja' }
    @{ name = 'processor_config.json' }
    @{ name = 'model.safetensors'; big = $true }
)  # exact repo siblings - verified live 71 (no tokenizer.model / special_tokens_map.json)

foreach ($f in $files) {
    $out = Join-Path $Dest $f.name
    $url = "$Base/$($f.name)"
    $existing = if (Test-Path $out) { (Get-Item $out).Length } else { 0 }
    if ($f.big) {
        # big file: resume-supporting range fetch in 64 MB chunks with progress
        $total = 0
        try {
            $r = [System.Net.HttpWebRequest]::Create($url)
            $r.Method = 'HEAD'; $r.AllowAutoRedirect = $true; $r.Timeout = 20000
            $resp = $r.GetResponse()
            $total = $resp.ContentLength; $resp.Close()
        } catch { Write-Output ('WARN: HEAD failed for ' + $f.name + ' - falling back to plain download.'); }
        if ($total -gt 0 -and $existing -ge $total) {
            Write-Output ('SKIP ' + $f.name + ' (complete, ' + [math]::Round($existing/1GB,2) + ' GB)')
            continue
        }
        Write-Output ('FETCH ' + $f.name + ' (' + [math]::Round($total/1GB,2) + ' GB total, have ' + [math]::Round($existing/1MB) + ' MB)')
        if ($total -gt 0 -and $existing -gt 0) {
            # resume from existing bytes
            $req = [System.Net.HttpWebRequest]::Create($url)
            $req.AllowAutoRedirect = $true
            $req.AddRange($existing)
            $resp = $req.GetResponse()
            $stream = $resp.GetResponseStream()
            $fs = [System.IO.File]::Open($out, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write)
            $buf = New-Object byte[] 67108864
            $read = 0; $tick = 0
            while (($read = $stream.Read($buf, 0, $buf.Length)) -gt 0) {
                $fs.Write($buf, 0, $read)
                $tick += $read
                if ($tick -gt 268435456) { $tick = 0; Write-Output ('  ... ' + [math]::Round(((Get-Item $out).Length)/1GB,2) + ' GB on disk') }
            }
            $fs.Close(); $stream.Close(); $resp.Close()
        } else {
            # plain download (no resume offset available)
            [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
        }
        Write-Output ('DONE ' + $f.name + ' -> ' + [math]::Round((Get-Item $out).Length/1GB,2) + ' GB')
    } else {
        if ($existing -gt 0) { Write-Output ('SKIP ' + $f.name); continue }
        Write-Output ('FETCH ' + $f.name)
        Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
        Write-Output ('DONE ' + $f.name)
    }
}
Write-Output 'ALL FILES PRESENT. Custom engine weights ready in engine\custom_engine_weights\'
