import base64
import json
import os
import time
from typing import Any, Dict, List, Optional
from urllib import error, request


EVENTS_INDEX = os.getenv("NGAV_ELASTIC_EVENTS_INDEX", "ngav-events")
DETECTIONS_INDEX = os.getenv("NGAV_ELASTIC_DETECTIONS_INDEX", "ngav-detections")
ALERTS_INDEX = os.getenv("NGAV_ELASTIC_ALERTS_INDEX", "ngav-alerts")
ELASTIC_URL = os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200")
ELASTIC_API_KEY = os.getenv("ELASTICSEARCH_API_KEY")
ELASTIC_USERNAME = os.getenv("ELASTICSEARCH_USERNAME")
ELASTIC_PASSWORD = os.getenv("ELASTICSEARCH_PASSWORD")
REQUIRE_ELASTIC = os.getenv("NGAV_REQUIRE_ELASTIC", "0").strip().lower() in {"1", "true", "yes", "on"}

_CLIENT: Optional[Any] = None
_CLIENT_ERROR: Optional[str] = None
_ACTIVE_ELASTIC_URL: str = ELASTIC_URL


def get_client() -> Optional[Any]:
    global _CLIENT, _CLIENT_ERROR, _ACTIVE_ELASTIC_URL
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

    errors: List[str] = []
    for url in _candidate_urls():
        try:
            client = Elasticsearch(url, **kwargs)
            if not _is_reachable(client):
                errors.append(f"cannot connect to Elasticsearch at {url}")
                continue
            _CLIENT = client
            _ACTIVE_ELASTIC_URL = url
            _ensure_indices(client)
            return _CLIENT
        except Exception as ex:
            errors.append(f"{url}: {ex}")

    _CLIENT_ERROR = "; ".join(errors) if errors else f"cannot connect to Elasticsearch at {ELASTIC_URL}"
    return None


def health() -> Dict[str, Any]:
    client = get_client()
    if client is None:
        raw_health = _raw_http_health()
        if raw_health is not None:
            return raw_health
        return _offline_health(_CLIENT_ERROR)
    try:
        info = client.info()
        cluster = client.cluster.health()
        return {
            "enabled": True,
            "url": _ACTIVE_ELASTIC_URL,
            "cluster_name": info.get("cluster_name"),
            "version": (info.get("version") or {}).get("number"),
            "cluster_status": cluster.get("status"),
            "active_shards": cluster.get("active_shards"),
            "unassigned_shards": cluster.get("unassigned_shards"),
            "client_connected": True,
            "connection_mode": "elasticsearch-client",
        }
    except Exception as ex:
        raw_health = _raw_http_health()
        if raw_health is not None:
            raw_health["client_error"] = str(ex)
            return raw_health
        return _offline_health(str(ex), url=_ACTIVE_ELASTIC_URL)


def check_connection(raise_on_error: bool = False) -> Dict[str, Any]:
    result = health()
    if result.get("enabled"):
        return result

    message = (
        "Elasticsearch connection failed. "
        f"configured_url={ELASTIC_URL}; "
        f"tried_urls={', '.join(_candidate_urls())}; "
        f"reason={result.get('error') or 'unknown'}"
    )
    if raise_on_error:
        raise RuntimeError(message)
    result["message"] = message
    return result


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
    if client is not None:
        try:
            client.index(index=index, id=doc_id, document=document)
            return
        except Exception as ex:
            print(f"[warn] failed to index {index} document with Elasticsearch client: {ex}")
    try:
        _raw_index_document(index, document, doc_id=doc_id)
    except Exception as ex:
        print(f"[warn] failed to index {index} document to Elasticsearch: {ex}")


def search_documents(index: str, limit: int = 100, query: Optional[str] = None) -> List[Dict[str, Any]]:
    client = get_client()
    if client is None:
        return _raw_search_documents(index, limit=limit, query=query)

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
        print(f"[warn] Elasticsearch client search failed for {index}: {ex}")
        return _raw_search_documents(index, limit=limit, query=query)

    return [
        {"_id": hit.get("_id"), **(hit.get("_source") or {})}
        for hit in (result.get("hits") or {}).get("hits", [])
    ]


def stats() -> Dict[str, Any]:
    client = get_client()
    counts: Dict[str, int] = {}
    for name, index in {
        "events": EVENTS_INDEX,
        "detections": DETECTIONS_INDEX,
        "alerts": ALERTS_INDEX,
    }.items():
        if client is None:
            counts[name] = _raw_count(index)
            continue
        try:
            counts[name] = int(client.count(index=index).get("count", 0))
        except Exception:
            counts[name] = _raw_count(index)
    return counts


