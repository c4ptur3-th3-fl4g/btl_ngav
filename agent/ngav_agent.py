import argparse
import platform
import socket
import smtplib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List, Optional

import joblib
import psutil
import yaml
import pandas as pd


@dataclass
class EmailConfig:
    enabled: bool
    smtp_server: str
    smtp_port: int
    use_tls: bool
    username: str
    password: str
    from_addr: str
    to_addrs: List[str]


@dataclass
class AgentConfig:
    scan_interval_seconds: int
    cooldown_seconds: int
    score_threshold: Optional[float]
    model_path: Path
    endpoint_name: str
    include_process_name_patterns: List[str]
    exclude_process_names: List[str]
    email: EmailConfig


def safe(callable_obj, default=None):
    try:
        return callable_obj()
    except Exception:
        return default


def load_config(config_path: Path) -> AgentConfig:
    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    email_raw = raw.get("email", {})
    endpoint_name = raw.get("agent", {}).get("endpoint_name", "auto")
    if endpoint_name == "auto":
        endpoint_name = socket.gethostname()

    email_cfg = EmailConfig(
        enabled=bool(email_raw.get("enabled", False)),
        smtp_server=email_raw.get("smtp_server", ""),
        smtp_port=int(email_raw.get("smtp_port", 587)),
        use_tls=bool(email_raw.get("use_tls", True)),
        username=email_raw.get("username", ""),
        password=email_raw.get("password", ""),
        from_addr=email_raw.get("from", ""),
        to_addrs=list(email_raw.get("to", [])),
    )

    cfg = AgentConfig(
        scan_interval_seconds=int(raw.get("scan_interval_seconds", 20)),
        cooldown_seconds=int(raw.get("cooldown_seconds", 600)),
        score_threshold=raw.get("score_threshold"),
        model_path=(config_path.parent / raw.get("model_path", "../models/ngav.pkl")).resolve(),
        endpoint_name=endpoint_name,
        include_process_name_patterns=[p.lower() for p in raw.get("agent", {}).get("include_process_name_patterns", [])],
        exclude_process_names=[p.lower() for p in raw.get("agent", {}).get("exclude_process_names", [])],
        email=email_cfg,
    )
    return cfg


def extract_process_record(proc: psutil.Process) -> Optional[Dict]:
    with proc.oneshot():
        pid = proc.pid
        ppid = safe(proc.ppid, -1)
        name = (safe(proc.name, "") or "").strip()
        exe = (safe(proc.exe, "") or "").strip()
        username = (safe(proc.username, "") or "").strip()
        cmdline = safe(proc.cmdline, []) or []
        status = safe(proc.status, "unknown") or "unknown"
        create_time = float(safe(proc.create_time, 0.0) or 0.0)
        cpu_percent = float(safe(lambda: proc.cpu_percent(interval=0.0), 0.0) or 0.0)
        memory_info = safe(proc.memory_info)
        memory_rss = int(getattr(memory_info, "rss", 0) if memory_info else 0)
        num_threads = int(safe(proc.num_threads, 0) or 0)
        num_fds = safe(proc.num_fds, -1)
        if num_fds is None:
            num_fds = -1

    lower_exe = exe.lower()
    if platform.system().lower() == "windows":
        is_system_path = int("\\windows\\system32" in lower_exe or "\\windows\\syswow64" in lower_exe)
    else:
        is_system_path = int(lower_exe.startswith("/usr/") or lower_exe.startswith("/bin/") or lower_exe.startswith("/sbin/"))

    is_temp_path = int("\\temp\\" in lower_exe or "/tmp/" in lower_exe)

    return {
        "pid": pid,
        "ppid": ppid,
        "name": name,
        "exe": exe,
        "username": username,
        "status": status,
        "create_time": create_time,
        "cpu_percent": cpu_percent,
        "memory_rss": memory_rss,
        "num_threads": num_threads,
        "num_fds": int(num_fds),
        "cmdline_len": len(" ".join(cmdline)),
        "is_system_path": is_system_path,
        "is_temp_path": is_temp_path,
        "platform": platform.system().lower(),
    }


