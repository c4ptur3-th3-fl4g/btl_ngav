NGAV Collector

This simple collector receives JSON events from agents and stores them as JSONL.

For full server and endpoint installation steps, see `INSTALL.md` at the project root.

Architecture:
- Endpoints install only the lightweight agent in background/service mode.
- Models stay on the server.
- Agents send process, file, and network telemetry to `POST /ingest`.
- The server collector runs detection, alerting, and Elastic indexing.

Run locally:

```bash
pip install -r requirements.txt
uvicorn server.collector:app --host 0.0.0.0 --port 8000
```

One-click server install:

```bash
sudo scripts/install_server.sh --server-ip <SERVER_IP>
```

Elasticsearch/Kibana are installed natively by default. Docker is not used.

The installer:
- copies the server to `/opt/ngav-server`
- creates a Python virtualenv
- installs dependencies
- installs native Elasticsearch/Kibana into `/opt/ngav-elastic`
- creates and starts the `ngav-collector` systemd service
- enables startup on boot
- listens for agents on `0.0.0.0:8000`
- generates an endpoint bundle at `/opt/ngav-server/dist/ngav-agent.zip`

Useful server commands:

```bash
sudo systemctl status ngav-collector
sudo journalctl -u ngav-collector -f
curl http://<SERVER_IP>:8000/agents
```

Uninstall:

```bash
sudo scripts/uninstall_server.sh --stop-elastic
```

Open:
- NGAV web console: http://localhost:8000/ui
- Kibana: http://localhost:5601

The collector writes to these Elasticsearch indices:
- `ngav-events`
- `ngav-detections`
- `ngav-alerts`

Endpoints:
- `POST /ingest` — accept JSON with `endpoint`, `event_type`, optional `timestamp` and `data`.
  Requires an API key. Supply header `X-API-Key: <key>` or `Authorization: ApiKey <key>`.
- `GET /events?limit=100` — returns last `limit` events.
- `GET /detections?limit=100&anomalies_only=true` — returns detection results.
- `GET /ui` — opens the Elastic-backed management console.
- `GET /api/elastic/events|detections|alerts` — returns indexed Elastic documents.
- `GET /agents` — lists registered agents and their last seen IP address.

Registration:
- `POST /register_agent` — register an agent API key. Payload: `{"endpoint":"name","api_key":"optional-agent-generated-key"}`. If `api_key` is omitted, the server returns a generated key.

Logs are stored in `server/logs/events.jsonl`.

EMBER training

Put a local EMBER subset under `data/ember` or another ignored directory. The trainer accepts raw EMBER JSONL files such as `train_features_0.jsonl` or a flattened CSV with a `label` column.

```bash
.venv/bin/python scripts/train_ember_models.py --ember-path data/ember --limit 50000
```

For optional GPU training on NVIDIA GPUs such as GTX1650, first make sure `nvidia-smi` works, then install the optional GPU package:

```bash
.venv/bin/pip install -r requirements-gpu.txt
.venv/bin/python scripts/train_ember_models.py --ember-path data/ember_extracted/ember2018 --limit 50000 --device cuda
```

Use `--device auto` to prefer GPU and fall back to CPU when the driver or package is not available.

This writes:
- `models/ember_ngav.pkl` — supervised benign/malware NGAV classifier.
- `models/ember_anomaly.pkl` — anomaly detector trained from benign EMBER samples.

The collector loads these models automatically when the files exist. Send PE/static features in either `data.ember_features` or `data.pe_features`:

```json
{
  "endpoint": "host-1",
  "event_type": "pe_static",
  "data": {
    "ember_features": {
      "histogram": [0, 1, 2],
      "strings": {"numstrings": 10},
      "general": {"size": 12345}
    }
  }
}
```
