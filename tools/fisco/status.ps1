# Health check: nodes up, block height, anchor contract address. Exit code 0 = healthy.
$here = $PSScriptRoot
$wslPath = (wsl -d oasis-fisco -- wslpath -a ($here.Replace([string][char]92,'/'))).Trim()
wsl -d oasis-fisco -u root -- bash "$wslPath/chain.sh" status
exit $LASTEXITCODE
