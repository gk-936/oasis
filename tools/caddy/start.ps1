# Start Caddy (post-quantum TLS on https://localhost:8443 -> uvicorn 127.0.0.1:8000). Everything stays on D:.
# Prereq: download Caddy for Windows (Apache-2.0) to D:\china_hackathon\tools\caddy\caddy.exe (see docs/pq-tls.md).
param([string]$Tools = 'D:\china_hackathon\tools\caddy')
$ErrorActionPreference = 'Continue'
$env:XDG_DATA_HOME   = Join-Path $Tools 'xdg-data'
$env:XDG_CONFIG_HOME = Join-Path $Tools 'xdg-config'
$env:CADDY_DATA      = Join-Path $Tools 'data'
$env:TEMP = $env:TMP = Join-Path $Tools 'tmp'
New-Item -ItemType Directory -Force $env:XDG_DATA_HOME, $env:XDG_CONFIG_HOME, $env:CADDY_DATA, $env:TEMP | Out-Null
$caddyfile = Join-Path $PSScriptRoot 'Caddyfile'
& "$Tools\caddy.exe" validate --config $caddyfile --adapter caddyfile *> $null
if ($LASTEXITCODE -ne 0) { Write-Error "Caddyfile invalid"; exit 1 }
Write-Host "Caddy up on https://localhost:8443  (internal CA root: $env:CADDY_DATA\pki\authorities\local\root.crt)"
& "$Tools\caddy.exe" run --config $caddyfile --adapter caddyfile
