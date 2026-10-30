"""Durable local event spool.

Design (per AGENT.md):
- One JSON file per event, published atomically via temporary file +
  `os.replace()` so concurrent hook-receiver invocations never corrupt entries.
- File names sort by publication time (`%016d` container timestamp then a
  monotonic counter) so the collector processes events in publication order.
- Network I/O never happens in this module: capture is fully local.
- Bounded spool: when the pending set exceeds configured limits, the OLDEST
  pending entries are dropped (fail-open) and a sanitized diagnostics note is
  appended. Claude Code is never blocked by a full spool.
- Invalid entries are moved to `quarantine/` without logging payloads.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PENDING = "pending"
_QUARANTINE = "quarantine"
_DIAGNOSTICS = "diagnostics.log"


@dataclass(frozen=True)
class SpoolLimits:
    max_events: int = 5000
    max_total_bytes: int = 20 * 1024 * 1024


class Spool:
    def __init__(self, root: str | os.PathLike[str], limits: SpoolLimits | None = None) -> None:
        self.root = Path(root)
        self.limits = limits or SpoolLimits()
        self._pending_dir = self.root / _PENDING
        self._quarantine_dir = self.root / _QUARANTINE
        self._diagnostics_path = self.root / _DIAGNOSTICS
        for directory in (self._pending_dir, self._quarantine_dir):
            directory.mkdir(parents=True, exist_ok=True)

    # -- publication ---------------------------------------------------------

    def publish(self, event: dict[str, Any], event_id: str) -> Path:
        """Atomically publish one sanitized event; returns the pending path.

        Raises nothing on success; if the spool is full the oldest events are
        dropped (never blocking the caller).
        """
        self._enforce_limits()
        payload = json.dumps(event, separators=(",", ":"), ensure_ascii=False)
        target = self._pending_dir / self._filename(event_id)
        tmp = target.with_suffix(f".tmp-{os.getpid()}")
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)  # atomic publication
        return target

    @staticmethod
    def _filename(event_id: str) -> str:
        seq = time.time_ns()
        return f"{seq:019d}-{event_id}.json"

    def _enforce_limits(self) -> None:
        entries = self.pending_entries()
        excess_by_count = max(0, len(entries) - self.limits.max_events + 1)
        if excess_by_count:
            self._drop_oldest(entries, excess_by_count)
            return
        total = sum(path.stat().st_size for path in entries)
        if total > self.limits.max_total_bytes:
            self._drop_oldest(entries, max(len(entries) // 10, 1))

    def _drop_oldest(self, entries: list[Path], count: int) -> None:
        for path in entries[:count]:
            try:
                path.unlink()
            except FileNotFoundError:
                continue
        self.note_diagnostics(f"spool overflow: dropped {count} oldest pending event(s)")

    # -- consumption ---------------------------------------------------------

    def pending_entries(self) -> list[Path]:
        return sorted(self._pending_dir.glob("*.json"))

    def read_entry(self, path: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self.quarantine(path, "unreadable-json")
            return None
        if not isinstance(data, dict):
            self.quarantine(path, "invalid-envelope")
            return None
        return data

    def delete_entry(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def quarantine(self, path: Path, reason: str) -> None:
        target = self._quarantine_dir / path.name
        try:
            os.replace(path, target)
        except OSError:  # pragma: no cover
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        self.note_diagnostics(f"quarantined event ({reason})")

    def note_diagnostics(self, message: str) -> None:
        """Sanitized, local-only diagnostics; never log payloads."""
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n"
        try:
            with open(self._diagnostics_path, "a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:  # pragma: no cover
            pass

    # -- stats ---------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        return {
            "pending": len(list(self._pending_dir.glob("*.json"))),
            "quarantined": len(list(self._quarantine_dir.glob("*"))),
        }
