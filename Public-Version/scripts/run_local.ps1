$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $PSScriptRoot
Set-Location $RootDir

if (-not (Test-Path (Join-Path $RootDir ".env"))) {
    Write-Error "Missing .env in $RootDir. Copy .env.example to .env and set ADMIN_TOKEN and WORKER_SECRET first."
    exit 1
}

$env:PYTHONIOENCODING = "utf-8"
python (Join-Path $RootDir "backend/run_cluster.py")
