import os
import time
from typing import Any, Dict, List, Optional


EVENTS_INDEX = os.getenv("NGAV_ELASTIC_EVENTS_INDEX", "ngav-events")
DETECTIONS_INDEX = os.getenv("NGAV_ELASTIC_DETECTIONS_INDEX", "ngav-detections")
ALERTS_INDEX = os.getenv("NGAV_ELASTIC_ALERTS_INDEX", "ngav-alerts")
ELASTIC_URL = os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200")
ELASTIC_API_KEY = os.getenv("ELASTICSEARCH_API_KEY")
ELASTIC_USERNAME = os.getenv("ELASTICSEARCH_USERNAME")
ELASTIC_PASSWORD = os.getenv("ELASTICSEARCH_PASSWORD")

_CLIENT: Optional[Any] = None
_CLIENT_ERROR: Optional[str] = None


def get_client() -> Optional[Any]:
    global _CLIENT, _CLIENT_ERROR
    if _CLIENT is not None:
        return _CLIENT
    try:
        from elasticsearch import Elasticsearch
    except Exception as ex:
        _CLIENT_ERROR = f"elasticsearch package is not installed: {ex}"
        return None

    kwargs: Dict[str, Any] = {"request_timeout": 5}
    if ELASTIC_API_KEY:
        kwargs["api_key"] = ELASTIC_API_KEY
    elif ELASTIC_USERNAME:
        kwargs["basic_auth"] = (ELASTIC_USERNAME, ELASTIC_PASSWORD or "")

    try:
        client = Elasticsearch(ELASTIC_URL, **kwargs)
        if not client.ping():
            _CLIENT_ERROR = f"cannot connect to Elasticsearch at {ELASTIC_URL}"
            return None
        _CLIENT = client
        _ensure_indices(client)
        return _CLIENT
    except Exception as ex:
        _CLIENT_ERROR = str(ex)
        return None


def health() -> Dict[str, Any]:
    client = get_client()
    if client is None:
        return {"enabled": False, "url": ELASTIC_URL, "error": _CLIENT_ERROR}
    try:
        info = client.info()
        return {
            "enabled": True,
            "url": ELASTIC_URL,
            "cluster_name": info.get("cluster_name"),
            "version": (info.get("version") or {}).get("number"),
        }
    except Exception as ex:
        return {"enabled": False, "url": ELASTIC_URL, "error": str(ex)}


def index_event(event: Dict[str, Any]) -> None:
    index_document(EVENTS_INDEX, _redact_event(event), doc_id=event.get("id"))


def index_detection(detection: Dict[str, Any]) -> None:
    doc_id = _doc_id("detection", detection)
    index_document(DETECTIONS_INDEX, _with_index_ts(detection), doc_id=doc_id)


def index_alert(alert: Dict[str, Any]) -> None:
    doc_id = _doc_id("alert", alert)
    index_document(ALERTS_INDEX, _with_index_ts(alert), doc_id=doc_id)


def index_document(index: str, document: Dict[str, Any], doc_id: Optional[str] = None) -> None:
    client = get_client()
    if client is None:
        return
    try:
        client.index(index=index, id=doc_id, document=document)
    except Exception as ex:
        print(f"[warn] failed to index {index} document to Elasticsearch: {ex}")


def search_documents(index: str, limit: int = 100, query: Optional[str] = None) -> List[Dict[str, Any]]:
    client = get_client()
    if client is None:
        return []

    body: Dict[str, Any] = {
        "size": max(1, min(limit, 500)),
        "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "date"}}],
        "query": {"match_all": {}},
    }
    if query:
        body["query"] = {
            "query_string": {
                "query": query,
                "default_operator": "AND",
            }
        }

    try:
        result = client.search(index=index, **body)
    except Exception as ex:
        print(f"[warn] Elasticsearch search failed for {index}: {ex}")
        return []

    return [
        {"_id": hit.get("_id"), **(hit.get("_source") or {})}
        for hit in (result.get("hits") or {}).get("hits", [])
    ]


def stats() -> Dict[str, Any]:
    client = get_client()
    if client is None:
        return {"events": 0, "detections": 0, "alerts": 0}

    counts: Dict[str, int] = {}
    for name, index in {
        "events": EVENTS_INDEX,
        "detections": DETECTIONS_INDEX,
        "alerts": ALERTS_INDEX,
    }.items():
        try:
            counts[name] = int(client.count(index=index).get("count", 0))
        except Exception:
            counts[name] = 0
    return counts


def _ensure_indices(client: Any) -> None:
    for index in [EVENTS_INDEX, DETECTIONS_INDEX, ALERTS_INDEX]:
        try:
            if not client.indices.exists(index=index):
                client.indices.create(index=index, mappings={"properties": {"@timestamp": {"type": "date"}}})
        except Exception as ex:
            print(f"[warn] failed to ensure Elasticsearch index {index}: {ex}")


def _redact_event(event: Dict[str, Any]) -> Dict[str, Any]:
    safe = _with_index_ts(event)
    if "api_key" in safe:
        safe["api_key"] = "[redacted]"
    return safe


def _with_index_ts(document: Dict[str, Any]) -> Dict[str, Any]:
    copied = dict(document)
    ts = copied.get("received_ts") or copied.get("created_ts") or copied.get("timestamp") or time.time()
    copied["@timestamp"] = _epoch_to_iso(ts)
    return copied


def _epoch_to_iso(value: Any) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def _doc_id(prefix: str, document: Dict[str, Any]) -> Optional[str]:
    event_id = document.get("event_id")
    model_name = document.get("model_name") or document.get("engine")
    score = document.get("score")
    if event_id and model_name is not None:
        return f"{prefix}:{event_id}:{model_name}:{score}"
    return None
