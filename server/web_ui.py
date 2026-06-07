import html
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

try:
    from . import elastic_store
    from .alert import DEFAULT_CONFIG_PATH, send_startup_notification
except ImportError:
    import elastic_store
    from alert import DEFAULT_CONFIG_PATH, send_startup_notification


router = APIRouter()
_AGENTS_PROVIDER = None


def set_agents_provider(provider) -> None:
    global _AGENTS_PROVIDER
    _AGENTS_PROVIDER = provider


@router.get("/ui", response_class=HTMLResponse)
def dashboard() -> str:
    health = elastic_store.health()
    stats = elastic_store.stats()
    detections = elastic_store.search_documents(elastic_store.DETECTIONS_INDEX, limit=25)
    alerts = elastic_store.search_documents(elastic_store.ALERTS_INDEX, limit=25)
    events = elastic_store.search_documents(elastic_store.EVENTS_INDEX, limit=25)
    agents = _AGENTS_PROVIDER() if _AGENTS_PROVIDER else []
    return _render_page(health=health, stats=stats, detections=detections, alerts=alerts, events=events, agents=agents)


@router.get("/api/elastic/health")
def elastic_health() -> Dict[str, Any]:
    return elastic_store.health()


@router.get("/api/elastic/stats")
def elastic_stats() -> Dict[str, Any]:
    return elastic_store.stats()


@router.get("/api/elastic/events")
def elastic_events(limit: int = 100, q: Optional[str] = None) -> Dict[str, Any]:
    return {"events": elastic_store.search_documents(elastic_store.EVENTS_INDEX, limit=limit, query=q)}


@router.get("/api/elastic/detections")
def elastic_detections(limit: int = 100, q: Optional[str] = None) -> Dict[str, Any]:
    return {"detections": elastic_store.search_documents(elastic_store.DETECTIONS_INDEX, limit=limit, query=q)}


@router.get("/api/elastic/alerts")
def elastic_alerts(limit: int = 100, q: Optional[str] = None) -> Dict[str, Any]:
    return {"alerts": elastic_store.search_documents(elastic_store.ALERTS_INDEX, limit=limit, query=q)}


@router.get("/api/notifications/settings")
def notification_settings() -> Dict[str, Any]:
    config = _load_config()
    return {"config_path": str(DEFAULT_CONFIG_PATH), "settings": _notification_config(config)}


@router.post("/api/notifications/settings")
def save_notification_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    config = _load_config()
    settings = payload.get("settings", payload)
    _apply_notification_config(config, settings)
    _write_config(config)
    return {"status": "ok", "config_path": str(DEFAULT_CONFIG_PATH), "settings": _notification_config(config)}


@router.post("/api/notifications/test")
def test_notifications() -> Dict[str, Any]:
    try:
        results = send_startup_notification(config_path=DEFAULT_CONFIG_PATH)
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))
    return {
        "status": "ok",
        "results": [
            {
                "channel": result.channel,
                "enabled": result.enabled,
                "sent": result.sent,
                "error": result.error,
            }
            for result in results
        ],
    }


