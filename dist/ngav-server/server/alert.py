import argparse
import json
import smtplib
import time
from dataclasses import dataclass
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import error, parse, request

import yaml

try:
    from . import elastic_store
except ImportError:
    import elastic_store


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
LOG_DIR = Path(__file__).resolve().parent / "logs"
ALERTS_FILE = LOG_DIR / "alerts.jsonl"


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
class TelegramConfig:
    enabled: bool
    bot_token: str
    chat_id: str


@dataclass
class DiscordConfig:
    enabled: bool
    webhook_url: str


@dataclass
class AlertConfig:
    email: EmailConfig
    telegram: TelegramConfig
    discord: DiscordConfig


def load_alert_config(config_path: Path = DEFAULT_CONFIG_PATH) -> AlertConfig:
    with Path(config_path).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    email_raw = raw.get("email", {})
    telegram_raw = raw.get("telegram", {})
    discord_raw = raw.get("discord", {})

    return AlertConfig(
        email=EmailConfig(
            enabled=bool(email_raw.get("enabled", False)),
            smtp_server=email_raw.get("smtp_server", ""),
            smtp_port=int(email_raw.get("smtp_port", 587)),
            use_tls=bool(email_raw.get("use_tls", True)),
            username=email_raw.get("username", ""),
            password=email_raw.get("password", ""),
            from_addr=email_raw.get("from", ""),
            to_addrs=list(email_raw.get("to", [])),
        ),
        telegram=TelegramConfig(
            enabled=bool(telegram_raw.get("enabled", False)),
            bot_token=telegram_raw.get("bot_token", ""),
            chat_id=str(telegram_raw.get("chat_id", "")),
        ),
        discord=DiscordConfig(
            enabled=bool(discord_raw.get("enabled", False)),
            webhook_url=discord_raw.get("webhook_url", ""),
        ),
    )


