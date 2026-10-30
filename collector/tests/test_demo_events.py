"""Fixture integrity tests: the demo fixture validates and stays privacy-safe."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from backend.app.schemas.base import EVENT_KINDS
from backend.app.schemas.source import SourceEvent
from collector.demo_events import FIXTURE_PATH, build_events, load_fixture


def test_fixture_exists_and_loads():
    fixture = load_fixture()
    assert fixture["source"] == "synthetic"
    assert fixture["events"], "fixture must contain events"


def test_fixture_events_validate_against_source_schema():
    fixture = load_fixture()
    events = build_events(fixture, base_time=datetime(2026, 1, 1, tzinfo=UTC))
    for event in events:
        assert isinstance(event, SourceEvent)
        assert event.kind in EVENT_KINDS


def test_fixture_is_marked_synthetic():
    fixture = load_fixture()
    assert fixture["source"] == "synthetic"
    assert fixture["machine_id"] == "synthetic-demo-machine"


def test_fresh_event_ids_per_publish():
    fixture = load_fixture()
    first = [e.event_id for e in build_events(fixture, base_time=datetime(2026, 1, 1, tzinfo=UTC))]
    second = [e.event_id for e in build_events(fixture, base_time=datetime(2026, 1, 1, tzinfo=UTC))]
    assert first
    assert set(first).isdisjoint(second)


def test_rejections_in_kind_names_are_absent():
    raw = FIXTURE_PATH.read_text(encoding="utf-8")
    for secret_marker in ("password", "source-content", "TODO_USER_CONTENT"):
        assert secret_marker not in raw


def test_repetitions_stay_bounded():
    fixture = load_fixture()
    events = build_events(fixture, repetitions=2)
    assert len(events) == 2 * len(fixture["events"])


def test_private_keys_never_in_fixture():
    raw = FIXTURE_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    for fixture_event in data["events"]:
        for value in fixture_event.get("summary", {}).values():
            assert not value.startswith("/")  # absolute paths are discouraged
