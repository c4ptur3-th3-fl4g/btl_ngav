from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, Iterator, Optional

import psutil


@dataclass(frozen=True)
class ProcessSnapshot:
	pid: int
	ppid: int
	name: str
	exe: str
	username: str
	status: str
	cmdline: str
	create_time: float


@dataclass(frozen=True)
class ProcessEvent:
	event_type: str
	snapshot: ProcessSnapshot
	previous_snapshot: Optional[ProcessSnapshot] = None


def safe(callable_obj, default=None):
	try:
		return callable_obj()
	except Exception:
		return default


def capture_snapshot(proc: psutil.Process) -> Optional[ProcessSnapshot]:
	with proc.oneshot():
		pid = proc.pid
		ppid = safe(proc.ppid, -1)
		name = (safe(proc.name, "") or "").strip()
		exe = (safe(proc.exe, "") or "").strip()
		username = (safe(proc.username, "") or "").strip()
		status = safe(proc.status, "unknown") or "unknown"
		cmdline = " ".join(safe(proc.cmdline, []) or [])
		create_time = float(safe(proc.create_time, 0.0) or 0.0)

	return ProcessSnapshot(
		pid=pid,
		ppid=ppid,
		name=name,
		exe=exe,
		username=username,
		status=status,
		cmdline=cmdline,
		create_time=create_time,
	)


def scan_processes() -> Dict[int, ProcessSnapshot]:
	snapshots: Dict[int, ProcessSnapshot] = {}
	for proc in psutil.process_iter():
		snapshot = safe(lambda: capture_snapshot(proc))
		if snapshot is not None:
			snapshots[snapshot.pid] = snapshot
	return snapshots


def diff_process_state(
	previous: Dict[int, ProcessSnapshot], current: Dict[int, ProcessSnapshot]
) -> Iterator[ProcessEvent]:
	previous_pids = set(previous)
	current_pids = set(current)

	for pid in sorted(current_pids - previous_pids):
		yield ProcessEvent(event_type="started", snapshot=current[pid])

	for pid in sorted(previous_pids - current_pids):
		yield ProcessEvent(event_type="stopped", snapshot=previous[pid])

	for pid in sorted(previous_pids & current_pids):
		before = previous[pid]
		after = current[pid]
		if before != after:
			yield ProcessEvent(event_type="updated", snapshot=after, previous_snapshot=before)


def format_event(event: ProcessEvent) -> str:
	snapshot = event.snapshot
	timestamp = datetime.now(timezone.utc).isoformat()
	base = (
		f"[{timestamp}] {event.event_type.upper()} pid={snapshot.pid} "
		f"ppid={snapshot.ppid} name={snapshot.name!r} exe={snapshot.exe!r} "
		f"user={snapshot.username!r} status={snapshot.status!r}"
	)
	if event.event_type == "updated" and event.previous_snapshot is not None:
		return base + f" previous_status={event.previous_snapshot.status!r}"
	return base


def watch_processes(
	interval_seconds: float = 1.0,
	on_event: Optional[Callable[[ProcessEvent], None]] = None,
) -> None:
	previous = scan_processes()
	print(f"[info] Monitoring {len(previous)} existing processes every {interval_seconds:.1f}s")

	while True:
		time.sleep(interval_seconds)
		current = scan_processes()
		for event in diff_process_state(previous, current):
			if on_event is None:
				print(format_event(event))
			else:
				on_event(event)
		previous = current


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Realtime process monitor")
	parser.add_argument("--interval", type=float, default=1.0, help="Polling interval in seconds")
	return parser.parse_args()


def main() -> None:
	args = parse_args()
	watch_processes(interval_seconds=args.interval)


if __name__ == "__main__":
	main()