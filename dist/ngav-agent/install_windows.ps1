param(
  [switch]$Task,
  [string]$InstallDir = "$env:ProgramData\NGAV-Agent",
  [string]$TaskName = "NGAV Agent",
  [string]$WatchPaths = ""
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
