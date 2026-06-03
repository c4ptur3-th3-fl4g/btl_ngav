$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

& .\.venv\Scripts\python.exe .\agent\ngav_agent.py `
  --config .\config\config.yaml `
  --realtime `
  --monitor-network `
  @args
