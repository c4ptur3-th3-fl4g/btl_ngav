# NGAV Installation Guide

This project uses a server-centered architecture.

- The server stores models, receives telemetry, detects suspicious behavior, sends alerts, and writes to Elasticsearch.
- Endpoints install only the lightweight agent. Agents do not include models.
- Agents run in the background and start with the operating system.

## 1. Server Install

### Requirements

- Linux server
- Python 3
- `sudo`
- `curl` and `tar`
- Network access from endpoint machines to server port `8000`

### One-Click Install

On the server, run:

```bash
sudo scripts/install_server.sh --server-ip <SERVER_IP>
```

Example:

```bash
sudo scripts/install_server.sh --server-ip 192.168.1.10
```

Elasticsearch and Kibana are installed natively by default. Docker is not used.

The native installer downloads Elastic Linux tarballs directly from Elastic, so it works on Arch Linux, Ubuntu, Debian, and other x86_64 Linux distributions with systemd. It does not use Docker, APT packages, Pacman packages, or AUR packages. It installs Elastic into:

```text
/opt/ngav-elastic
```

It configures Elasticsearch as single-node on `127.0.0.1:9200` and Kibana on `0.0.0.0:5601`.

The installer will:

- copy the server to `/opt/ngav-server`
- create `/opt/ngav-server/.venv`
- install `requirements.txt`
- install and start native Elasticsearch/Kibana
- create the `ngav-collector` systemd service
- enable the service at boot
- listen for agents on `0.0.0.0:8000`
- generate an agent bundle at `/opt/ngav-server/dist/ngav-agent.zip`

### Server URLs

Replace `<SERVER_IP>` with your server IP:

```text
Collector API: http://<SERVER_IP>:8000
NGAV Console:  http://<SERVER_IP>:8000/ui
Kibana:        http://<SERVER_IP>:5601
Agents API:    http://<SERVER_IP>:8000/agents
```

### Server Management

```bash
sudo systemctl status ngav-collector
sudo systemctl status ngav-elasticsearch
sudo systemctl status ngav-kibana
sudo systemctl restart ngav-collector
sudo journalctl -u ngav-collector -f
```

Check connected agents:

```bash
curl http://<SERVER_IP>:8000/agents
```

Uninstall server:

```bash
sudo scripts/uninstall_server.sh --stop-elastic
```

## 2. Agent Bundle

After server install, copy this file from the server to each endpoint:

```text
/opt/ngav-server/dist/ngav-agent.zip
```

The bundle is already configured to send telemetry to:

```text
http://<SERVER_IP>:8000
```

The agent bundle contains no models.

## 3. Install Agent On Linux Endpoint

Copy `ngav-agent.zip` to the endpoint, then run:

```bash
unzip ngav-agent.zip
cd ngav-agent
sudo ./install_linux.sh --systemd
```

This installs the agent as a systemd service and starts it automatically at boot.

Check status:

```bash
sudo systemctl status ngav-agent
sudo journalctl -u ngav-agent -f
```

Install with file watch paths:

```bash
sudo ./install_linux.sh --systemd
sudo systemctl edit ngav-agent
```

Add an override if needed:

```ini
[Service]
ExecStart=
ExecStart=/opt/ngav-agent/.venv/bin/python /opt/ngav-agent/agent/ngav_agent.py --config /opt/ngav-agent/config/config.yaml --realtime --monitor-network --watch-paths /tmp,/home
```

Apply:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ngav-agent
```

## 4. Install Agent On Windows Endpoint

Copy `ngav-agent.zip` to the endpoint and extract it.

Open PowerShell as Administrator:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd .\ngav-agent
.\install_windows.ps1 -Task
```

This installs the agent into:

```text
C:\ProgramData\NGAV-Agent
```

It creates a startup Scheduled Task:

```text
NGAV Agent
```

Check status:

```powershell
Get-ScheduledTask -TaskName "NGAV Agent"
Get-ScheduledTaskInfo -TaskName "NGAV Agent"
```

Install with file watch paths:

```powershell
.\install_windows.ps1 -Task -WatchPaths "C:\Users,C:\Windows\Temp"
```

Uninstall Windows agent:

```powershell
.\uninstall_windows.ps1
```

## 5. Verify End-To-End

On the server:

```bash
curl http://<SERVER_IP>:8000/agents
```

You should see each endpoint with:

- `endpoint`
- `last_remote_addr`
- `last_seen_ts`
- `last_event_type`

Open:

```text
http://<SERVER_IP>:8000/ui
```

## 6. Firewall Notes

Allow inbound traffic on the server:

```text
TCP 8000  NGAV collector and console
TCP 5601  Kibana, optional
TCP 9200  Elasticsearch, local/admin only
```

Endpoint machines only need outbound access to:

```text
http://<SERVER_IP>:8000
```
