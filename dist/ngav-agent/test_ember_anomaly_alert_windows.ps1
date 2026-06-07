param(
  [string]$ServerUrl = "",
  [string]$ApiKey = "",
  [string]$Endpoint = "",
  [string]$InstallDir = "$env:ProgramData\NGAV-Agent"
)

$ErrorActionPreference = "Stop"

function Get-DefaultRoot {
  $scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
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

$features = @{}
for ($i = 0; $i -lt 256; $i++) {
  $features["histogram.$i"] = 999999.0
  $features["byteentropy.$i"] = 999999.0
}
$features["general.size"] = 999999.0
$features["general.vsize"] = 999999.0
$features["general.has_debug"] = 1.0
$features["strings.numstrings"] = 999999.0
$features["strings.entropy"] = 999999.0
$features["strings.urls"] = 999999.0
$features["strings.registry"] = 999999.0

$payload = @{
  endpoint = $Endpoint
  event_type = "ember_test_anomaly"
  timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  data = @{
    ember_features = $features
    test_marker = "ngav_agent_ember_anomaly_alert_test"
    note = "Synthetic EMBER features for testing server-side EMBER anomaly alert pipeline"
  }
} | ConvertTo-Json -Depth 8

$headers = @{
  "Content-Type" = "application/json"
  "X-API-Key" = $ApiKey
}

Write-Host "[info] sending EMBER anomaly test event to $ServerUrl/ingest"
$response = Invoke-RestMethod -Method Post -Uri "$ServerUrl/ingest" -Headers $headers -Body $payload -TimeoutSec 30
$response | ConvertTo-Json -Depth 8

$hasAnomaly = $false
if ($response.detections) {
  foreach ($det in $response.detections) {
    if ($det.is_anomaly -eq $true) {
      $hasAnomaly = $true
    }
  }
}

Write-Host ""
if ($hasAnomaly) {
  Write-Host "[ok] server returned an anomaly detection. Alert pipeline should run."
} else {
  Write-Host "[warn] server accepted the event, but no anomaly was returned."
  Write-Host "[warn] Check that EMBER models exist on the server and collector was restarted after model/config changes."
}
Write-Host "[next] check:"
Write-Host "  $ServerUrl/detections?limit=5&anomalies_only=true"
Write-Host "  $ServerUrl/api/elastic/alerts?limit=5"
Write-Host "  $ServerUrl/ui"
