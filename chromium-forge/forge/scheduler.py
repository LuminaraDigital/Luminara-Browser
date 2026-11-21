"""Scheduled goals: run a saved co-browsing goal every N minutes or daily at a local time.

`ScheduledTaskStore` persists tasks as one private JSON file; `ScheduleRunner` is the daemon
thread that fires whatever is due. Each run goes through the normal goal runner, so login gates,
the mutation firewall and the action ledger apply exactly as they do to an interactive goal.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import secrets
import threading
from typing import Any

from .http_base import atomic_write_private

MIN_INTERVAL_MIN = 5
MAX_TASKS = 50
_DAILY_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def parse_schedule(kind: str, *, every_min: int | None = None, at: str | None = None) -> dict[str, Any]:
    """Validate a schedule and return its canonical form."""
    if kind == "interval":
        if isinstance(every_min, bool) or not isinstance(every_min, int) or not MIN_INTERVAL_MIN <= every_min <= 7 * 24 * 60:
            raise ValueError(f"interval schedules need every_min between {MIN_INTERVAL_MIN} and 10080")
        return {"kind": "interval", "every_min": every_min}
    if kind == "daily":
        if not isinstance(at, str) or not _DAILY_RE.match(at):
            raise ValueError("daily schedules need at='HH:MM' (24-hour local time)")
        return {"kind": "daily", "at": at}
    raise ValueError(f"Unsupported schedule kind {kind!r}: use 'interval' or 'daily'")


def next_run_after(schedule: dict[str, Any], now: datetime) -> datetime:
    """First run time strictly after `now`."""
    if schedule["kind"] == "interval":
        return now + timedelta(minutes=int(schedule["every_min"]))
    hour, minute = (int(part) for part in str(schedule["at"]).split(":"))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


class ScheduledTaskStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                self._tasks = {str(t["id"]): t for t in loaded if isinstance(t, dict) and t.get("id")}
            except (OSError, ValueError, TypeError, KeyError):
                self._tasks = {}

    def _save(self) -> None:
        atomic_write_private(self.path, json.dumps(list(self._tasks.values()), indent=2))

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(t) for t in self._tasks.values()]

    def add(self, goal: str, schedule: dict[str, Any], *, start_url: str = "", max_steps: int = 8, now: datetime | None = None) -> dict[str, Any]:
        with self._lock:
            if len(self._tasks) >= MAX_TASKS:
                raise ValueError(f"At most {MAX_TASKS} scheduled tasks are allowed")
            task = {
                "id": f"sched_{secrets.token_hex(5)}",
                "goal": goal,
                "start_url": start_url,
                "max_steps": max(1, min(15, int(max_steps))),
                "schedule": schedule,
                "enabled": True,
                "next_run": next_run_after(schedule, now or datetime.now()).isoformat(timespec="seconds"),
                "last_run": "",
                "last_status": "",
            }
            self._tasks[task["id"]] = task
            self._save()
            return dict(task)

    def _require(self, task_id: str) -> dict[str, Any]:
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Unknown scheduled task: {task_id!r}")
        return task

    def remove(self, task_id: str) -> None:
        with self._lock:
            self._require(task_id)
            del self._tasks[task_id]
            self._save()

    def set_enabled(self, task_id: str, enabled: bool, *, now: datetime | None = None) -> dict[str, Any]:
        with self._lock:
            task = self._require(task_id)
            task["enabled"] = enabled
            if enabled:
                task["next_run"] = next_run_after(task["schedule"], now or datetime.now()).isoformat(timespec="seconds")
            self._save()
            return dict(task)

    def get(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._require(task_id))

    def claim_due(self, now: datetime) -> list[dict[str, Any]]:
        """Return due tasks and advance their `next_run` first, so a crash mid-run cannot re-fire them in a loop."""
        with self._lock:
            due = [t for t in self._tasks.values() if t["enabled"] and datetime.fromisoformat(t["next_run"]) <= now]
            for task in due:
                task["next_run"] = next_run_after(task["schedule"], now).isoformat(timespec="seconds")
            if due:
                self._save()
            return [dict(t) for t in due]

    def mark_ran(self, task_id: str, status: str, now: datetime) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:  # removed while it was running
                return
            task["last_run"] = now.isoformat(timespec="seconds")
            task["last_status"] = status[:80]
            self._save()


class ScheduleRunner:
    """Fires due tasks one at a time on a daemon thread."""

    def __init__(
        self,
        store: ScheduledTaskStore,
        run_task: Callable[[dict[str, Any]], str],
        *,
        tick_sec: float = 30.0,
        on_tick: Callable[[], None] | None = None,
    ) -> None:
        self.store = store
        self._run_task = run_task
        self._tick_sec = tick_sec
        self._on_tick = on_tick
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_one(self, task: dict[str, Any], now: datetime | None = None) -> str:
        try:
            status = self._run_task(task)
        except Exception as exc:  # noqa: BLE001 - one failing goal must not stop the schedule
            status = f"ERROR: {type(exc).__name__}"
        self.store.mark_ran(task["id"], status, now or datetime.now())
        return status

    def run_due(self, now: datetime | None = None) -> list[tuple[str, str]]:
        moment = now or datetime.now()
        return [(task["id"], self.run_one(task, moment)) for task in self.store.claim_due(moment)]

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="luminara-scheduler", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self._tick_sec):
            self.run_due()
            if self._on_tick is not None:
                try:
                    self._on_tick()
                except Exception:  # noqa: BLE001
                    pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
