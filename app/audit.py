"""Minimal, privacy-preserving audit event recording."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class AuditEvent:
    timestamp: str
    action: str
    decision: str
    request_id: str
    actor: str | None = None
    resource: str | None = None


class AuditSink(Protocol):
    def record(self, event: AuditEvent) -> None: ...


class InMemoryAuditSink:
    """Non-persistent sink reserved for tests and local development."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


class JsonlAuditSink:
    """Append-only JSONL audit sink for request stream tracking and external SIEM ingestion.

    Security & Integrity Boundaries:
    1. Tamper-Resistance Boundary: This JSONL audit file is NOT inherently tamper-proof merely
       because entries are appended. Privileged host processes or storage administrators can alter,
       truncate, or delete local flat files. True non-repudiation requires immutable write-once media (WORM),
       filesystem immutable flags (e.g. Linux 'chattr +a'), or real-time remote SIEM log forwarding.
    2. Fail-Closed Error Policy: Logging failures (disk full, permission denials, I/O errors) raise an
       exception immediately and are NEVER silently caught or bypassed.
    3. Transactional Isolation: This sink operates outside SQLite ACID transaction boundaries. It does not
       participate in SQLite rollback. If a database transaction rolls back, database rows are undone, while
       filesystem JSONL append events remain preserved for post-incident forensic investigation.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._lock = threading.Lock()

    def record(self, event: AuditEvent) -> None:
        line = json.dumps(asdict(event), separators=(",", ":")) + "\n"
        with self._lock, self._path.open("a", encoding="utf-8") as audit_file:
            audit_file.write(line)


def new_event(
    action: str, decision: str, request_id: str, actor: str | None = None, resource: str | None = None
) -> AuditEvent:
    return AuditEvent(
        timestamp=datetime.now(timezone.utc).isoformat(),
        action=action,
        decision=decision,
        request_id=request_id,
        actor=actor,
        resource=resource,
    )
