"""Realtime file monitor.

Provides a lightweight, dependency-free polling watcher for paths that
emits file events: created, modified, deleted. Optionally uses
`watchdog` if available for lower-latency events.

API:
 - FileEvent(dataclass): event_type in {'created','modified','deleted'} and path, src_path, stat
 - watch_paths(paths, interval_seconds, on_event)

This module is intentionally simple and cross-platform.
"""
from dataclasses import dataclass
import os
import time
from typing import Callable, Dict, Iterable, List, Optional


@dataclass
class FileEvent:
	event_type: str  # 'created' | 'modified' | 'deleted'
	path: str
	src_path: Optional[str] = None
	stat: Optional[os.stat_result] = None


def _scan_paths(paths: Iterable[str]) -> Dict[str, float]:
	"""Return a mapping path -> mtime for all files under the given paths.

	Paths may be files or directories; directories are scanned recursively.
	"""
	result: Dict[str, float] = {}
	for p in paths:
		p = os.path.abspath(os.path.expanduser(p))
		if os.path.isfile(p):
			try:
				st = os.stat(p)
				result[p] = st.st_mtime
			except Exception:
				continue
		elif os.path.isdir(p):
			for root, _, files in os.walk(p):
				for fn in files:
					fp = os.path.join(root, fn)
					try:
						st = os.stat(fp)
						result[fp] = st.st_mtime
					except Exception:
						continue
		else:
			# path does not exist yet; ignore
			continue
	return result


def _diff_file_state(prev: Dict[str, float], cur: Dict[str, float]):
	# detect created
	for path, mtime in cur.items():
		if path not in prev:
			yield FileEvent(event_type="created", path=path)
		else:
			if mtime != prev[path]:
				yield FileEvent(event_type="modified", path=path)

	# detect deleted
	for path in prev:
		if path not in cur:
			yield FileEvent(event_type="deleted", path=path)


def watch_paths(paths: List[str], interval_seconds: float = 1.0, on_event: Optional[Callable[[FileEvent], None]] = None) -> None:
	"""Continuously watch `paths` and call `on_event` for each FileEvent.

	This function blocks until interrupted. It is intended to be run in
	a dedicated thread when used from a long-running agent.
	"""
	prev = _scan_paths(paths)
	if on_event is None:
		def _print(ev: FileEvent):
			print(f"[filemon] {ev.event_type}: {ev.path}")

		on_event = _print

	while True:
		try:
			time.sleep(interval_seconds)
			cur = _scan_paths(paths)
			for ev in _diff_file_state(prev, cur):
				try:
					on_event(ev)
				except Exception:
					# swallow exceptions from callbacks to keep watcher running
					pass
			prev = cur
		except KeyboardInterrupt:
			break
		except Exception:
			# keep running on transient errors
			time.sleep(interval_seconds)

