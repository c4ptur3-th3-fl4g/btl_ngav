param(
  [string]$ServerUrl = "",
  [string]$ApiKey = "",
  [string]$Endpoint = "",
  [string]$InstallDir = "$env:ProgramData\NGAV-Agent"
)

$ErrorActionPreference = "Stop"

function Get-DefaultRoot {
  $scriptRoot = Split-Path -Parent $MyInvocation.ScriptName
  if ($scriptRoot -and (Test-Path (Join-Path $scriptRoot "config\config.yaml"))) {
    return $scriptRoot
  }
  if (Test-Path (Join-Path $InstallDir "config\config.yaml")) {
    return $InstallDir
  }
  return $scriptRoot
}

function Get-CollectorUrlFromConfig {
  param([string]$ConfigPath)
  if (-not (Test-Path $ConfigPath)) {
    return ""
  }
  $lines = Get-Content $ConfigPath
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\s*collector\s*:\s*$') {
      for ($j = $i + 1; $j -lt $lines.Count; $j++) {
        if ($lines[$j] -match '^\S') {
          break
        }
        if ($lines[$j] -match '^\s*url\s*:\s*["'']?([^"'']+)["'']?\s*$') {
          return $Matches[1].Trim()
        }
      }
    }
  }
  return ""
}

$Root = Get-DefaultRoot
$ConfigPath = Join-Path $Root "config\config.yaml"
$KeyPath = Join-Path $Root "agent\api_key.txt"

if (-not $ServerUrl) {
  $ServerUrl = Get-CollectorUrlFromConfig -ConfigPath $ConfigPath
}
if (-not $ServerUrl) {
  $ServerUrl = Read-Host "NGAV Server URL, for example http://10.18.1.134:8000"
}
$ServerUrl = $ServerUrl.TrimEnd("/")

if (-not $ApiKey -and (Test-Path $KeyPath)) {
  $ApiKey = (Get-Content $KeyPath -Raw).Trim()
}
if (-not $ApiKey) {
  $ApiKey = Read-Host "NGAV API key"
}

if (-not $Endpoint) {
  $Endpoint = $env:COMPUTERNAME
}

$os = Get-CimInstance Win32_OperatingSystem
$payload = @{
  endpoint = $Endpoint
  event_type = "process_sample"
  timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  data = @{
    records = @(
      @{
        pid = 4242
        ppid = 1000
        name = "ngav-alert-test.exe"
        exe = "$env:TEMP\ngav-alert-test.exe"
        username = "$env:USERDOMAIN\$env:USERNAME"
        status = "running"
        platform = "windows"
        cmdline_len = 240
        num_threads = 64
        memory_rss = 268435456
        cpu_percent = 87.5
        is_system_path = 0
        is_temp_path = 1
        create_time = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        cmdline = "powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand <NGAV_TEST_ONLY>"
        test_marker = "ngav_windows_alert_test"
        os = $os.Caption
        os_version = $os.Version
      }
    )
  }
} | ConvertTo-Json -Depth 8

$headers = @{
  "Content-Type" = "application/json"
  "X-API-Key" = $ApiKey
}

Write-Host "[info] sending NGAV test event to $ServerUrl/ingest"
$response = Invoke-RestMethod -Method Post -Uri "$ServerUrl/ingest" -Headers $headers -Body $payload -TimeoutSec 20
$response | ConvertTo-Json -Depth 8

Write-Host ""
Write-Host "[ok] test event sent from endpoint: $Endpoint"
Write-Host "[next] check:"
Write-Host "  $ServerUrl/events?limit=5"
Write-Host "  $ServerUrl/api/elastic/events?limit=5"
Write-Host "  $ServerUrl/ui"
Write-Host ""
Write-Host "[note] Telegram/Discord alert is sent only if the server model marks this event as anomalous."