def _render_page(
    health: Dict[str, Any],
    stats: Dict[str, Any],
    detections: List[Dict[str, Any]],
    alerts: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    agents: List[Dict[str, Any]],
) -> str:
    status = "Online" if health.get("enabled") else "Offline"
    status_class = "ok" if health.get("enabled") else "bad"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NGAV Elastic Console</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --line: #d9dee7;
      --text: #1d2430;
      --muted: #5b677a;
      --ok: #087f5b;
      --bad: #b42318;
      --accent: #2563eb;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 18px 24px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0;
      font-size: 20px;
      letter-spacing: 0;
    }}
    main {{
      max-width: 1320px;
      margin: 0 auto;
      padding: 20px;
    }}
    .status {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 14px;
    }}
    .dot {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--bad);
    }}
    .dot.ok {{ background: var(--ok); }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .metric, section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .metric {{
      padding: 16px;
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
    }}
    .metric strong {{
      display: block;
      margin-top: 6px;
      font-size: 28px;
    }}
    section {{
      margin-bottom: 18px;
      overflow: hidden;
    }}
    section h2 {{
      margin: 0;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      font-size: 16px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      font-size: 13px;
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
    }}
    th {{
      color: var(--muted);
      font-weight: 600;
      background: #fbfcfe;
    }}
    .pill {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      background: #e8eefc;
      color: var(--accent);
      font-size: 12px;
      font-weight: 600;
    }}
    .badtext {{ color: var(--bad); font-weight: 700; }}
    .muted {{ color: var(--muted); }}
    .connect {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      padding: 14px 16px;
    }}
    .connect input {{
      min-width: 220px;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      font: inherit;
    }}
    .settings {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
      padding: 14px 16px;
    }}
    .channel {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfe;
    }}
    .channel h3 {{
      margin: 0 0 10px;
      font-size: 14px;
    }}
    .field {{
      display: grid;
      gap: 5px;
      margin-bottom: 9px;
    }}
    .field label, .check {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }}
    .field input, .field textarea {{
      width: 100%;
      box-sizing: border-box;
      padding: 8px 9px;
      border: 1px solid var(--line);
      border-radius: 6px;
      font: inherit;
      background: white;
    }}
    .field textarea {{
      min-height: 72px;
      resize: vertical;
    }}
    .actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      padding: 0 16px 14px;
    }}
    .connect button {{
      padding: 8px 12px;
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: white;
      font-weight: 700;
      cursor: pointer;
    }}
    .actions button {{
      padding: 8px 12px;
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: white;
      font-weight: 700;
      cursor: pointer;
    }}
    .actions button.secondary {{
      background: #475569;
    }}
    .keybox {{
      margin: 0;
      padding: 0 16px 14px;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }}
    @media (max-width: 760px) {{
      header {{ align-items: flex-start; flex-direction: column; gap: 8px; }}
      .grid {{ grid-template-columns: 1fr; }}
      .settings {{ grid-template-columns: 1fr; }}
      th:nth-child(4), td:nth-child(4) {{ display: none; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>NGAV Elastic Console</h1>
    <div class="status"><span class="dot {status_class}"></span>Elastic {html.escape(status)} at {html.escape(str(health.get("url", "")))}</div>
  </header>
  <main>
    <div class="grid">
      {_metric("Events", stats.get("events", 0))}
      {_metric("Detections", stats.get("detections", 0))}
      {_metric("Alerts", stats.get("alerts", 0))}
    </div>
    {_table("Recent Alerts", alerts, ["@timestamp", "severity", "endpoint", "engine", "reason"])}
    {_table("Connected Devices", agents, ["endpoint", "last_remote_addr", "os_name", "os_version", "hostname", "last_seen_ts"])}
    {_table("Recent Detections", detections, ["@timestamp", "model_name", "endpoint", "event_type", "score", "is_anomaly"])}
    {_table("Recent Events", events, ["@timestamp", "endpoint", "event_type", "remote_addr", "id"])}
    <section>
      <h2>Agent Connect</h2>
      <div class="connect">
        <input id="connect-endpoint" value="manual-agent" aria-label="Endpoint name">
        <button id="connect-button" type="button">Connect</button>
        <span class="muted">Generate an API key for an endpoint agent.</span>
      </div>
      <pre id="connect-result" class="keybox">Click Connect to generate an API key.</pre>
    </section>
    <section>
      <h2>Notification Settings</h2>
      <div class="settings">
        <div class="channel">
          <h3>Email / Gmail</h3>
          <label class="check"><input id="email-enabled" type="checkbox"> Enabled</label>
          <div class="field"><label>SMTP server</label><input id="email-smtp-server" value="smtp.gmail.com"></div>
          <div class="field"><label>SMTP port</label><input id="email-smtp-port" type="number" value="587"></div>
          <label class="check"><input id="email-use-tls" type="checkbox" checked> Use TLS</label>
          <div class="field"><label>Username</label><input id="email-username"></div>
          <div class="field"><label>Password / app password</label><input id="email-password" type="password"></div>
          <div class="field"><label>From</label><input id="email-from"></div>
          <div class="field"><label>To, one address per line</label><textarea id="email-to"></textarea></div>
        </div>
        <div class="channel">
          <h3>Telegram</h3>
          <label class="check"><input id="telegram-enabled" type="checkbox"> Enabled</label>
          <div class="field"><label>Bot token</label><input id="telegram-bot-token" type="password"></div>
          <div class="field"><label>Chat ID</label><input id="telegram-chat-id"></div>
        </div>
        <div class="channel">
          <h3>Discord</h3>
          <label class="check"><input id="discord-enabled" type="checkbox"> Enabled</label>
          <div class="field"><label>Webhook URL</label><input id="discord-webhook-url" type="password"></div>
        </div>
      </div>
      <div class="actions">
        <button id="notification-save" type="button">Save Settings</button>
        <button id="notification-test" class="secondary" type="button">Test Notifications</button>
      </div>
      <pre id="notification-result" class="keybox">Notification settings are loaded from config.yaml.</pre>
    </section>
    <section>
      <h2>Elastic Health</h2>
      <pre>{html.escape(json.dumps(health, indent=2, ensure_ascii=False))}</pre>
    </section>
  </main>
  <script>
    const button = document.getElementById("connect-button");
    const output = document.getElementById("connect-result");
    const endpoint = document.getElementById("connect-endpoint");
    button.addEventListener("click", async () => {{
      output.textContent = "Generating API key...";
      try {{
        const response = await fetch("/api/agent/connect-key", {{
          method: "POST",
          headers: {{"Content-Type": "application/json"}},
          body: JSON.stringify({{endpoint: endpoint.value || "manual-agent"}})
        }});
        const payload = await response.json();
        if (!response.ok) {{
          throw new Error(payload.detail || JSON.stringify(payload));
        }}
        const origin = window.location.origin;
        output.textContent =
          "Server URL: " + origin + "\\n" +
          "Endpoint: " + payload.endpoint + "\\n" +
          "API Key: " + payload.api_key + "\\n\\n" +
          "Linux install example:\\n" +
          "sudo ./install_linux.sh --systemd --server-url " + origin + " --api-key " + payload.api_key + "\\n\\n" +
          "Windows install example:\\n" +
          ".\\\\install_windows.ps1 -Task -ServerUrl " + origin + " -ApiKey " + payload.api_key;
      }} catch (err) {{
        output.textContent = "Failed to generate API key: " + err;
      }}
    }});

    const notifOutput = document.getElementById("notification-result");
    const notificationFields = {{
      emailEnabled: document.getElementById("email-enabled"),
      emailSmtpServer: document.getElementById("email-smtp-server"),
      emailSmtpPort: document.getElementById("email-smtp-port"),
      emailUseTls: document.getElementById("email-use-tls"),
      emailUsername: document.getElementById("email-username"),
      emailPassword: document.getElementById("email-password"),
      emailFrom: document.getElementById("email-from"),
      emailTo: document.getElementById("email-to"),
      telegramEnabled: document.getElementById("telegram-enabled"),
      telegramBotToken: document.getElementById("telegram-bot-token"),
      telegramChatId: document.getElementById("telegram-chat-id"),
      discordEnabled: document.getElementById("discord-enabled"),
      discordWebhookUrl: document.getElementById("discord-webhook-url")
    }};

    function collectNotificationSettings() {{
      return {{
        email: {{
          enabled: notificationFields.emailEnabled.checked,
          smtp_server: notificationFields.emailSmtpServer.value.trim(),
          smtp_port: Number(notificationFields.emailSmtpPort.value || 587),
          use_tls: notificationFields.emailUseTls.checked,
          username: notificationFields.emailUsername.value.trim(),
          password: notificationFields.emailPassword.value,
          from: notificationFields.emailFrom.value.trim(),
          to: notificationFields.emailTo.value.split(/\\r?\\n/).map(v => v.trim()).filter(Boolean)
        }},
        telegram: {{
          enabled: notificationFields.telegramEnabled.checked,
          bot_token: notificationFields.telegramBotToken.value.trim(),
          chat_id: notificationFields.telegramChatId.value.trim()
        }},
        discord: {{
          enabled: notificationFields.discordEnabled.checked,
          webhook_url: notificationFields.discordWebhookUrl.value.trim()
        }}
      }};
    }}

    function fillNotificationSettings(settings) {{
      const email = settings.email || {{}};
      const telegram = settings.telegram || {{}};
      const discord = settings.discord || {{}};
      notificationFields.emailEnabled.checked = Boolean(email.enabled);
      notificationFields.emailSmtpServer.value = email.smtp_server || "smtp.gmail.com";
      notificationFields.emailSmtpPort.value = email.smtp_port || 587;
      notificationFields.emailUseTls.checked = email.use_tls !== false;
      notificationFields.emailUsername.value = email.username || "";
      notificationFields.emailPassword.value = email.password || "";
      notificationFields.emailFrom.value = email.from || "";
      notificationFields.emailTo.value = (email.to || []).join("\\n");
      notificationFields.telegramEnabled.checked = Boolean(telegram.enabled);
      notificationFields.telegramBotToken.value = telegram.bot_token || "";
      notificationFields.telegramChatId.value = telegram.chat_id || "";
      notificationFields.discordEnabled.checked = Boolean(discord.enabled);
      notificationFields.discordWebhookUrl.value = discord.webhook_url || "";
    }}

    async function loadNotificationSettings() {{
      try {{
        const response = await fetch("/api/notifications/settings");
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || JSON.stringify(payload));
        fillNotificationSettings(payload.settings || {{}});
        notifOutput.textContent = "Loaded from " + payload.config_path;
      }} catch (err) {{
        notifOutput.textContent = "Failed to load notification settings: " + err;
      }}
    }}

    document.getElementById("notification-save").addEventListener("click", async () => {{
      notifOutput.textContent = "Saving notification settings...";
      try {{
        const response = await fetch("/api/notifications/settings", {{
          method: "POST",
          headers: {{"Content-Type": "application/json"}},
          body: JSON.stringify({{settings: collectNotificationSettings()}})
        }});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || JSON.stringify(payload));
        fillNotificationSettings(payload.settings || {{}});
        notifOutput.textContent = "Saved to " + payload.config_path;
      }} catch (err) {{
        notifOutput.textContent = "Failed to save notification settings: " + err;
      }}
    }});

    document.getElementById("notification-test").addEventListener("click", async () => {{
      notifOutput.textContent = "Sending test notification...";
      try {{
        const response = await fetch("/api/notifications/test", {{method: "POST"}});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || JSON.stringify(payload));
        notifOutput.textContent = JSON.stringify(payload.results, null, 2);
      }} catch (err) {{
        notifOutput.textContent = "Failed to send test notification: " + err;
      }}
    }});

    loadNotificationSettings();
  </script>
</body>
</html>"""


def _metric(label: str, value: Any) -> str:
    return f'<div class="metric"><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>'


def _table(title: str, rows: List[Dict[str, Any]], columns: List[str]) -> str:
    header = "".join(f"<th>{html.escape(col)}</th>" for col in columns)
    body = "".join(_row(row, columns) for row in rows) or f'<tr><td colspan="{len(columns)}" class="muted">No documents found.</td></tr>'
    return f"<section><h2>{html.escape(title)}</h2><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></section>"


def _row(row: Dict[str, Any], columns: List[str]) -> str:
    cells = "".join(f"<td>{_format_cell(col, row.get(col))}</td>" for col in columns)
    return f"<tr>{cells}</tr>"


def _format_cell(column: str, value: Any) -> str:
    if value is None:
        return '<span class="muted">-</span>'
    if column in {"is_anomaly"} and value:
        return '<span class="badtext">true</span>'
    if column in {"severity", "model_name", "engine"}:
        return f'<span class="pill">{html.escape(str(value))}</span>'
    if isinstance(value, float):
        return html.escape(f"{value:.6f}")
    if isinstance(value, (dict, list)):
        return html.escape(json.dumps(value, ensure_ascii=False)[:240])
    return html.escape(str(value))


def _load_config() -> Dict[str, Any]:
    path = Path(DEFAULT_CONFIG_PATH)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"cannot read config {path}: {ex}")


def _write_config(config: Dict[str, Any]) -> None:
    path = Path(DEFAULT_CONFIG_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True)
        os.replace(tmp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"cannot write config {path}: {ex}")


def _notification_config(config: Dict[str, Any]) -> Dict[str, Any]:
    email = dict(config.get("email") or {})
    telegram = dict(config.get("telegram") or {})
    discord = dict(config.get("discord") or {})
    return {
        "email": {
            "enabled": bool(email.get("enabled", False)),
            "smtp_server": str(email.get("smtp_server", "smtp.gmail.com")),
            "smtp_port": int(email.get("smtp_port", 587) or 587),
            "use_tls": bool(email.get("use_tls", True)),
            "username": str(email.get("username", "")),
            "password": str(email.get("password", "")),
            "from": str(email.get("from", "")),
            "to": list(email.get("to") or []),
        },
        "telegram": {
            "enabled": bool(telegram.get("enabled", False)),
            "bot_token": str(telegram.get("bot_token", "")),
            "chat_id": str(telegram.get("chat_id", "")),
        },
        "discord": {
            "enabled": bool(discord.get("enabled", False)),
            "webhook_url": str(discord.get("webhook_url", "")),
        },
    }


def _apply_notification_config(config: Dict[str, Any], settings: Dict[str, Any]) -> None:
    current = _notification_config(config)
    email = dict(settings.get("email") or {})
    telegram = dict(settings.get("telegram") or {})
    discord = dict(settings.get("discord") or {})

    config["email"] = {
        "enabled": bool(email.get("enabled", False)),
        "smtp_server": str(email.get("smtp_server") or current["email"]["smtp_server"]),
        "smtp_port": _as_int(email.get("smtp_port"), current["email"]["smtp_port"]),
        "use_tls": bool(email.get("use_tls", True)),
        "username": str(email.get("username", "")),
        "password": str(email.get("password", "")),
        "from": str(email.get("from", "")),
        "to": _as_string_list(email.get("to")),
    }
    config["telegram"] = {
        "enabled": bool(telegram.get("enabled", False)),
        "bot_token": str(telegram.get("bot_token", "")),
        "chat_id": str(telegram.get("chat_id", "")),
    }
    config["discord"] = {
        "enabled": bool(discord.get("enabled", False)),
        "webhook_url": str(discord.get("webhook_url", "")),
    }


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    return []
