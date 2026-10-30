"""Unit tests for atomic spool publication, limits, quarantine."""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

from collector.spool import SpoolLimits
from collector.tests.conftest import make_source_event


def test_publish_is_atomic_and_readable(spool):
    path = spool.publish(
        make_source_event(event_id="11111111-1111-1111-1111-111111111111"),
        event_id="11111111-1111-1111-1111-111111111111",
    )
    assert path.exists()
    assert json.loads(path.read_text())["event_id"] == "11111111-1111-1111-1111-111111111111"
    # no leftover temp files in pending
    leftovers = [p for p in spool.pending_entries() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_publish_fifty_from_concurrent_threads_leaves_matching_files(spool):
    def publish_one(index: int) -> str:
        event_id = str(uuid.uuid4())
        spool.publish(make_source_event(event_id=event_id, index=index), event_id=event_id)
        return event_id

    event_ids = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(publish_one, i) for i in range(50)]
        for future in futures:
            event_ids.append(future.result())
    entries = spool.pending_entries()
    assert len(entries) == 50
    on_disk_ids = {json.loads(p.read_text())["event_id"] for p in entries}
    assert on_disk_ids == set(event_ids)


def test_pending_entries_are_publication_ordered(spool):
    for i in range(20):
        spool.publish(make_source_event(index=i), event_id=str(uuid.uuid4()))
    entries = spool.pending_entries()
    names = [p.name for p in entries]
    assert names == sorted(names)


def test_delete_entry_removes_file(spool):
    event_id = "22222222-2222-2222-2222-222222222222"
    path = spool.publish(make_source_event(event_id=event_id), event_id=event_id)
    spool.delete_entry(path)
    assert not path.exists()
    # deletion of a missing entry is a no-op
    spool.delete_entry(path)


def test_invalid_entry_reports_quarantine(spool):
    event_id = "33333333-3333-3333-3333-333333333333"
    path = spool.publish(make_source_event(event_id=event_id), event_id=event_id)
    path.write_text("{not json")
    assert spool.read_entry(path) is None
    quarantined = list((spool.root / "quarantine").glob("*"))
    assert len(quarantined) == 1


def test_non_dict_entry_is_invalid(spool):
    event_id = "44444444-4444-4444-4444-444444444444"
    path = spool.publish(make_source_event(event_id=event_id), event_id=event_id)
    path.write_text("[1, 2, 3]")
    assert spool.read_entry(path) is None


def test_diagnostics_never_include_payload(spool):
    event_id = "55555555-5555-5555-5555-555555555555"
    spool.publish(make_source_event(event_id=event_id), event_id=event_id)
    spool.note_diagnostics("something happened")
    text = (spool.root / "diagnostics.log").read_text()
    assert "something happened" in text
    assert "README.md" not in text


def test_overflow_drops_oldest_and_notes_diagnostic(spool):
    tiny = SpoolLimits(max_events=5, max_total_bytes=10 * 1024 * 1024)
    spool.limits = tiny
    ids = []
    for i in range(8):
        event_id = f"6666666{i:02d}-2222-2222-2222-00000000000{i}"
        spool.publish(make_source_event(index=i, tool=f"Tool{i}", event_id=event_id), event_id=event_id)
        ids.append(event_id)
    stats = spool.stats()
    assert stats["pending"] <= 5
    diagnostics = (spool.root / "diagnostics.log").read_text()
    assert "overflow" in diagnostics
    # oldest were dropped: the newest published id remains pending
    remaining_ids = {json.loads(p.read_text())["event_id"] for p in spool.pending_entries()}
    assert ids[-1] in remaining_ids
    assert ids[0] not in remaining_ids


def test_publisher_never_blocks_when_spool_full(spool):
    tiny = SpoolLimits(max_events=1, max_total_bytes=10 * 1024 * 1024)
    spool.limits = tiny
    spool.publish(make_source_event(index=1), event_id=str(uuid.uuid4()))
    import time

    started = time.monotonic()
    path = spool.publish(make_source_event(index=2), event_id=str(uuid.uuid4()))
    elapsed = time.monotonic() - started
    assert path.exists() and elapsed < 1.0
