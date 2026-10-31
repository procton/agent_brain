"""OpenCode connector: passive listener on the OpenCode background service.

The service already exposes `GET /api/event` (an SSE stream, Basic auth with
the local service password — see docs/opencode-integration.md). This listener
subscribes like any other API client would and:

- maps a strict allowlist of event types onto the source-neutral event kinds;
- sanitizes EVERY field before anything reaches the spool (no prompts, no tool
  output, no command text — shell commands collapse into coarse category
  tokens via `collector.sanitization`);
- publishes one sanitized event per spool file; the collector daemon then
  delivers them to the backend. Nothing is posted directly anywhere;
- never forwards text/reasoning/tool-input deltas (arbitrary model output),
  and never forwards token-usage counts (usage is forbidden as an intensity
  input per AGENTS.md §9).

This process does NOT control OpenCode in any way: it only reads events.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import socket
import subprocess
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from backend.app.config import Settings
from backend.app.schemas.source import SourceEvent
from collector.sanitization import sanitize_string, sanitize_tool_input
from collector.spool import Spool

SOURCE = "opencode"

# Only these wire event types are ever forwarded; everything else is ignored.
MAPPED_EVENT_TYPES = frozenset(
    {
        "session.created",
        "session.step.started",
        "session.tool.called",
        "session.tool.success",
        "session.tool.failed",
        "session.skill.activated",
        "permission.asked",
        "permission.replied",
        "session.idle",
        "session.execution.started",
        "session.execution.succeeded",
        "session.execution.failed",
        "session.execution.interrupted",
        "session.archived",
        "session.deleted",
    }
)

# Consumed to resolve tool names; never published themselves.
_TOOL_NAME_EVENTS = frozenset({"session.tool.input.started"})
_MAX_PART_CACHE = 256


def _machine_id() -> str:
    host = socket.gethostname().strip().lower() or "unknown-host"
    return host[:120]


def _ts_iso(epoch_ms: Any) -> str | None:
    if isinstance(epoch_ms, (int, float)) and epoch_ms > 0:
        return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC).isoformat(timespec="milliseconds")
    return None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class OpenCodeDiscovery:
    """Resolve the local OpenCode background service URL + auth header.

    Precedence: explicit args > environment > `opencode service status` CLI
    discovery. The service password comes from the service config file and is
    never printed, logged, or persisted anywhere by this module.
    """

    def __init__(self, *, server_url: str | None = None, password_file: Path | None = None):
        self.server_url = server_url or os.environ.get("OBSERVATORY_OPENCODE_SERVER")
        self.password_file = password_file or self._default_password_file()

    @staticmethod
    def _default_password_file() -> Path:
        xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        return Path(xdg) / "opencode" / "service.json"

    @staticmethod
    def discover_server_url() -> str | None:
        command = os.environ.get("OPENCODE_BIN", "opencode").split()
        try:
            result = subprocess.run(
                [*command, "service", "status"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        for line in result.stdout.splitlines():
            candidate = line.strip()
            if candidate.startswith(("http://", "https://")):
                return candidate.rstrip("/")
        return None

    def credentials(self) -> tuple[str, str] | None:
        """Return (Authorization header value, server_url) or None."""
        server = self.server_url or self.discover_server_url()
        if not server:
            return None
        password: str | None = None
        env_password = os.environ.get("OBSERVATORY_OPENCODE_PASSWORD")
        if env_password:
            password = env_password.strip()
        else:
            try:
                data = json.loads(self.password_file.read_text(encoding="utf-8"))
                password = sanitize_string(data.get("password"), max_length=256)
            except (OSError, json.JSONDecodeError, AttributeError):
                password = None
        if not password:
            return None
        raw = base64.b64encode(f"opencode:{password}".encode()).decode("ascii")
        return f"Basic {raw}", server


class OpenCodeTranslator:
    """Wire event (decoded `data:` payload) -> at most one sanitized SourceEvent."""

    def __init__(self, machine_id: str | None = None):
        self.machine_id = machine_id or _machine_id()
        self.published = 0
        self.dropped_unmapped = 0
        self.dropped_no_session = 0
        self._nonces = 0
        # part id -> sanitized summary captured at call time (target/tool)
        self._tool_summaries: OrderedDict[str, dict[str, str]] = OrderedDict()
        # part id -> tool name (from tool-input state events)
        self._tool_names: OrderedDict[str, str] = OrderedDict()

    @property
    def counters(self) -> dict[str, int]:
        return {
            "published": self.published,
            "dropped_unmapped": self.dropped_unmapped,
            "dropped_no_session": self.dropped_no_session,
        }

    def observe_wire(self, wire: dict) -> list[SourceEvent]:
        """Publish-side entry: translate one decoded event payload."""
        event_type = wire.get("type")
        data = wire.get("data") if isinstance(wire.get("data"), dict) else {}
        if event_type in _TOOL_NAME_EVENTS:
            self._remember_tool_name(data)
            return []
        if event_type not in MAPPED_EVENT_TYPES:
            self.dropped_unmapped += 1
            return []

        session_id = self._session_id_of(wire, event_type, data)
        if not session_id:
            self.dropped_no_session += 1
            return []

        project_root = sanitize_string((wire.get("location") or {}).get("directory"), max_length=200)
        if not isinstance(project_root, str) or not project_root.startswith("/"):
            project_root = None

        mapping = self._map_event(event_type, data, project_root)
        if mapping is None:
            self.dropped_unmapped += 1
            return []
        kind, source_event, summary = mapping

        self._nonces += 1
        wire_event_id = sanitize_string(wire.get("id"), max_length=120) or f"unidentified-{self._nonces}"
        occurred_at = _ts_iso(wire.get("created")) or _ts_iso(data.get("created")) or _now_iso()
        event = SourceEvent(
            event_id=f"oc-{wire_event_id}",
            machine_id=self.machine_id,
            session_id=str(session_id),
            source=SOURCE,
            source_event=source_event,
            kind=kind,
            occurred_at=occurred_at,
            recorded_at=_now_iso(),
            summary=summary,
            correlation=self._correlation_of(event_type, data),
        )
        self.published += 1
        return [event]

    translate = observe_wire  # backward-compatible alias

    # -- internals ---------------------------------------------------------

    def _remember_tool_name(self, data: dict) -> None:
        name = sanitize_string(data.get("name"), max_length=64)
        part_id = sanitize_string(data.get("id"), max_length=128)
        if name and part_id:
            self._tool_names[part_id] = name
            self._cap(self._tool_names)

    @staticmethod
    def _cap(cache: OrderedDict) -> None:
        while len(cache) > _MAX_PART_CACHE:
            cache.popitem(last=False)

    @staticmethod
    def _session_id_of(wire: dict, event_type: str, data: dict) -> str | None:
        session_id = sanitize_string(data.get("sessionID"), max_length=128)
        if not session_id:
            session_id = sanitize_string(wire.get("sessionID"), max_length=128)
        if not session_id and event_type in ("session.archived", "session.deleted"):
            session_id = sanitize_string(data.get("id"), max_length=128)
        return session_id

    @staticmethod
    def _correlation_of(event_type: str, data: dict) -> dict[str, str | None]:
        if event_type.startswith("session.tool."):
            return {
                "tool_call_id": sanitize_string(data.get("id"), max_length=128),
                "agent_id": None,
                "parent_agent_id": None,
            }
        return {"tool_call_id": None, "agent_id": None, "parent_agent_id": None}

    def _map_event(
        self, event_type: str, data: dict, project_root: str | None
    ) -> tuple[str, str, dict[str, str]] | None:
        part_id = sanitize_string(data.get("id"), max_length=128) or ""
        name = self._tool_names.get(part_id) or sanitize_string(data.get("name"), max_length=64)

        if event_type == "session.created":
            return "session.started", "SessionCreated", self._apply_project({}, project_root)

        if event_type in ("session.step.started", "session.execution.started"):
            summary: dict[str, str] = {}
            agent = sanitize_string(data.get("agent"), max_length=64)
            if agent:
                summary["agent"] = agent
            model = data.get("model") or {}
            model_id = sanitize_string(model.get("id"), max_length=120) if isinstance(model, dict) else None
            if model_id:
                summary["model"] = model_id
            return "turn.started", "SessionStepStarted", self._apply_project(summary, project_root)

        if event_type in ("session.tool.called", "session.tool.success", "session.tool.failed"):
            return self._map_tool_event(event_type, part_id, name, data, project_root)

        if event_type == "session.skill.activated":
            skill = sanitize_string(data.get("skill") or data.get("name"), max_length=120)
            if not skill:
                return None  # no verified name: never invent one
            return (
                "skill.activated",
                "SessionSkillActivated",
                self._apply_project({"skill": skill}, project_root),
            )

        if event_type == "permission.asked":
            return "agent.notification", "PermissionAsked", {"action": "permission-requested"}
        if event_type == "permission.replied":
            return "agent.notification", "PermissionReplied", {"action": "permission-replied"}

        if event_type == "session.idle":
            return "turn.completed", "SessionIdle", self._apply_project({"outcome": "idle"}, project_root)
        if event_type in (
            "session.execution.succeeded",
            "session.execution.failed",
            "session.execution.interrupted",
        ):
            return (
                "turn.completed",
                "SessionExecution",
                self._apply_project({"outcome": event_type.split(".")[-1]}, project_root),
            )
        if event_type in ("session.archived", "session.deleted"):
            return "session.ended", "SessionArchived", self._apply_project({}, project_root)
        return None

    def _map_tool_event(
        self, event_type: str, part_id: str, name: str | None, data: dict, project_root: str | None
    ) -> tuple[str, str, dict[str, str]] | None:
        input_args = data.get("input") if isinstance(data.get("input"), dict) else {}
        summary: dict[str, str] = {}
        if name:
            summary["tool"] = name
        summary.update(sanitize_tool_input(input_args))
        summary = {key: summary[key] for key in sorted(summary)[:8]}
        summary = self._apply_project(summary, project_root)

        if event_type == "session.tool.called":
            if part_id:
                self._tool_summaries[part_id] = summary
                self._cap(self._tool_summaries)
            return "tool.requested", "SessionToolCalled", summary

        # success/failure: prefer the sanitized summary captured at call time
        stashed = self._tool_summaries.get(part_id)
        if stashed:
            summary = dict(stashed)
        else:
            metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
            status = sanitize_string(metadata.get("status"), max_length=32)
            if status:
                summary["status"] = status
        if event_type == "session.tool.success":
            return "tool.completed", "SessionToolSuccess", summary
        return "tool.failed", "SessionToolFailed", summary

    @staticmethod
    def _apply_project(summary: dict[str, str], project_root: str | None) -> dict[str, str]:
        """Tag the project and make paths project-relative (AGENTS.md §12).

        Never persists usernames or home-directory paths: paths inside the
        project become project-relative; absolute paths outside collapse to
        their basename. Non-absolute / unknown values pass through untouched.
        """
        applied = dict(summary)
        if not project_root:
            return applied
        name = sanitize_string(project_root.rsplit("/", 1)[-1], max_length=120)
        if name:
            applied["project"] = name
        for key in ("target", "path", "directory"):
            value = applied.get(key)
            if not value:
                continue
            if value == project_root:
                applied[key] = "."
            elif value.startswith(project_root + "/"):
                applied[key] = value[len(project_root) + 1 :]
            elif value.startswith("/"):
                applied[key] = value.rsplit("/", 1)[-1]
        return applied


class OpenCodeListener:
    """Subscribe to the service SSE stream and publish sanitized spool files.

    Reconnects with bounded exponential backoff + jitter; OpenCode stays a
    plain HTTP client here — the listener never writes to the service.
    """

    def __init__(
        self,
        spool: Spool,
        *,
        settings: Settings,
        server_url: str | None = None,
        password_file: Path | None = None,
    ):
        self.spool = spool
        self.settings = settings
        self.discovery = OpenCodeDiscovery(server_url=server_url, password_file=password_file)
        self.translator = OpenCodeTranslator()
        self.publish_errors = 0
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    @property
    def counters(self) -> dict[str, int]:
        counters = self.translator.counters
        counters["publish_errors"] = self.publish_errors
        return counters

    async def run_forever(self) -> None:
        attempt = 0
        printed_drift_hint = False
        while not self._stop_requested:
            credentials = self.discovery.credentials()
            if credentials is None:
                if not printed_drift_hint:
                    print(
                        "[opencode-listen] cannot discover the local OpenCode service yet "
                        "(start OpenCode or set OBSERVATORY_OPENCODE_SERVER); retrying every 5s"
                    )
                    printed_drift_hint = True
                await asyncio.sleep(5)
                continue
            printed_drift_hint = False
            auth_header, server_url = credentials
            try:
                await self._stream_once(auth_header, server_url)
                attempt = 0
            except httpx.HTTPStatusError as exc:
                print(f"[opencode-listen] HTTP {exc.response.status_code} from {server_url}; backing off")
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                print(f"[opencode-listen] stream error ({type(exc).__name__}); reconnecting")
            if self._stop_requested:
                return
            delay = min(30.0, 0.5 * (2 ** min(attempt, 6)))
            await asyncio.sleep(delay + random.uniform(0, delay * 0.25))
            attempt += 1

    async def stream_limited(self, *, auth_header: str, server_url: str, seconds: float) -> None:
        """Stream for at most `seconds` (used for tests and --diagnostics)."""
        try:
            await asyncio.wait_for(
                self._stream_once(auth_header, server_url),
                timeout=seconds,
            )
        except TimeoutError:
            return  # normal end of a bounded sample

    async def _stream_once(self, auth_header: str, server_url: str) -> None:
        headers = {"Authorization": auth_header, "Accept": "text/event-stream"}
        url = server_url + "/api/event"
        timeout = httpx.Timeout(connect=5.0, read=None, write=5.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if self._stop_requested:
                        return
                    if not line.startswith("data: "):
                        continue  # SSE comments, heartbeats, blank separators
                    payload = line[len("data: ") :].strip()
                    if not payload:
                        continue
                    try:
                        wire = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    try:
                        self.publish_wire(wire)
                    except OSError as exc:
                        # Spool write failure (disk, dir moved, permissions) must
                        # never kill the stream or OpenCode: count it honestly
                        # and keep observing. The telemetry gap stays visible
                        # through `publish_errors` at shutdown/doctor output.
                        self.publish_errors += 1
                        print(f"[opencode-listen] spool write failed ({type(exc).__name__}); event dropped")
                        continue

    def publish_wire(self, wire: dict) -> list[str]:
        """Translate one wire event and write any sanitized result to the spool."""
        published_ids: list[str] = []
        for event in self.translator.observe_wire(wire):
            self.spool.publish(event.model_dump(mode="json"), event_id=event.event_id)
            published_ids.append(event.event_id)
        return published_ids
