from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pathlib import Path
import json
import uuid
import time
from typing import Any, Dict, List, Optional
import secrets

try:
    from .detector import NgavDetector
    from .alert import handle_detection
    from . import elastic_store
    from .web_ui import router as web_ui_router, set_agents_provider
except ImportError:
    from detector import NgavDetector
    from alert import handle_detection
    import elastic_store
    from web_ui import router as web_ui_router, set_agents_provider


# Logs and keys directory
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "events.jsonl"
KEYS_FILE = LOG_DIR / "keys.jsonl"
DETECTIONS_FILE = LOG_DIR / "detections.jsonl"

# in-memory keys cache: api_key -> record
_KEYS: Dict[str, Dict[str, Any]] = {}
_DETECTOR: Optional[NgavDetector] = None


def _load_keys() -> None:
    global _KEYS
    _KEYS = {}
    if not KEYS_FILE.exists():
        return
    try:
        with KEYS_FILE.open("r", encoding="utf-8") as f:
            for ln in f:
                try:
                    rec = json.loads(ln)
                    _KEYS[rec.get("api_key")] = rec
                except Exception:
                    continue
    except Exception:
        pass


def _append_key(rec: Dict[str, Any]) -> None:
    with KEYS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    _KEYS[rec["api_key"]] = rec


_load_keys()


def _touch_agent(
    api_key: str,
    endpoint: str,
    remote_addr: Optional[str],
    event_type: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    rec = _KEYS.get(api_key)
    if not rec:
        return
    rec["endpoint"] = endpoint or rec.get("endpoint")
    rec["last_seen_ts"] = time.time()
    rec["last_remote_addr"] = remote_addr
    if event_type:
        rec["last_event_type"] = event_type
    if metadata:
        for key in ["os", "os_name", "os_version", "hostname", "machine"]:
            if metadata.get(key):
                rec[key] = metadata[key]




class AgentEvent(BaseModel):
    endpoint: str
    event_type: str
    timestamp: Optional[float] = None
    data: Optional[Dict[str, Any]] = None


app = FastAPI(title="NGAV Collector")
set_agents_provider(lambda: get_agent_records(redact_api_key=True))
app.include_router(web_ui_router)


@app.on_event("startup")
def check_elasticsearch_on_startup() -> None:
    if not getattr(elastic_store, "REQUIRE_ELASTIC", False):
        return
    result = elastic_store.check_connection(raise_on_error=True)
    print(
        "[ok] Elasticsearch connected "
        f"url={result.get('url')} cluster={result.get('cluster_name')} "
        f"status={result.get('cluster_status')}"
    )


def _append_event(evt: Dict[str, Any]) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(evt, ensure_ascii=False) + "\n")


def _append_detection(det: Dict[str, Any]) -> None:
    with DETECTIONS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(det, ensure_ascii=False) + "\n")
    elastic_store.index_detection(det)


def _get_detector() -> Optional[NgavDetector]:
    global _DETECTOR
    if _DETECTOR is not None:
        return _DETECTOR
    try:
        _DETECTOR = NgavDetector()
    except Exception as ex:
        print(f"[warn] NGAV detector unavailable: {ex}")
        return None
    return _DETECTOR


def _detect_event(evt: Dict[str, Any]) -> list:
    detector = _get_detector()
    if detector is None:
        return []
    try:
        detections = [det.to_dict() for det in detector.detect_event(evt)]
        for det in detections:
            _append_detection(det)
            try:
                handle_detection(det, event=evt)
            except Exception as ex:
                print(f"[warn] alert dispatch failed: {ex}")
        return detections
    except Exception as ex:
        print(f"[warn] NGAV detection failed: {ex}")
        return []


@app.post("/ingest")
async def ingest(event: AgentEvent, request: Request):
    # validate API key header
    api_key = None
    # prefer X-API-Key header
    if "x-api-key" in request.headers:
        api_key = request.headers.get("x-api-key")
    else:
        # allow Authorization: ApiKey <key>
        auth = request.headers.get("authorization")
        if auth and auth.lower().startswith("apikey "):
            api_key = auth.split(None, 1)[1].strip()

    if not api_key or api_key not in _KEYS:
        raise HTTPException(status_code=401, detail="missing or invalid api key")

    obj = event.dict()
    obj["received_ts"] = time.time()
    obj["id"] = str(uuid.uuid4())
    obj["remote_addr"] = request.client.host if request.client else None
    obj["api_key"] = api_key
    _touch_agent(api_key, obj["endpoint"], obj["remote_addr"], obj["event_type"])
    obj["detections"] = _detect_event(obj)
    try:
        _append_event(obj)
        elastic_store.index_event(obj)
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))
    return JSONResponse({"status": "ok", "id": obj["id"], "detections": obj["detections"]})