def build_alert(detection: Dict[str, Any], event: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    record = detection.get("record") or {}
    endpoint = detection.get("endpoint") or (event or {}).get("endpoint") or "unknown"
    score = float(detection.get("score", 0.0))
    threshold = float(detection.get("threshold", 0.0))

    return {
        "created_ts": time.time(),
        "severity": _severity(score, threshold),
        "endpoint": endpoint,
        "event_id": detection.get("event_id") or (event or {}).get("id"),
        "event_type": detection.get("event_type") or (event or {}).get("event_type"),
        "engine": detection.get("model_name", "ngav"),
        "score": score,
        "threshold": threshold,
        "process": {
            "pid": record.get("pid"),
            "ppid": record.get("ppid"),
            "name": record.get("name"),
            "exe": record.get("exe"),
            "username": record.get("username"),
            "status": record.get("status"),
            "platform": record.get("platform"),
        },
        "reason": _reason(detection),
    }


def handle_detection(
    detection: Dict[str, Any],
    event: Optional[Dict[str, Any]] = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> Optional[Dict[str, Any]]:
    if not detection.get("is_anomaly"):
        return None
    alert = build_alert(detection, event=event)
    handle_alert(alert, config_path=config_path)
    return alert


def handle_alert(alert: Dict[str, Any], config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    config = load_alert_config(config_path)
    log_alert(alert)
    send_email_alert(config.email, alert)
    send_telegram_alert(config.telegram, alert)
    send_discord_alert(config.discord, alert)
    print("[ALERT]", json.dumps(alert, ensure_ascii=False))


def log_alert(alert: Dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with ALERTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(alert, ensure_ascii=False) + "\n")
    elastic_store.index_alert(alert)


def send_email_alert(email_cfg: EmailConfig, alert: Dict[str, Any]) -> None:
    if not email_cfg.enabled:
        return
    if not (email_cfg.smtp_server and email_cfg.from_addr and email_cfg.to_addrs):
        print("[warn] Email alert is enabled but SMTP config is incomplete.")
        return

    subject, body = format_alert_message(alert)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = email_cfg.from_addr
    msg["To"] = ", ".join(email_cfg.to_addrs)

    try:
        with smtplib.SMTP(email_cfg.smtp_server, email_cfg.smtp_port, timeout=20) as server:
            if email_cfg.use_tls:
                server.starttls()
            if email_cfg.username:
                server.login(email_cfg.username, email_cfg.password)
            server.sendmail(email_cfg.from_addr, email_cfg.to_addrs, msg.as_string())
    except Exception as ex:
        print(f"[warn] Email alert error: {ex}")


def send_telegram_alert(telegram_cfg: TelegramConfig, alert: Dict[str, Any]) -> None:
    if not telegram_cfg.enabled:
        return
    if not (telegram_cfg.bot_token and telegram_cfg.chat_id):
        print("[warn] Telegram alert is enabled but config is incomplete.")
        return

    _, body = format_alert_message(alert)
    payload = parse.urlencode({"chat_id": telegram_cfg.chat_id, "text": body}).encode("utf-8")
    req = request.Request(
        f"https://api.telegram.org/bot{telegram_cfg.bot_token}/sendMessage",
        data=payload,
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=20) as response:
            if response.status >= 400:
                print(f"[warn] Telegram alert failed with status={response.status}")
    except error.URLError as ex:
        print(f"[warn] Telegram alert error: {ex}")


def send_discord_alert(discord_cfg: DiscordConfig, alert: Dict[str, Any]) -> None:
    if not discord_cfg.enabled:
        return
    if not discord_cfg.webhook_url:
        print("[warn] Discord alert is enabled but webhook_url is empty.")
        return

    subject, body = format_alert_message(alert)
    payload = {"content": f"**{subject}**\n```text\n{body}\n```"}
    req = request.Request(
        discord_cfg.webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=20) as response:
            if response.status >= 400:
                print(f"[warn] Discord alert failed with status={response.status}")
    except error.URLError as ex:
        print(f"[warn] Discord alert error: {ex}")


def format_alert_message(alert: Dict[str, Any]) -> tuple:
    process = alert.get("process") or {}
    subject = (
        f"[NGAV ALERT] {alert.get('severity', 'unknown').upper()} "
        f"{alert.get('engine', 'ngav')} on {alert.get('endpoint', 'unknown')}"
    )
    body = "\n".join(
        [
            f"Severity: {alert.get('severity', 'unknown')}",
            f"Endpoint: {alert.get('endpoint', 'unknown')}",
            f"Engine: {alert.get('engine', 'unknown')}",
            f"Event ID: {alert.get('event_id', 'unknown')}",
            f"Event type: {alert.get('event_type', 'unknown')}",
            f"Score: {float(alert.get('score', 0.0)):.6f}",
            f"Threshold: {float(alert.get('threshold', 0.0)):.6f}",
            f"Reason: {alert.get('reason', 'unknown')}",
            "",
            "Process:",
            f"- pid: {process.get('pid')}",
            f"- ppid: {process.get('ppid')}",
            f"- name: {process.get('name')}",
            f"- exe: {process.get('exe')}",
            f"- username: {process.get('username')}",
            f"- status: {process.get('status')}",
            f"- platform: {process.get('platform')}",
        ]
    )
    return subject, body


def _severity(score: float, threshold: float) -> str:
    gap = score - threshold
    if gap >= 0.2:
        return "critical"
    if gap >= 0.05:
        return "high"
    return "medium"


def _reason(detection: Dict[str, Any]) -> str:
    model_name = detection.get("model_name", "ngav")
    score = float(detection.get("score", 0.0))
    threshold = float(detection.get("threshold", 0.0))
    return f"{model_name} anomaly score {score:.6f} exceeded threshold {threshold:.6f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Send an alert from a detection JSON object")
    parser.add_argument("detection_json", help="Detection JSON object or path to a JSON file")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.yaml")
    args = parser.parse_args()

    raw = Path(args.detection_json)
    if raw.exists():
        detection = json.loads(raw.read_text(encoding="utf-8"))
    else:
        detection = json.loads(args.detection_json)

    alert = handle_detection(detection, config_path=Path(args.config))
    if alert is None:
        print("[info] Detection is not anomalous; no alert sent.")


if __name__ == "__main__":
    main()