def collect_snapshot(cfg: AgentConfig) -> pd.DataFrame:
    rows: List[Dict] = []
    include_patterns = cfg.include_process_name_patterns
    exclude_names = set(cfg.exclude_process_names)

    for proc in psutil.process_iter():
        record = safe(lambda: extract_process_record(proc))
        if not record:
            continue

        name_lower = record["name"].lower()
        if name_lower in exclude_names:
            continue

        if include_patterns and not any(p in name_lower for p in include_patterns):
            continue

        rows.append(record)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def send_email_alert(email_cfg: EmailConfig, subject: str, body: str) -> None:
    if not email_cfg.enabled:
        return

    if not (email_cfg.smtp_server and email_cfg.from_addr and email_cfg.to_addrs):
        print("[warn] Email is enabled but SMTP config is incomplete.")
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = email_cfg.from_addr
    msg["To"] = ", ".join(email_cfg.to_addrs)

    with smtplib.SMTP(email_cfg.smtp_server, email_cfg.smtp_port, timeout=20) as server:
        if email_cfg.use_tls:
            server.starttls()
        if email_cfg.username:
            server.login(email_cfg.username, email_cfg.password)
        server.sendmail(email_cfg.from_addr, email_cfg.to_addrs, msg.as_string())


def format_alert(endpoint_name: str, row: pd.Series, score: float, threshold: float) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    lines = [
        f"Time (UTC): {ts}",
        f"Endpoint: {endpoint_name}",
        f"Anomaly score: {score:.6f}",
        f"Threshold: {threshold:.6f}",
        "",
        "Process details:",
        f"- pid: {row.get('pid')}",
        f"- ppid: {row.get('ppid')}",
        f"- name: {row.get('name')}",
        f"- exe: {row.get('exe')}",
        f"- username: {row.get('username')}",
        f"- status: {row.get('status')}",
        f"- cpu_percent: {row.get('cpu_percent')}",
        f"- memory_rss: {row.get('memory_rss')}",
        f"- cmdline_len: {row.get('cmdline_len')}",
        f"- platform: {row.get('platform')}",
    ]
    return "\n".join(lines)


def run_loop(cfg: AgentConfig, one_shot: bool = False) -> None:
    bundle = joblib.load(cfg.model_path)
    pipeline = bundle["pipeline"]
    feature_columns = bundle["feature_columns"]
    bundle_threshold = float(bundle["threshold"])
    threshold = float(cfg.score_threshold) if cfg.score_threshold is not None else bundle_threshold

    print(f"[info] Loaded model bundle from {cfg.model_path}")
    print(f"[info] Running on endpoint: {cfg.endpoint_name}")
    print(f"[info] Effective threshold: {threshold:.6f}")

    alerted_until: Dict[str, float] = {}

    while True:
        df = collect_snapshot(cfg)
        if df.empty:
            print("[warn] Snapshot has no visible process records.")
        else:
            for col in feature_columns:
                if col not in df.columns:
                    df[col] = None

            X = df[feature_columns]
            scores = -pipeline.decision_function(X)
            df["anomaly_score"] = scores
            anomalies = df[df["anomaly_score"] > threshold].copy()
            anomalies.sort_values(by="anomaly_score", ascending=False, inplace=True)

            print(
                f"[info] {datetime.now().isoformat()} scanned={len(df)} flagged={len(anomalies)} "
                f"max_score={float(df['anomaly_score'].max()):.6f}"
            )

            now = time.time()
            for _, row in anomalies.iterrows():
                key = f"{row.get('name')}|{row.get('exe')}"
                next_allowed = alerted_until.get(key, 0.0)
                if now < next_allowed:
                    continue

                body = format_alert(cfg.endpoint_name, row, float(row["anomaly_score"]), threshold)
                subject = f"[NGAV] Suspicious process on {cfg.endpoint_name}: {row.get('name')}"
                send_email_alert(cfg.email, subject, body)
                alerted_until[key] = now + cfg.cooldown_seconds

        if one_shot:
            return
        time.sleep(cfg.scan_interval_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Basic cross-platform NGAV agent")
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    parser.add_argument("--once", action="store_true", help="Run one scan only")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(Path(args.config).resolve())
    run_loop(cfg, one_shot=args.once)


if __name__ == "__main__":
    main()
