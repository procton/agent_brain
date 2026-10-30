"""Collector daemon: deliver queued spool events to the backend.

Behavior (per AGENT.md):
- Bounded batches: at most `batch_size` events and `batch_max_bytes` bytes per
  HTTP call.
- Retry temporary failures (connection errors, 5xx, 429, 413) with exponential
  backoff and jitter; event IDs are preserved across retries.
- Delete spool entries only after the backend confirms acceptance (per-event
  report); permanently invalid entries are quarantined locally without logging
  their payloads.
- Clean shutdown on SIGINT/SIGTERM: finish the current batch, then exit.

The daemon performs no capture-side work.
"""

from __future__ import annotations

import asyncio
import json
import random

import httpx

from backend.app.schemas.source import SCHEMA_VERSION, SourceEvent
from collector.spool import Spool

BACKOFF_INITIAL_SECONDS = 0.5
BACKOFF_MAX_SECONDS = 30.0
BACKOFF_FACTOR = 1.6

RETRYABLE_STATUS = {502, 503, 504, 429}
PERMANENT_STATUS = {401, 403}


def event_id_of(payload: dict) -> str | None:
    value = payload.get("event_id")
    return value if isinstance(value, str) else None


class CollectorDaemon:
    def __init__(
        self,
        spool: Spool,
        backend_base_url: str,
        credential: str,
        *,
        batch_size: int = 50,
        batch_max_bytes: int = 256 * 1024,
        transport: httpx.AsyncBaseTransport | None = None,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self.spool = spool
        self.backend_base_url = backend_base_url.rstrip("/")
        self.credential = credential
        self.batch_size = batch_size
        self.batch_max_bytes = batch_max_bytes
        self.transport = transport
        self.poll_interval_seconds = poll_interval_seconds
        self._stop = asyncio.Event()
        self._backoff_seconds = 0.0
        self.stats = {
            "batches_delivered": 0,
            "events_delivered": 0,
            "events_quarantined": 0,
            "duplicates_accepted": 0,
            "temporary_failures": 0,
        }

    # -- lifecycle -----------------------------------------------------------

    def request_stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        async with self._make_client() as client:
            while not self._stop.is_set():
                outcome = await self._deliver_one_batch(client)
                await self._pause(outcome)

    async def run_until_idle(self, *, idle_cycles: int = 2, max_attempts: int = 8) -> int:
        """Deliver everything currently queued; used by CLI --once and tests.

        Semantics: exit after `idle_cycles` consecutive empty polls, or after
        `max_attempts` real delivery attempts (so a downed backend cannot spin
        forever). Returns the number of delivered batches.
        """
        delivered = 0
        attempts = 0
        async with self._make_client() as client:
            empty_polls = 0
            while empty_polls < idle_cycles and attempts < max_attempts:
                outcome = await self._deliver_one_batch(client)
                if outcome == "delivered":
                    delivered += 1
                    empty_polls = 0
                    continue
                if outcome == "retry":
                    attempts += 1  # a real, failed delivery attempt
                    continue
                empty_polls += 1
                await asyncio.sleep(self.poll_interval_seconds)
        return delivered

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.backend_base_url,
            headers={"Authorization": f"Bearer {self.credential}"},
            transport=self.transport,
        )

    async def _pause(self, outcome: str) -> None:
        if outcome == "delivered":
            nap = 0.0
        else:
            nap = self.poll_interval_seconds
            if self._backoff_seconds:
                nap = self._backoff_seconds
                self._backoff_seconds = min(BACKOFF_MAX_SECONDS, self._backoff_seconds * BACKOFF_FACTOR)
            jitter = random.uniform(0, nap * 0.25) if nap else 0.0
            nap += jitter
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=nap)
        except asyncio.TimeoutError:
            pass

    # -- delivery ------------------------------------------------------------

    async def _deliver_one_batch(self, client: httpx.AsyncClient) -> str:
        """One bounded batch attempt. Returns outcome status."""
        batch = self._assemble_batch()
        if batch is None:
            return "idle"

        payload = {"schema_version": SCHEMA_VERSION, "events": [e.payload for e in batch]}
        try:
            response = await client.post(
                "/api/events/batch",
                json=payload,
            )
        except (httpx.TransportError, httpx.StreamError) as exc:
            self.stats["temporary_failures"] += 1
            self._request_backoff(f"backend unreachable ({type(exc).__name__})")
            return "retry"

        status = response.status_code
        if status == 200:
            report = response.json()
            self._apply_report(batch, report)
            self.stats["batches_delivered"] += 1
            self._backoff_seconds = 0.0
            return "delivered"
        if status in RETRYABLE_STATUS or status in (422, 413):
            # 422/413: whole-batch schema/size problems cannot be fixed by
            # retrying unchanged; quarantine permanently invalid entries.
            self.stats["temporary_failures"] += 1
            if status in (422, 413):
                note = (
                    f"batch rejected ({status}); quarantining {len(batch)} invalid entr(y|ies)"
                    .replace("(y|ies)", "y" if len(batch) == 1 else "ies")
                )
                self.spool.note_diagnostics(note)
                for item in batch:
                    self.spool.quarantine(item.path, f"batch-rejected-{status}")
                    self.stats["events_quarantined"] += 1
                return "dropped-invalid"
            self._request_backoff(f"temporary backend failure ({status})")
            return "retry"
        if status in PERMANENT_STATUS:
            # Credential problem: keep data, back off (diagnostics only).
            self._request_backoff(f"authentication failure ({status})")
            return "retry"
        self._request_backoff(f"unexpected backend status ({status})")
        return "retry"

    # -- batch assembly ------------------------------------------------------

    def _assemble_batch(self) -> list[BatchItem] | None:
        items: list[BatchItem] = []
        total_bytes = 0
        for entry in self.spool.pending_entries():
            if len(items) >= self.batch_size:
                break
            data = self.spool.read_entry(entry)
            if data is None:  # quarantined by the spool
                self.stats["events_quarantined"] += 1
                continue
            try:
                event = SourceEvent.model_validate(data)
            except Exception:
                self.spool.quarantine(entry, "invalid-schema")
                self.stats["events_quarantined"] += 1
                continue
            size = len(entry.read_text(encoding="utf-8"))
            if items and total_bytes + size > self.batch_max_bytes:
                break
            items.append(BatchItem(path=entry, payload=event.model_dump(mode="json")))
            total_bytes += size
        return items or None

    def _apply_report(self, batch: list[BatchItem], report: dict) -> None:
        accepted = set(report.get("accepted", []))
        duplicates = set(report.get("duplicates", []))
        for item in batch:
            event_id = event_id_of(item.payload)
            if event_id is None:
                self.spool.quarantine(item.path, "missing-event-id")
                self.stats["events_quarantined"] += 1
                continue
            if event_id in accepted:
                self.spool.delete_entry(item.path)
                self.stats["events_delivered"] += 1
            elif event_id in duplicates:
                self.spool.delete_entry(item.path)
                self.stats["duplicates_accepted"] += 1
            else:
                # Backend confirmed receiving the batch but not this event; the
                # entry stays queued and will be retried (it cannot vanish).
                pass

    def _request_backoff(self, reason: str) -> None:
        jitter = random.uniform(0, BACKOFF_INITIAL_SECONDS)
        target = max(BACKOFF_INITIAL_SECONDS, self._backoff_seconds * BACKOFF_FACTOR)
        self._backoff_seconds = min(BACKOFF_MAX_SECONDS, target + jitter * 0.25)
        self.spool.note_diagnostics(f"{reason}; backing off {self._backoff_seconds:.2f}s")


class BatchItem:
    __slots__ = ("path", "payload")

    def __init__(self, path, payload) -> None:
        self.path = path
        self.payload = payload


__all__ = [
    "CollectorDaemon",
    "BACKOFF_MAX_SECONDS",
    "BACKOFF_INITIAL_SECONDS",
]
