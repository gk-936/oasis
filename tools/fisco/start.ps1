# Start the oasis-fisco WSL distro (D:\WSL\oasis-fisco), the 4-node FISCO BCOS chain, and deploy the anchor contract if needed.
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$wslPath = (wsl -d oasis-fisco -- wslpath -a ($here.Replace([string][char]92,'/'))).Trim()
# A running wsl process keeps the distro (and the nodes) alive; WSL stops idle distros otherwise.
$pidFile = Join-Path $here '.keepalive.pid'
$alive = $false
if (Test-Path $pidFile) { $alive = [bool](Get-Process -Id ([int](Get-Content $pidFile)) -ErrorAction SilentlyContinue) }
if (-not $alive) {
    $p = Start-Process wsl -ArgumentList '-d','oasis-fisco','-u','root','--','sleep','infinity' -WindowStyle Hidden -PassThru
    $p.Id | Set-Content $pidFile
}
wsl -d oasis-fisco -u root -- bash "$wslPath/chain.sh" start
$has = (wsl -d oasis-fisco -u root -- bash -c 'cat /opt/fisco/anchor_contract.txt 2>/dev/null').Trim()
if (-not $has) { wsl -d oasis-fisco -u root -- bash "$wslPath/chain.sh" deploy }
& "$here\status.ps1"
