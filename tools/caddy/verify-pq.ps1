# Prove X25519MLKEM768 negotiation against the running Caddy, using an OpenSSL 3.5.9 client built inside the
# oasis-fisco WSL distro (/opt/openssl35, on D:). Caddy must be running (start.ps1).
param([string]$Tools = 'D:\china_hackathon\tools\caddy')
$root = Join-Path $Tools 'data\pki\authorities\local\root.crt'
$tmp = 'D:\china_hackathon\tools\tmp'
Copy-Item $root (Join-Path $tmp 'root.crt') -Force
$sh = Join-Path $PSScriptRoot 'pq-client.sh'
$p = (wsl -d oasis-fisco -- wslpath -a ($sh.Replace([string][char]92,'/'))).Trim()
wsl -d oasis-fisco -u root -- bash $p