def _ensure_indices(client: Any) -> None:
    for index in [EVENTS_INDEX, DETECTIONS_INDEX, ALERTS_INDEX]:
        try:
            if not client.indices.exists(index=index):
                client.indices.create(
                    index=index,
                    settings={"number_of_shards": 1, "number_of_replicas": 0},
                    mappings={"properties": {"@timestamp": {"type": "date"}}},
                )
            else:
                client.indices.put_settings(index=index, settings={"number_of_replicas": 0})
        except Exception as ex:
            print(f"[warn] failed to ensure Elasticsearch index {index}: {ex}")


def _candidate_urls() -> List[str]:
    urls = [ELASTIC_URL]
    if "localhost" in ELASTIC_URL:
        urls.append(ELASTIC_URL.replace("localhost", "127.0.0.1"))
    elif "127.0.0.1" in ELASTIC_URL:
        urls.append(ELASTIC_URL.replace("127.0.0.1", "localhost"))
    urls.extend(["http://127.0.0.1:9200", "http://localhost:9200"])
    return list(dict.fromkeys(urls))


def _offline_health(error_message: Optional[str], url: Optional[str] = None) -> Dict[str, Any]:
    return {
        "enabled": False,
        "url": url or ELASTIC_URL,
        "tried_urls": _candidate_urls(),
        "error": error_message,
        "hint": "Elasticsearch is not reachable from the NGAV collector process. Check systemd env, bind address, firewall, proxy, and service status.",
    }


def _raw_http_health() -> Optional[Dict[str, Any]]:
    global _ACTIVE_ELASTIC_URL
    errors: List[str] = []
    for url in _candidate_urls():
        try:
            info = _http_json(url, "/")
            cluster = _http_json(url, "/_cluster/health")
            _ACTIVE_ELASTIC_URL = url
            return {
                "enabled": True,
                "url": url,
                "cluster_name": info.get("cluster_name"),
                "version": (info.get("version") or {}).get("number"),
                "cluster_status": cluster.get("status"),
                "active_shards": cluster.get("active_shards"),
                "unassigned_shards": cluster.get("unassigned_shards"),
                "client_connected": False,
                "connection_mode": "raw-http",
                "client_error": _CLIENT_ERROR,
            }
        except Exception as ex:
            errors.append(f"{url}: {ex}")

    if errors:
        print(f"[warn] raw Elasticsearch HTTP health failed: {'; '.join(errors)}")
    return None


def _http_json(base_url: str, path: str) -> Dict[str, Any]:
    url = base_url.rstrip("/") + path
    req = request.Request(url, headers=_http_headers(), method="GET")
    opener = request.build_opener(request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=5) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as ex:
        body = ex.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {ex.code}: {body[:300]}") from ex
    return json.loads(body)


def _http_request_json(base_url: str, path: str, method: str = "GET", body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = base_url.rstrip("/") + path
    data = None
    headers = _http_headers()
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    opener = request.build_opener(request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=5) as response:
            response_body = response.read().decode("utf-8")
    except error.HTTPError as ex:
        response_body = ex.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {ex.code}: {response_body[:300]}") from ex
    if not response_body:
        return {}
    return json.loads(response_body)


def _raw_index_document(index: str, document: Dict[str, Any], doc_id: Optional[str] = None) -> None:
    method = "PUT" if doc_id else "POST"
    path = f"/{index}/_doc/{doc_id}" if doc_id else f"/{index}/_doc"
    _http_request_json(_ACTIVE_ELASTIC_URL, path, method=method, body=document)


def _raw_search_documents(index: str, limit: int = 100, query: Optional[str] = None) -> List[Dict[str, Any]]:
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
        result = _http_request_json(_ACTIVE_ELASTIC_URL, f"/{index}/_search", method="POST", body=body)
    except Exception as ex:
        print(f"[warn] raw Elasticsearch search failed for {index}: {ex}")
        return []
    return [
        {"_id": hit.get("_id"), **(hit.get("_source") or {})}
        for hit in (result.get("hits") or {}).get("hits", [])
    ]


def _raw_count(index: str) -> int:
    try:
        result = _http_request_json(_ACTIVE_ELASTIC_URL, f"/{index}/_count")
        return int(result.get("count", 0))
    except Exception as ex:
        print(f"[warn] raw Elasticsearch count failed for {index}: {ex}")
        return 0


def _http_headers() -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    if ELASTIC_API_KEY:
        headers["Authorization"] = f"ApiKey {ELASTIC_API_KEY}"
    elif ELASTIC_USERNAME:
        raw = f"{ELASTIC_USERNAME}:{ELASTIC_PASSWORD or ''}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    return headers


def _is_reachable(client: Any) -> bool:
    try:
        if client.ping():
            return True
    except Exception:
        pass
    try:
        client.info()
        return True
    except Exception:
        return False


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
