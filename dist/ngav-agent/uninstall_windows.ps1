param(
  [string]$InstallDir = "$env:ProgramData\NGAV-Agent",
  [string]$TaskName = "NGAV Agent"
)

$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
  Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  Write-Host "[ok] removed Scheduled Task: $TaskName"
}

if (Test-Path $InstallDir) {
  Remove-Item -Recurse -Force $InstallDir
  Write-Host "[ok] removed install directory: $InstallDir"
}
