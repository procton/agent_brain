"""Explicitly synthetic demo events.

`observatory demo-publish` converts this fixture into sanitized source events
and writes them through the REAL spool; the REAL collector then delivers them
to the backend. Nothing ever publishes to the dashboard directly.

No Claude Code installation is required. Events carry:
- fresh UUIDs per publish (so re-publishing never counts as duplicates)
- `recorded_at` stamps spaced `offset_ms` apart, likely in the past
- session/session id from the fixture, so repeated publishes append to the
  same demo session unless `--per-publish-session` is given
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.app.schemas.source import SourceEvent

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic" / "demo_session.json"


def load_fixture(path: Path = FIXTURE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_events(
    fixture: dict,
    *,
    base_time: datetime | None = None,
    session_id: str | None = None,
    repetitions: int = 1,
) -> list[SourceEvent]:
    """Materialize `repetitions` passes over the fixture as fresh events.

    Each repetition starts `12 s` after the previous one so timestamps show a
    plausible old sequence without ever colliding.
    """
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    sid = session_id or fixture["session_id"]
    base = base_time or datetime.now(UTC)
    events: list[SourceEvent] = []
    for repetition_index in range(repetitions):
        repeat_base = base + timedelta(milliseconds=repetition_index * 12_000)
        for fixture_event in fixture["events"]:
            occurred = repeat_base + timedelta(
                milliseconds=fixture_event["offset_ms"] - 1200
            )
            events.append(
                SourceEvent(
                    event_id=str(uuid.uuid4()),
                    machine_id=fixture["machine_id"],
                    session_id=sid,
                    source=fixture["source"],
                    source_event=fixture_event["source_event"],
                    kind=fixture_event["kind"],
                    occurred_at=occurred.isoformat(timespec="milliseconds"),
                    recorded_at=occurred.isoformat(timespec="milliseconds"),
                    correlation=fixture_event.get("correlation", {}) or {},
                    summary={
                        **fixture_event.get("summary", {}),
                        "project": fixture["project"]["label"],
                    },
                )
            )
    return events


def to_row(event: SourceEvent) -> dict:
    return event.model_dump(mode="json")
