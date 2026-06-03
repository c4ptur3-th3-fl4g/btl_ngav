import argparse
import os
import shutil
import stat
import zipfile
from pathlib import Path
from typing import Iterable, Optional

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "dist"
AGENT_REQUIREMENTS = [
    "psutil",
    "pyyaml",
    "watchdog",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a deployable NGAV agent bundle")
    parser.add_argument("--collector-url", required=True, help="Collector URL, for example http://10.0.0.5:8000")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for generated bundle")
    parser.add_argument("--name", default="ngav-agent", help="Bundle directory name")
    parser.add_argument("--no-zip", action="store_true", help="Only create directory, skip .zip archive")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    bundle_dir = output_dir / args.name
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    copy_tree(PROJECT_ROOT / "agent", bundle_dir / "agent", patterns=["*.py"])
    (bundle_dir / "config").mkdir(parents=True, exist_ok=True)
    write_agent_config(bundle_dir / "config" / "config.yaml", args.collector_url)
    write_requirements(bundle_dir / "requirements-agent.txt")
    write_linux_scripts(bundle_dir)
    write_windows_scripts(bundle_dir)
    write_deploy_readme(bundle_dir, args.collector_url)

    archive_path: Optional[Path] = None
    if not args.no_zip:
        archive_path = output_dir / f"{args.name}.zip"
        if archive_path.exists():
            archive_path.unlink()
        zip_dir(bundle_dir, archive_path)

    print(f"[ok] bundle directory: {bundle_dir}")
    if archive_path:
        print(f"[ok] zip archive: {archive_path}")
    print("[next] copy the bundle to an endpoint and run install_linux.sh or install_windows.ps1")


def copy_tree(src: Path, dst: Path, patterns: Iterable[str]) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        return
    for pattern in patterns:
        for path in src.glob(pattern):
            if path.is_file():
                shutil.copy2(path, dst / path.name)


def write_agent_config(path: Path, collector_url: str) -> None:
    source = PROJECT_ROOT / "config" / "config.example.yaml"
    raw = {}
    if source.exists():
        with source.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    raw.pop("model_path", None)
    raw.pop("score_threshold", None)
    raw.setdefault("agent", {})
    raw["agent"].setdefault("endpoint_name", "auto")
    raw.setdefault("email", {})["enabled"] = False
    raw.setdefault("telegram", {})["enabled"] = False
    raw.setdefault("discord", {})["enabled"] = False
    raw["collector"] = {
        "url": collector_url.rstrip("/"),
        "api_key_path": "../agent/api_key.txt",
    }

    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, sort_keys=False)


def write_requirements(path: Path) -> None:
    path.write_text("\n".join(AGENT_REQUIREMENTS) + "\n", encoding="utf-8")


def write_linux_scripts(bundle_dir: Path) -> None:
    install = """#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$ROOT"
"$PYTHON_BIN" -m venv .venv
".venv/bin/pip" install --upgrade pip
".venv/bin/pip" install -r requirements-agent.txt

chmod +x run_agent.sh

if [[ "${1:-}" == "--systemd" ]]; then
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "[error] --systemd requires sudo/root"
    exit 1
  fi
  INSTALL_DIR="${INSTALL_DIR:-/opt/ngav-agent}"
  mkdir -p "$INSTALL_DIR"
  cp -a "$ROOT/." "$INSTALL_DIR/"
  cat >/etc/systemd/system/ngav-agent.service <<SERVICE
[Unit]
Description=NGAV Agent
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/agent/ngav_agent.py --config $INSTALL_DIR/config/config.yaml --realtime --monitor-network
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE
  systemctl daemon-reload
  systemctl enable --now ngav-agent
  echo "[ok] systemd service installed: ngav-agent"
else
  echo "[ok] installed. Run ./run_agent.sh"
fi
"""
    run = """#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

exec .venv/bin/python agent/ngav_agent.py \\
  --config config/config.yaml \\
  --realtime \\
  --monitor-network \\
  "$@"
"""
    write_executable(bundle_dir / "install_linux.sh", install)
    write_executable(bundle_dir / "run_agent.sh", run)


def write_windows_scripts(bundle_dir: Path) -> None:
    install = """param(
  [switch]$Task,
  [string]$InstallDir = "$env:ProgramData\\NGAV-Agent",
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
& .\\.venv\\Scripts\\python.exe -m pip install --upgrade pip
& .\\.venv\\Scripts\\pip.exe install -r requirements-agent.txt

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
  Write-Host "[ok] installed. Run .\\run_agent.ps1"
  Write-Host "[next] for background startup mode, run PowerShell as Administrator:"
  Write-Host "       .\\install_windows.ps1 -Task"
}
"""
    uninstall = """param(
  [string]$InstallDir = "$env:ProgramData\\NGAV-Agent",
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
"""
    run = """$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

& .\\.venv\\Scripts\\python.exe .\\agent\\ngav_agent.py `
  --config .\\config\\config.yaml `
  --realtime `
  --monitor-network `
  @args
"""
    (bundle_dir / "install_windows.ps1").write_text(install, encoding="utf-8")
    (bundle_dir / "uninstall_windows.ps1").write_text(uninstall, encoding="utf-8")
    (bundle_dir / "run_agent.ps1").write_text(run, encoding="utf-8")


def write_deploy_readme(bundle_dir: Path, collector_url: str) -> None:
    text = f"""# NGAV Agent Bundle

Collector URL: `{collector_url.rstrip("/")}`

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
.\\install_windows.ps1
.\\run_agent.ps1
```

Install as a background startup task. Run PowerShell as Administrator:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\\install_windows.ps1 -Task
Get-ScheduledTask -TaskName "NGAV Agent"
```

Add file watch paths to the startup task:

```powershell
.\\install_windows.ps1 -Task -WatchPaths "C:\\Users,C:\\Windows\\Temp"
```

Uninstall the startup task and installed files:

```powershell
.\\uninstall_windows.ps1
```

## Watch paths

Add paths at runtime:

```bash
./run_agent.sh --watch-paths /tmp,/home
```

```powershell
.\\run_agent.ps1 --watch-paths C:\\Users,C:\\Windows\\Temp
```

This bundle is sensor-only. Models stay on the NGAV server; this agent only sends telemetry to the collector.

The agent stores its API key at `agent/api_key.txt` after first registration.
"""
    (bundle_dir / "README_DEPLOY.md").write_text(text, encoding="utf-8")


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def zip_dir(src_dir: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in src_dir.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(src_dir.parent))


if __name__ == "__main__":
    main()
