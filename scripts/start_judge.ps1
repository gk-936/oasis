<#
Start Oasis for a judge: offline, mock rates, a fresh sandbox database, the already-built UI. No API key, no Node, no network.
Usage: scripts\start_judge.ps1 [-Port 8000] [-BindHost 127.0.0.1] [-RandomPasscodes] [-DataDir DIR]
Contains no secrets. With the default (public) demo passcodes the sandbox is open to anyone who can reach the port,
so keep the host at 127.0.0.1 unless you mean to share it.
#>
param([int]$Port = 8000, [string]$BindHost = "127.0.0.1", [switch]$RandomPasscodes, [string]$DataDir = "")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $DataDir) { $DataDir = Join-Path $Root "data\judge_sandbox" }
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = (Get-Command python -ErrorAction Stop).Source }
if (-not (Test-Path (Join-Path $Root "frontend\dist\index.html"))) {
    throw "frontend/dist is missing (it is committed to the repo); rebuild with: cd frontend; npm ci; npm run build"
}
if (Test-Path $DataDir) { Remove-Item -Recurse -Force $DataDir }      # a fresh sandbox every start
New-Item -ItemType Directory -Force (Join-Path $DataDir "keys") | Out-Null
$env:OASIS_LLM = "offline"; $env:OASIS_EXTRACT = "deterministic"; $env:OASIS_RATES = "mock"; $env:OASIS_ANCHOR = "local"
$env:OASIS_DB = Join-Path $DataDir "oasis.db"
$env:OASIS_DATA_KEY = Join-Path $DataDir "keys\data_key.json"
$env:OASIS_TRUST_KEY = Join-Path $DataDir "keys\trust_key.json"
$env:OASIS_SESSION_SECRET_FILE = Join-Path $DataDir "keys\session_secret.json"
$env:OASIS_ATTEMPTS_FILE = Join-Path $DataDir "redteam_attempts.jsonl"
$env:OASIS_JUDGE_MODE = "1"; $env:OASIS_FRESH_ON_LOGIN = "1"; $env:PYTHONPATH = $Root
if ($RandomPasscodes) {
    $env:OASIS_PASS_STUDENT = & $Py -c "import secrets;print(secrets.token_urlsafe(9))"
    $env:OASIS_PASS_PARENT = & $Py -c "import secrets;print(secrets.token_urlsafe(9))"
    $env:OASIS_PASS_JUDGE = & $Py -c "import secrets;print(secrets.token_urlsafe(9))"
    Remove-Item Env:OASIS_ALLOW_DEMO_PASSCODES -ErrorAction SilentlyContinue
} else {
    $env:OASIS_PASS_STUDENT = "student-demo"; $env:OASIS_PASS_PARENT = "parent-demo"; $env:OASIS_PASS_JUDGE = "judge-demo"
    $env:OASIS_ALLOW_DEMO_PASSCODES = "1"
}
Write-Host "Oasis judge sandbox (offline, MOCK rates, fresh database in $DataDir)"
Write-Host "  URL:         http://${BindHost}:$Port"
Write-Host "  Judge login: role judge, passcode $($env:OASIS_PASS_JUDGE)"
Write-Host "  Also:        student $($env:OASIS_PASS_STUDENT), parent $($env:OASIS_PASS_PARENT)"
Write-Host "  Judge mode:  API docs off, tighter rate limits, at most 20 isolated red-team sandboxes. Ctrl+C stops."
$ErrorActionPreference = "Continue"
Set-Location $Root
& $Py -m uvicorn oasis.api.main:app --host $BindHost --port $Port
