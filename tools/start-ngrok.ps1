$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$ngrokExe = Join-Path $PSScriptRoot "ngrok\ngrok.exe"
$logFile = Join-Path $PSScriptRoot "ngrok.log"
$errFile = Join-Path $PSScriptRoot "ngrok.err.log"

if (-not (Test-Path $ngrokExe)) {
  throw "ngrok.exe not found at $ngrokExe"
}

$running = Get-Process ngrok -ErrorAction SilentlyContinue
if (-not $running) {
  Remove-Item $logFile, $errFile -ErrorAction SilentlyContinue
  Start-Process -FilePath $ngrokExe `
    -ArgumentList @("http", "8000", "--log=stdout", "--log-format=json") `
    -WindowStyle Hidden `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError $errFile | Out-Null
}

for ($i = 0; $i -lt 15; $i++) {
  try {
    $api = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels"
    $https = $api.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1
    if ($https.public_url) {
      Write-Output $https.public_url
      exit 0
    }
  } catch {}
  Start-Sleep -Seconds 1
}

throw "ngrok tunnel did not expose an HTTPS URL in time"
