"""Collector daemon tests with a mocked HTTP transport (no real backend)."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable

import httpx

from collector.daemon import CollectorDaemon
from collector.spool import Spool
from collector.tests.conftest import make_source_event

AUTH_HEADER = "Authorization"


def make_daemon(spool: Spool, handler: Callable, *, batch_size: int = 50) -> CollectorDaemon:
    transport = httpx.MockTransport(handler)
    return CollectorDaemon(
        spool,
        "http://backend.test",
        "secret-token",
        batch_size=batch_size,
        transport=transport,
        poll_interval_seconds=0.01,
    )


def publish(spool: Spool, count: int = 3) -> list[str]:
    ids = []
    for index in range(count):
        payload = make_source_event(index=index)
        spool.publish(payload, event_id=payload["event_id"])
        ids.append(payload["event_id"])
    return ids


def default_handler(calls: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content.decode())
        accepted = [event["event_id"] for event in body["events"]]
        return httpx.Response(200, json={"accepted": accepted, "duplicates": [], "rejected": []})

    return handler


def test_delivers_batch_with_preserved_event_ids(spool):
    ids = publish(spool, 3)
    calls: list[httpx.Request] = []
    daemon = make_daemon(spool, default_handler(calls))
    asyncio.run(daemon.run_until_idle())
    assert daemon.stats["events_delivered"] == 3
    assert daemon.stats["batches_delivered"] == 1
    assert not spool.pending_entries()
    delivered_ids = [json.loads(calls[0].content.decode())["events"][i]["event_id"] for i in range(3)]
    assert delivered_ids == ids
    assert len(ids) == len(set(ids))


def test_retry_on_temporary_failure_keeps_ids(spool):
    ids = publish(spool, 2)
    calls: list[httpx.Request] = []
    sent_payloads: list[list] = []
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        attempts["n"] += 1
        if attempts["n"] <= 2:
            return httpx.Response(503, json={"detail": "backend starting"})
        body = json.loads(request.content.decode())
        sent_payloads.append(body["events"])
        ids_in_body = [event["event_id"] for event in body["events"]]
        return httpx.Response(200, json={"accepted": ids_in_body, "duplicates": []})

    daemon = make_daemon(spool, handler)
    asyncio.run(daemon.run_until_idle())
    assert attempts["n"] == 3
    assert daemon.stats["temporary_failures"] == 2
    assert not spool.pending_entries()
    assert sent_payloads[-1] and [e["event_id"] for e in sent_payloads[-1]] == ids


def test_connection_error_keeps_entries_queued(spool):
    ids = publish(spool, 2)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    daemon = make_daemon(spool, handler)
    asyncio.run(daemon.run_until_idle(idle_cycles=2))
    assert daemon.stats["temporary_failures"] >= 1
    remaining = spool.pending_entries()
    assert len(remaining) == 2
    kept = {json.loads(p.read_text())["event_id"] for p in remaining}
    assert kept == set(ids)


def test_partial_acceptance_only_deletes_confirmed(spool):
    publish(spool, 3)
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        body = json.loads(request.content.decode())
        if attempts["n"] == 1:
            return httpx.Response(200, json={"accepted": [body["events"][0]["event_id"]], "duplicates": []})
        return httpx.Response(
            200, json={"accepted": [e["event_id"] for e in body["events"]], "duplicates": []}
        )

    daemon = make_daemon(spool, handler)
    asyncio.run(daemon.run_until_idle())
    assert daemon.stats["events_delivered"] == 3
    assert not spool.pending_entries()
    assert attempts["n"] >= 2


def test_duplicate_event_ids_are_confirmed_and_removed(spool):
    ids = publish(spool, 2)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        events = json.loads(request.content.decode())["events"]
        if len(calls) == 1:
            return httpx.Response(200, json={"accepted": [e["event_id"] for e in events], "duplicates": []})
        # Simulate backend replaying the same batch (e.g. collector retried after
        # a lost response): events already present are reported as duplicates.
        return httpx.Response(200, json={"accepted": [], "duplicates": [e["event_id"] for e in events]})

    daemon = make_daemon(spool, handler)
    asyncio.run(daemon.run_until_idle())
    assert daemon.stats["events_delivered"] == 2
    assert not spool.pending_entries()
    # republish the same ids (as a retrying collector would)
    for id_ in ids:
        spool.publish(
            make_source_event(event_id=id_, index=9),
            event_id=id_,
        )
    asyncio.run(daemon.run_until_idle())
    assert daemon.stats["duplicates_accepted"] == 2
    assert not spool.pending_entries()


def test_invalid_schema_entry_is_quarantined(spool):
    good = make_source_event()
    spool.publish(good, event_id=good["event_id"])
    spool.publish({"event_id": 123}, event_id=str(uuid.uuid4()))
    daemon = make_daemon(spool, default_handler([]))
    asyncio.run(daemon.run_until_idle())
    assert daemon.stats["events_quarantined"] == 1
    assert daemon.stats["events_delivered"] == 1
    quarantined = list((spool.root / "quarantine").glob("*"))
    assert len(quarantined) == 1
    # quarantined file exists but good event was delivered


def test_auth_failure_retries_but_keeps_data(spool):
    publish(spool, 2)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get(AUTH_HEADER) != "Bearer secret-token":
            return httpx.Response(403, json={"detail": "invalid credential"})
        events = json.loads(request.content.decode())["events"]
        return httpx.Response(200, json={"accepted": [e["event_id"] for e in events], "duplicates": []})

    daemon = make_daemon(spool, handler)
    asyncio.run(daemon.run_until_idle())
    assert not spool.pending_entries()
    assert daemon.stats["events_delivered"] == 2


def test_batches_are_bounded(spool):
    publish(spool, 4)
    calls: list[httpx.Request] = []
    daemon = make_daemon(spool, default_handler(calls), batch_size=2)
    asyncio.run(daemon.run_until_idle())
    assert len(calls) >= 2
    sizes = [len(json.loads(c.content.decode())["events"]) for c in calls]
    assert all(size <= 2 for size in sizes)
    assert sum(sizes) == 4
    assert not spool.pending_entries()


def test_batch_error_422_reports_invalid_entries(spool):
    publish(spool, 2)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "invalid batch; no events persisted"})

    daemon = make_daemon(spool, handler)
    asyncio.run(daemon.run_until_idle())
    assert daemon.stats["events_quarantined"] == 2
    assert not spool.pending_entries()
    assert len(list((spool.root / "quarantine").glob("*"))) == 2
