$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = $env:PYTHON_BIN
if (-not $Python) { $Python = "python" }

& $Python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -r requirements-agent.txt

Write-Host "[ok] installed. Run .\run_agent.ps1"
