"""Single-process project snapshots plus a replayable append-only event log."""
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from backend.core.runtime import atomic_replace
from contracts.models import EventPage, ProjectEvent, ProjectSnapshot, ProjectSummary
from contracts.validation import artifact_path, canonical_json


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, project_id: str) -> asyncio.Lock:
        self.directory(project_id)  # Validate before using the ID as a key.
        return self._locks.setdefault(project_id, asyncio.Lock())

    def directory(self, project_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", project_id):
            raise KeyError(project_id)
        return artifact_path(self.root, f"projects/{project_id}")

    def get(self, project_id: str) -> ProjectSnapshot:
        path = self.directory(project_id) / "snapshot.json"
        if not path.is_file():
            raise KeyError(project_id)
        return ProjectSnapshot.model_validate_json(path.read_bytes())

    def events(self, project_id: str, after: int = 0) -> EventPage:
        self.get(project_id)
        path = self.directory(project_id) / "events.jsonl"
        rows = []
        if path.exists():
            for line in path.read_text().splitlines():
                try:
                    event = ProjectEvent.model_validate_json(line)
                except ValueError:
                    # A process kill can leave only the final line truncated.
                    continue
                if event.event_id > after:
                    rows.append(event)
        return EventPage(events=rows, next_after=rows[-1].event_id if rows else after)

    def list(self) -> list[ProjectSummary]:
        result = []
        for path in (self.root / "projects").glob("*/snapshot.json"):
            snapshot = ProjectSnapshot.model_validate_json(path.read_bytes())
            result.append(ProjectSummary(project_id=snapshot.project_id, topic=snapshot.topic,
                                         status=snapshot.status, mode=snapshot.mode, updated_at=snapshot.updated_at))
        return sorted(result, key=lambda item: item.updated_at, reverse=True)

    def save(self, snapshot: ProjectSnapshot, event_type: str, message: str, *,
             scene_id: str | None = None, revision: int | None = None,
             progress: float | None = None) -> ProjectSnapshot:
        """Caller holds lock (or is creating a unique project).

        A small write-ahead transaction makes a crash between event/snapshot writes
        recoverable. It contains no extra wire fields or provider secrets.
        """
        directory = self.directory(snapshot.project_id)
        directory.mkdir(parents=True, exist_ok=True)
        snapshot.updated_at = utc_now()
        snapshot = ProjectSnapshot.model_validate(snapshot.model_dump(mode="json"))
        event_id = self.events(snapshot.project_id).next_after + 1 if (directory / "snapshot.json").exists() else 1
        event = ProjectEvent(project_id=snapshot.project_id, event_id=event_id, at=snapshot.updated_at,
                             type=event_type, message=message, scene_id=scene_id, revision=revision, progress=progress)
        atomic_replace(directory / "transaction.json", canonical_json({
            "snapshot": snapshot.model_dump(mode="json"), "event": event.model_dump(mode="json")}))
        self._apply(directory, snapshot, event)
        (directory / "transaction.json").unlink(missing_ok=True)
        return snapshot

    def _apply(self, directory: Path, snapshot: ProjectSnapshot, event: ProjectEvent) -> None:
        log = directory / "events.jsonl"
        existing = log.read_bytes() if log.exists() else b""
        valid_lines = []
        ids = set()
        for line in existing.splitlines():
            try:
                parsed = ProjectEvent.model_validate_json(line)
                valid_lines.append(line)
                ids.add(parsed.event_id)
            except ValueError:
                continue
        # Recovery alone may need to remove a truncated final line. Normal saves append.
        clean = b"\n".join(valid_lines) + (b"\n" if valid_lines else b"")
        if clean != existing:
            atomic_replace(log, clean)
        if event.event_id not in ids:
            import os
            with log.open("ab") as stream:
                stream.write(canonical_json(event) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
        atomic_replace(directory / "snapshot.json", canonical_json(snapshot))

    async def update(self, project_id: str, mutate: Callable[[ProjectSnapshot], None],
                     event_type: str, message: str, **event_fields) -> ProjectSnapshot:
        async with self.lock(project_id):
            snapshot = self.get(project_id)
            mutate(snapshot)
            return self.save(snapshot, event_type, message, **event_fields)

    def recover(self) -> None:
        for transaction in (self.root / "projects").glob("*/transaction.json"):
            data = json.loads(transaction.read_bytes())
            self._apply(transaction.parent, ProjectSnapshot.model_validate(data["snapshot"]),
                        ProjectEvent.model_validate(data["event"]))
            transaction.unlink()
