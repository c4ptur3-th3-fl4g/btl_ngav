param(
  [switch]$Task,
  [string]$InstallDir = "$env:ProgramData\NGAV-Agent",
  [string]$TaskName = "NGAV Agent",
  [string]$WatchPaths = "",
  [string]$ServerIp = "",
  [string]$ServerUrl = "",
  [string]$ApiKey = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = $env:PYTHON_BIN
if (-not $Python) { $Python = "python" }

function Test-Admin {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($identity)
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Install-IntoDirectory {
  param([string]$Target)
  New-Item -ItemType Directory -Force -Path $Target | Out-Null
  robocopy $Root $Target /MIR /XD ".venv" "__pycache__" /XF "api_key.txt" | Out-Null
  if ($LASTEXITCODE -gt 7) {
    throw "robocopy failed with exit code $LASTEXITCODE"
  }
}

if ($Task) {
  if (-not (Test-Admin)) {
    throw "Installing a startup task requires Administrator PowerShell."
  }
  Install-IntoDirectory -Target $InstallDir
  Set-Location $InstallDir
}

& $Python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -r requirements-agent.txt

if (-not $ServerUrl) {
  if (-not $ServerIp) {
    $ServerIp = Read-Host "NGAV server IP"
  }
  if ($ServerIp) {
    $ServerUrl = "http://$ServerIp`:8000"
  }
}
if (-not $ApiKey) {
  $ApiKey = Read-Host "NGAV API key from Server UI Connect button"
}

if ($ServerUrl -or $ApiKey) {
  $env:SERVER_URL = $ServerUrl
  $env:API_KEY = $ApiKey
  $ConfigureScript = Join-Path $Root "_configure_agent.py"
  @'
import os
from pathlib import Path
import yaml

config_path = Path("config/config.yaml")
raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
if os.environ.get("SERVER_URL"):
    raw.setdefault("collector", {})["url"] = os.environ["SERVER_URL"].rstrip("/")
raw.setdefault("collector", {})["api_key_path"] = "../agent/api_key.txt"
config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

api_key = os.environ.get("API_KEY", "").strip()
if api_key:
    key_path = Path("agent/api_key.txt")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(api_key + "\n", encoding="utf-8")
'@ | Set-Content -Encoding UTF8 $ConfigureScript
  & .\.venv\Scripts\python.exe $ConfigureScript
  Remove-Item -Force $ConfigureScript
}

if ($Task) {
  $runScript = Join-Path $InstallDir "run_agent.ps1"
  $arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runScript`""
  if ($WatchPaths) {
    $arguments = "$arguments --watch-paths `"$WatchPaths`""
  }
  $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
  $trigger = New-ScheduledTaskTrigger -AtStartup
  $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 0)
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
  Start-ScheduledTask -TaskName $TaskName
  Write-Host "[ok] installed startup Scheduled Task: $TaskName"
  Write-Host "[ok] install directory: $InstallDir"
} else {
  Write-Host "[ok] installed. Run .\run_agent.ps1"
  Write-Host "[next] for background startup mode, run PowerShell as Administrator:"
  Write-Host "       .\install_windows.ps1 -Task"
}
