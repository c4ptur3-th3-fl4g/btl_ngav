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

## Watch paths

Add paths at runtime:

```bash
./run_agent.sh --watch-paths /tmp,/home
```

```powershell
.\run_agent.ps1 --watch-paths C:\Users,C:\Windows\Temp
```

The agent stores its API key at `agent/api_key.txt` after first registration.
