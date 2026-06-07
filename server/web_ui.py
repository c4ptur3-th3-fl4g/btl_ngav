import html
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

try:
    from . import elastic_store
except ImportError:
    import elastic_store


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
    .connect button {{
      padding: 8px 12px;
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: white;
      font-weight: 700;
      cursor: pointer;
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
