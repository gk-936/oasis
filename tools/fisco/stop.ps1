# Stop the chain and release the keepalive so WSL can shut the distro down. Chain data is kept.
$here = $PSScriptRoot
$wslPath = (wsl -d oasis-fisco -- wslpath -a ($here.Replace([string][char]92,'/'))).Trim()
wsl -d oasis-fisco -u root -- bash "$wslPath/chain.sh" stop
$pidFile = Join-Path $here '.keepalive.pid'
if (Test-Path $pidFile) { Stop-Process -Id ([int](Get-Content $pidFile)) -ErrorAction SilentlyContinue; Remove-Item $pidFile }
wsl --terminate oasis-fisco
