NGAV Collector

This simple collector receives JSON events from agents and stores them as JSONL.

Run locally:

```bash
pip install -r requirements.txt
uvicorn server.collector:app --host 0.0.0.0 --port 8000
```

Endpoints:
- `POST /ingest` — accept JSON with `endpoint`, `event_type`, optional `timestamp` and `data`.
 - `POST /ingest` — accept JSON with `endpoint`, `event_type`, optional `timestamp` and `data`.
	 Requires an API key. Supply header `X-API-Key: <key>` or `Authorization: ApiKey <key>`.
- `GET /events?limit=100` — returns last `limit` events.

Registration:
- `POST /register_agent` — register an agent API key. Payload: `{"endpoint":"name","api_key":"optional-agent-generated-key"}`. If `api_key` is omitted, the server returns a generated key.

Logs are stored in `server/logs/events.jsonl`.
