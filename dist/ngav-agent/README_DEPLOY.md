# NGAV Agent Bundle

Collector URL: `http://localhost:8000`

## Linux

```bash
chmod +x install_linux.sh run_agent.sh
./install_linux.sh
./run_agent.sh
```

Install as a systemd service:

```bash
sudo ./install_linux.sh --systemd
sudo systemctl status ngav-agent
```

## Windows PowerShell

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install_windows.ps1
.\run_agent.ps1
```

Install as a background startup task. Run PowerShell as Administrator:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install_windows.ps1 -Task
Get-ScheduledTask -TaskName "NGAV Agent"
```

Add file watch paths to the startup task:

```powershell
.\install_windows.ps1 -Task -WatchPaths "C:\Users,C:\Windows\Temp"
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

The agent stores its API key at `agent/api_key.txt` after first registration.
