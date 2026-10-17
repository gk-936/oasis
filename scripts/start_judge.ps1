<#
Start Oasis for a judge: offline, mock rates, a fresh sandbox database, the already-built UI. No API key, no Node, no network.
Usage: scripts\start_judge.ps1 [-Port 8000] [-BindHost 127.0.0.1] [-RandomPasscodes] [-DataDir DIR] [-Live]
-Live (optional): use the live model, Amazon Nova Pro on Amazon Bedrock, with YOUR OWN AWS credentials already in the environment
(AWS_BEARER_TOKEN_BEDROCK, or AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY, and AWS_REGION). You pay AWS for the tokens; the daily cap
defaults to 200000 tokens (set OASIS_BEDROCK_DAILY_TOKENS to change it). Oasis never stores the credentials. Default is offline.
Contains no secrets and no built-in passcode (fresh random ones are printed at each start). Anyone who has them can log in,
so keep the host at 127.0.0.1 unless you mean to share it.
#>
param([int]$Port = 8000, [string]$BindHost = "127.0.0.1", [switch]$RandomPasscodes, [string]$DataDir = "", [switch]$Live)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if ($Live -and -not $env:AWS_BEARER_TOKEN_BEDROCK -and -not ($env:AWS_ACCESS_KEY_ID -and $env:AWS_SECRET_ACCESS_KEY)) {
    throw "-Live needs your own AWS credentials in the environment: AWS_BEARER_TOKEN_BEDROCK, or AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY (plus AWS_REGION). Oasis does not provide or store them. Without -Live the app runs offline with no key."
}
if (-not $DataDir) { $DataDir = Join-Path $Root "data\judge_sandbox" }
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = (Get-Command python -ErrorAction Stop).Source }
if (-not (Test-Path (Join-Path $Root "frontend\dist\index.html"))) {
    throw "frontend/dist is missing (it is committed to the repo); rebuild with: cd frontend; npm ci; npm run build"
}
if (Test-Path $DataDir) { Remove-Item -Recurse -Force $DataDir }      # a fresh sandbox every start
New-Item -ItemType Directory -Force (Join-Path $DataDir "keys") | Out-Null
$env:OASIS_RATES = "mock"; $env:OASIS_ANCHOR = "local"
if ($Live) {
    $env:OASIS_LLM = "bedrock"; $env:OASIS_EXTRACT = "llm"
    if (-not $env:OASIS_BEDROCK_DAILY_TOKENS) { $env:OASIS_BEDROCK_DAILY_TOKENS = "200000" }
} else { $env:OASIS_LLM = "offline"; $env:OASIS_EXTRACT = "deterministic" }
$env:OASIS_DB = Join-Path $DataDir "oasis.db"
$env:OASIS_DATA_KEY = Join-Path $DataDir "keys\data_key.json"
$env:OASIS_TRUST_KEY = Join-Path $DataDir "keys\trust_key.json"
$env:OASIS_SESSION_SECRET_FILE = Join-Path $DataDir "keys\session_secret.json"
$env:OASIS_ATTEMPTS_FILE = Join-Path $DataDir "redteam_attempts.jsonl"
$env:OASIS_JUDGE_MODE = "1"; $env:OASIS_FRESH_ON_LOGIN = "1"; $env:PYTHONPATH = $Root
# There are no built-in passcodes. Use the ones already set in the environment, otherwise make fresh random ones for this run.
function New-Passcode { & $Py -c "import secrets,string;a=string.ascii_letters+string.digits;print(''.join(secrets.choice(a) for _ in range(16)))" }
if (-not $env:OASIS_KEY_PASSPHRASE) { $env:OASIS_KEY_PASSPHRASE = New-Passcode }   # key files in the throwaway sandbox are written wrapped, never plaintext
$env:OASIS_REQUIRE_KEY_PASSPHRASE = "1"
if (-not $env:OASIS_PASS_STUDENT) { $env:OASIS_PASS_STUDENT = New-Passcode }
if (-not $env:OASIS_PASS_PARENT)  { $env:OASIS_PASS_PARENT  = New-Passcode }
if (-not $env:OASIS_PASS_JUDGE)   { $env:OASIS_PASS_JUDGE   = New-Passcode }
if ($Live) { Write-Host "Oasis judge sandbox (LIVE model: Amazon Nova Pro on YOUR AWS account, cap $($env:OASIS_BEDROCK_DAILY_TOKENS) tokens a day; typed text and images go to Bedrock; MOCK rates, fresh database in $DataDir)" }
else { Write-Host "Oasis judge sandbox (offline, MOCK rates, fresh database in $DataDir)" }
Write-Host "  URL:         http://${BindHost}:$Port"
Write-Host "  Judge login: role judge, passcode $($env:OASIS_PASS_JUDGE)"
Write-Host "  Also:        student $($env:OASIS_PASS_STUDENT), parent $($env:OASIS_PASS_PARENT)"
Write-Host "  Judge mode:  API docs off, tighter rate limits, one private sandbox per login. Ctrl+C stops."
$ErrorActionPreference = "Continue"
Set-Location $Root
& $Py -m uvicorn oasis.api.main:app --host $BindHost --port $Port