class AgentRegistration(BaseModel):
    endpoint: str
    api_key: Optional[str] = None
    os: Optional[str] = None
    os_name: Optional[str] = None
    os_version: Optional[str] = None
    hostname: Optional[str] = None
    machine: Optional[str] = None


class ConnectKeyRequest(BaseModel):
    endpoint: Optional[str] = "manual-agent"


@app.post("/register_agent")
def register_agent(reg: AgentRegistration, request: Request):
    # agent may provide its own api_key; otherwise server will generate one
    key = reg.api_key or secrets.token_urlsafe(32)
    remote_addr = request.client.host if request.client else None
    if key in _KEYS:
        # already registered
        _touch_agent(key, reg.endpoint, remote_addr, "register", metadata=reg.dict())
        return {"status": "exists", "api_key": key}

    rec = {
        "api_key": key,
        "endpoint": reg.endpoint,
        "os": reg.os,
        "os_name": reg.os_name,
        "os_version": reg.os_version,
        "hostname": reg.hostname,
        "machine": reg.machine,
        "created_ts": time.time(),
        "last_seen_ts": time.time(),
        "last_remote_addr": remote_addr,
        "last_event_type": "register",
    }
    try:
        _append_key(rec)
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))

    return {"status": "ok", "api_key": key}


@app.post("/api/agent/connect-key")
def create_connect_key(req: ConnectKeyRequest, request: Request):
    key = secrets.token_urlsafe(32)
    endpoint = (req.endpoint or "manual-agent").strip() or "manual-agent"
    rec = {
        "api_key": key,
        "endpoint": endpoint,
        "created_ts": time.time(),
        "last_seen_ts": None,
        "last_remote_addr": request.client.host if request.client else None,
        "last_event_type": "connect-key-created",
    }
    try:
        _append_key(rec)
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))
    return {"status": "ok", "endpoint": endpoint, "api_key": key}


@app.get("/agents")
def list_agents():
    return {"agents": get_agent_records(redact_api_key=True)}


def get_agent_records(redact_api_key: bool = True) -> List[Dict[str, Any]]:
    agents = []
    for rec in _KEYS.values():
        api_key = "[redacted]" if redact_api_key else rec.get("api_key")
        agents.append(
            {
                "endpoint": rec.get("endpoint"),
                "hostname": rec.get("hostname"),
                "os": rec.get("os"),
                "os_name": rec.get("os_name"),
                "os_version": rec.get("os_version"),
                "machine": rec.get("machine"),
                "created_ts": rec.get("created_ts"),
                "last_seen_ts": rec.get("last_seen_ts"),
                "last_remote_addr": rec.get("last_remote_addr"),
                "last_event_type": rec.get("last_event_type"),
                "api_key": api_key,
            }
        )
    agents.sort(key=lambda item: item.get("last_seen_ts") or 0, reverse=True)
    return agents


@app.get("/events")
def list_events(limit: int = 100):
    if not LOG_FILE.exists():
        return {"events": []}

    events = []
    try:
        with LOG_FILE.open("r", encoding="utf-8") as f:
            # naive tail: read last ~N lines
            lines = f.readlines()[-limit:]
            for ln in lines:
                try:
                    events.append(json.loads(ln))
                except Exception:
                    continue
    except Exception:
        raise HTTPException(status_code=500, detail="failed to read log file")

    return {"events": events}


@app.get("/detections")
def list_detections(limit: int = 100, anomalies_only: bool = False):
    if not DETECTIONS_FILE.exists():
        return {"detections": []}

    detections = []
    try:
        with DETECTIONS_FILE.open("r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
            for ln in lines:
                try:
                    det = json.loads(ln)
                except Exception:
                    continue
                if anomalies_only and not det.get("is_anomaly"):
                    continue
                detections.append(det)
    except Exception:
        raise HTTPException(status_code=500, detail="failed to read detections file")

    return {"detections": detections}


@app.get("/")
def read_root():
    return {"service": "ngav-collector", "status": "ok"}
