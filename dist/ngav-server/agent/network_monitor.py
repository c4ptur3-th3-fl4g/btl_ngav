"""Simple cross-platform network monitor using psutil.

Provides sampling of interface IO and a polling `watch_network` helper that
emits per-interface bandwidth deltas (bytes/sec). Designed to run in a
background thread inside the agent.
"""
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Any

import psutil


@dataclass
class NetworkSample:
    timestamp: float
    interfaces: Dict[str, Dict[str, float]]  # iface -> metrics


def sample_interfaces() -> Dict[str, Any]:
    """Return the raw psutil.net_io_counters(pernic=True) mapping."""
    try:
        return psutil.net_io_counters(pernic=True)
    except Exception:
        return {}


def _compute_deltas(prev, cur, interval: float) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for iface, curv in cur.items():
        prevv = prev.get(iface)
        if prevv is None:
            # cannot compute delta for new iface
            continue
        sent_delta = (curv.bytes_sent - prevv.bytes_sent) / interval
        recv_delta = (curv.bytes_recv - prevv.bytes_recv) / interval
        out[iface] = {
            "bytes_sent_per_sec": float(max(0.0, sent_delta)),
            "bytes_recv_per_sec": float(max(0.0, recv_delta)),
            "bytes_sent": float(curv.bytes_sent),
            "bytes_recv": float(curv.bytes_recv),
        }
    return out


def watch_network(interval_seconds: float = 1.0, on_sample: Optional[Callable[[NetworkSample], None]] = None) -> None:
    """Continuously sample network interfaces and call `on_sample` with deltas.

    `on_sample` receives a `NetworkSample` dataclass.
    """
    prev = sample_interfaces()
    if on_sample is None:
        def _print(sample: NetworkSample):
            print(f"[netmon] {sample.timestamp}: interfaces={list(sample.interfaces.keys())}")

        on_sample = _print

    while True:
        try:
            time.sleep(interval_seconds)
            cur = sample_interfaces()
            deltas = _compute_deltas(prev, cur, max(1e-6, interval_seconds))
            sample = NetworkSample(timestamp=time.time(), interfaces=deltas)
            try:
                on_sample(sample)
            except Exception:
                pass
            prev = cur
        except KeyboardInterrupt:
            break
        except Exception:
            # swallow and retry
            time.sleep(interval_seconds)
