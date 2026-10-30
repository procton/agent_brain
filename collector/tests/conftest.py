"""Collector test fixtures."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from collector.spool import Spool


@pytest.fixture
def spool_dir(tmp_path):
    return tmp_path / "spool"


@pytest.fixture
def spool(spool_dir):
    return Spool(spool_dir)


def make_source_event(
    event_id: str | None = None,
    *,
    session_id: str = "synthetic-demo-0001",
    kind: str = "tool.requested",
    source_event: str = "PreToolUse",
    tool: str = "Read",
    target: str = "README.md",
    index: int = 0,
) -> dict:
    base = datetime(2026, 10, 29, 10, 0, 0, tzinfo=UTC) + timedelta(seconds=index)
    return {
        "schema_version": 1,
        "event_id": event_id or str(uuid.uuid4()),
        "machine_id": "test-machine",
        "session_id": session_id,
        "source": "synthetic",
        "source_event": source_event,
        "kind": kind,
        "occurred_at": base.isoformat(timespec="milliseconds"),
        "recorded_at": base.isoformat(timespec="milliseconds"),
        "correlation": {"tool_call_id": f"call-{index:04d}"},
        "summary": {"tool": tool, "target": target, "project": "demo"},
    }


def force_older_names(spool: Spool, entries: list, shift: int = 1_000_000) -> None:
    """Rename published entries so they sort before a just-published one."""
    for entry in entries:
        broken = entry.parent / f"{max(0, int(entry.name.split('-')[0]) - shift)}-{entry.name}"
        entry.rename(broken)
