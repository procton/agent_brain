"""OpenCode listener: translation mapping + SSE integration on a fake server.

Every fixture here is synthetic sanitized shape-only data (no real session
ids, no command text) — a real captured stream must never enter the repo.
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading

import httpx  # noqa: F401
import uvicorn
from fastapi import FastAPI, Request
from starlette.responses import StreamingResponse

from backend.app.config import Settings
from collector.opencode_listener import OpenCodeListener, OpenCodeTranslator
from collector.spool import Spool


def wire_event(
    event_type: str, data: dict | None = None, *, event_id: str = "evt_test0001", created: int | None = None
) -> dict:
    payload = {"id": event_id, "type": event_type}
    if created is not None:
        payload["created"] = created
    if data is not None:
        payload["data"] = data
    return payload


def sse_line(event: dict) -> str:
    return "data: " + json.dumps(event)


# ---------------------------------------------------------------------------
# Translator mapping
# ---------------------------------------------------------------------------


def test_tool_lifecycle_is_mapped_with_tool_call_id():
    translator = OpenCodeTranslator(machine_id="test-machine")
    started = wire_event(
        "session.tool.input.started", {"sessionID": "ses_x", "id": "part-1", "name": "read"}
    )
    called = wire_event(
        "session.tool.called",
        {
            "sessionID": "ses_x",
            "id": "part-1",
            "input": {"file_path": "src/app/main.py", "secret": "SHOULD_NOT_APPEAR"},
        },
    )
    success = wire_event(
        "session.tool.success",
        {
            "sessionID": "ses_x",
            "id": "part-1",
            "content": [{"type": "text", "text": "OUTPUT_THAT_MUST_BE_DROPPED"}],
        },
    )

    assert translator.observe_wire(started) == []  # name capture only
    requested = translator.observe_wire(called)
    assert len(requested) == 1
    assert requested[0].kind == "tool.requested"
    assert requested[0].summary == {"tool": "read", "target": "src/app/main.py"}
    assert requested[0].correlation.tool_call_id == "part-1"
    assert "secret" not in requested[0].summary

    completed = translator.observe_wire(success)
    assert len(completed) == 1
    assert completed[0].kind == "tool.completed"
    assert completed[0].summary == {"tool": "read", "target": "src/app/main.py"}
    assert all("OUTPUT" not in value for value in completed[0].summary.values())


def test_command_text_collapses_to_category_token():
    translator = OpenCodeTranslator(machine_id="test-machine")
    translator.observe_wire(
        wire_event("session.tool.input.started", {"sessionID": "ses_x", "id": "part-9", "name": "shell"})
    )
    called = translator.observe_wire(
        wire_event(
            "session.tool.called",
            {
                "sessionID": "ses_x",
                "id": "part-9",
                "input": {"command": "pytest backend/tests -q", "cwd": "/home/me/secret_repo"},
            },
        )
    )
    assert len(called) == 1
    summary = called[0].summary
    assert summary["command"] == "pytest"  # coarse token only
    assert "pytest backend/tests" not in json.dumps(summary)
    assert "cwd" not in summary  # unallowlisted input keys are dropped


def test_unmapped_and_delta_events_are_never_published():
    translator = OpenCodeTranslator()
    responses = [
        wire_event("session.text.delta", {"sessionID": "ses_x", "text": "SECRET_OUTPUT"}),
        wire_event("session.reasoning.delta", {"sessionID": "ses_x"}),
        wire_event("session.usage.updated", {"sessionID": "ses_x", "tokens": {"input": 1}}),
        wire_event("shell.created", {}),
        {"id": "evt_hb", "type": "not-a-real-event"},
    ]
    published = [event for wire in responses for event in translator.observe_wire(wire)]
    assert published == []
    assert translator.counters["published"] == 0


def test_skill_activation_is_explicit_and_requires_a_name():
    translator = OpenCodeTranslator()
    unnamed = translator.observe_wire(wire_event("session.skill.activated", {"sessionID": "ses_x"}))
    assert unnamed == []
    named = translator.observe_wire(
        wire_event(
            "session.skill.activated", {"sessionID": "ses_x", "skill": "opencode", "name": "Opencode"}
        )
    )
    assert len(named) == 1
    assert named[0].kind == "skill.activated"
    assert named[0].event_id.startswith("oc-")
    assert named[0].summary["skill"] == "opencode"


def test_permission_events_surface_as_notifications_not_approvals():
    translator = OpenCodeTranslator()
    asked = translator.observe_wire(
        wire_event("permission.asked", {"sessionID": "ses_x", "action": "edit"})
    )
    replied = translator.observe_wire(
        wire_event("permission.replied", {"sessionID": "ses_x", "response": "once"})
    )
    assert [event.kind for event in asked + replied] == ["agent.notification", "agent.notification"]
    assert asked[0].summary == {"action": "permission-requested"}
    assert replied[0].summary == {"action": "permission-replied"}


def test_execution_and_idle_end_the_turn():
    translator = OpenCodeTranslator()
    idle = translator.observe_wire(wire_event("session.idle", {"sessionID": "ses_x"}))
    executed = translator.observe_wire(wire_event("session.execution.succeeded", {"sessionID": "ses_x"}))
    assert idle[0].kind == "turn.completed"
    assert executed[0].kind == "turn.completed"
    assert executed[0].summary["outcome"] == "succeeded"


def test_archived_without_session_id_still_uses_its_own_id():
    translator = OpenCodeTranslator()
    archived = translator.observe_wire(wire_event("session.archived", {"id": "ses_gone"}))
    assert len(archived) == 1
    assert archived[0].kind == "session.ended"
    assert archived[0].session_id == "ses_gone"


def test_event_without_session_id_is_dropped_not_invented():
    translator = OpenCodeTranslator()
    result = translator.observe_wire(wire_event("session.tool.called", {"id": "part-42", "input": {}}))
    assert result == []
    assert translator.counters["dropped_no_session"] == 1


def test_paths_become_project_relative_and_project_is_labeled():
    translator = OpenCodeTranslator(machine_id="test-machine")
    translator.observe_wire(
        wire_event("session.tool.input.started", {"sessionID": "ses_x", "id": "p2", "name": "read"})
    )
    inside = wire_event(
        "session.tool.called",
        {"sessionID": "ses_x", "id": "p2", "input": {"file_path": "/home/me/proj/docs/notes.md"}},
    )
    inside["location"] = {"directory": "/home/me/proj"}
    events = translator.observe_wire(inside)
    assert events[0].summary == {"project": "proj", "target": "docs/notes.md", "tool": "read"}

    outside = wire_event(
        "session.tool.called",
        {
            "sessionID": "ses_x",
            "id": "p3",
            "input": {"file_path": "/home/me/shared/secret-dir/config.json"},
        },
    )
    outside["location"] = {"directory": "/home/me/proj"}
    events = translator.observe_wire(outside)
    # Outside the project the basename only: no username, no home directory.
    assert events[0].summary["target"] == "config.json"
    assert "/home/" not in json.dumps(events[0].summary)
    assert "me" not in json.dumps(events[0].summary)


# ---------------------------------------------------------------------------
# Background-service discovery
# ---------------------------------------------------------------------------


def test_discovery_prefers_explicit_url_and_password_file(tmp_path):
    from collector.opencode_listener import OpenCodeDiscovery

    secret_file = tmp_path / "service.json"
    secret_file.write_text(json.dumps({"password": "service-secret"}), encoding="utf-8")
    discovery = OpenCodeDiscovery(server_url="http://127.0.0.1:5999", password_file=secret_file)
    header, url = discovery.credentials()
    assert url == "http://127.0.0.1:5999"
    expect = "Basic " + base64.b64encode(b"opencode:service-secret").decode()
    assert header == expect


def test_discovery_fails_without_any_hints(tmp_path, monkeypatch):
    from collector.opencode_listener import OpenCodeDiscovery

    monkeypatch.delenv("OBSERVATORY_OPENCODE_SERVER", raising=False)
    monkeypatch.delenv("OBSERVATORY_OPENCODE_PASSWORD", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))  # no service.json here
    discovery = OpenCodeDiscovery(server_url=None, password_file=tmp_path / "nothing")
    assert discovery.credentials() is None


# ---------------------------------------------------------------------------
# SSE integration against a real HTTP server (bounded run)
# ---------------------------------------------------------------------------

SSE_LINES = [
    sse_line(wire_event("server.connected", {})),
    "",
    ": heartbeat",
    "",
    sse_line(
        wire_event("session.created", {"sessionID": "ses-x", "title": "NO_TITLE_STORED"}, event_id="evt_a")
    ),
    sse_line(
        wire_event(
            "session.step.started",
            {"sessionID": "ses-x", "agent": "build", "model": {"id": "test-model"}},
            event_id="evt_b",
        )
    ),
    sse_line(
        wire_event(
            "session.tool.input.started",
            {"sessionID": "ses-x", "id": "p1", "name": "read"},
            event_id="evt_c",
        )
    ),
    sse_line(
        wire_event(
            "session.tool.called",
            {"sessionID": "ses-x", "id": "p1", "input": {"file_path": "docs/notes.md"}},
            event_id="evt_d",
        )
    ),
    sse_line(wire_event("session.tool.success", {"sessionID": "ses-x", "id": "p1"}, event_id="evt_e")),
]


def build_sse_app() -> FastAPI:
    return build_sse_app_with(SSE_LINES)


def build_sse_app_with(lines: list[str]) -> FastAPI:
    app = FastAPI()

    @app.get("/api/event")
    async def stream(request: Request) -> StreamingResponse:
        async def generator():
            for line in lines:
                yield line + "\n\n"
            await asyncio.sleep(30)  # stay open; the client bounds the run

        return StreamingResponse(generator(), media_type="text/event-stream")

    return app


async def start_server(app: FastAPI):
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.02)
    assert server.started, "uvicorn did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, thread, port


async def test_listener_publishes_mapped_events_from_real_sse(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    spool = Spool(settings.spool_dir)
    listener = OpenCodeListener(
        spool, settings=settings, server_url="http://unused", password_file=tmp_path / "missing"
    )

    app = build_sse_app()
    server, thread, port = await start_server(app)
    try:
        await listener.stream_limited(
            auth_header="Basic unused", server_url=f"http://127.0.0.1:{port}", seconds=3
        )
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    counters = listener.counters
    assert counters["published"] == 4  # session.started + turn.started + tool.requested + tool.completed

    entries = sorted(spool.pending_entries())
    assert len(entries) == 4
    contents = [json.loads(entry.read_text(encoding="utf-8")) for entry in entries]
    kinds = sorted(content["kind"] for content in contents)
    assert kinds == ["session.started", "tool.completed", "tool.requested", "turn.started"]
    session_started = next(content for content in contents if content["kind"] == "session.started")
    assert session_started["session_id"] == "ses-x"
    assert "NO_TITLE" not in json.dumps(session_started["summary"])  # titles never stored
    requested = next(content for content in contents if content["kind"] == "tool.requested")
    assert requested["summary"] == {"tool": "read", "target": "docs/notes.md"}
    for content in contents:
        assert content["source"] == "opencode"
        assert content["event_id"].startswith("oc-")
        assert content["recorded_at"]  # written by the capture path
        assert content["machine_id"]  # never empty


async def test_spool_write_failures_never_kill_the_stream(tmp_path):
    """A spool outage is counted and observed-through, never fatal (§6)."""
    settings = Settings(data_dir=tmp_path / "data")
    spool = Spool(settings.spool_dir)
    listener = OpenCodeListener(
        spool, settings=settings, server_url="http://unused", password_file=tmp_path / "missing"
    )

    seen: list[str] = []
    original_publish = spool.publish

    def flaky_publish(event, event_id):
        if len(seen) < 1:
            seen.append(event_id)
            raise OSError("spool dir vanished")
        return original_publish(event, event_id)

    # Build a small real SSE server serving one session event.
    app = build_sse_app_with(
        [
            sse_line(wire_event("session.created", {"sessionID": "ses-flaky"}, event_id="evt_f1")),
            sse_line(wire_event("session.created", {"sessionID": "ses-flaky"}, event_id="evt_f2")),
        ]
    )
    server, thread, port = await start_server(app)
    try:
        listener.spool.publish = flaky_publish  # type: ignore[method-assign]
        await listener.stream_limited(
            auth_header="Basic unused", server_url=f"http://127.0.0.1:{port}", seconds=3
        )
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert listener.counters["publish_errors"] == 1
    assert listener.counters["published"] == 2  # translation still observed both

    contents = [json.loads(entry.read_text(encoding="utf-8")) for entry in spool.pending_entries()]
    kinds = [content["kind"] for content in contents]
    assert kinds == ["session.started"]  # only the second file survived the outage
