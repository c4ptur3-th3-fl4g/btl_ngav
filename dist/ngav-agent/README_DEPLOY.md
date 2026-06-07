# NGAV Agent Bundle

Collector URL: `http://10.18.1.134:8000`

## Linux

```bash
chmod +x install_linux.sh run_agent.sh
./install_linux.sh --server-ip SERVER_IP --api-key API_KEY
./run_agent.sh
```

Install as a systemd service:

```bash
sudo ./install_linux.sh --systemd --server-ip SERVER_IP --api-key API_KEY
sudo systemctl status ngav-agent
```

You can also pass the full collector URL:

```bash
sudo ./install_linux.sh --systemd --server-url http://SERVER_IP:8000 --api-key API_KEY
```

## Windows PowerShell

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install_windows.ps1 -ServerIp SERVER_IP -ApiKey API_KEY
.\run_agent.ps1
```

Install as a background startup task. Run PowerShell as Administrator:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install_windows.ps1 -Task -ServerIp SERVER_IP -ApiKey API_KEY
Get-ScheduledTask -TaskName "NGAV Agent"
```

Add file watch paths to the startup task:

```powershell
.\install_windows.ps1 -Task -ServerIp SERVER_IP -ApiKey API_KEY -WatchPaths "C:\Users,C:\Windows\Temp"
```

Uninstall the startup task and installed files:

```powershell
.\uninstall_windows.ps1
```

## Watch paths

Add paths at runtime:

```bash
./run_agent.sh --watch-paths /tmp,/home
```

```powershell
.\run_agent.ps1 --watch-paths C:\Users,C:\Windows\Temp
```

This bundle is sensor-only. Models stay on the NGAV server; this agent only sends telemetry to the collector.

Use the Server UI Connect button to generate `API_KEY`.

The agent stores its API key at `agent/api_key.txt`.

## Test EMBER anomaly alert

Run on a Windows endpoint after the agent has been installed and registered:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\test_ember_anomaly_alert_windows.ps1
```

Or pass values explicitly:

```powershell
.\test_ember_anomaly_alert_windows.ps1 -ServerUrl http://SERVER_IP:8000 -ApiKey API_KEY
```

This sends synthetic EMBER features to the server so the server-side EMBER model can produce an anomaly detection and trigger alert delivery.
