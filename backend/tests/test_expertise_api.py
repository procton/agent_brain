"""Expertise snapshot endpoint: auth, evidence wiring, sessionless errors."""

from __future__ import annotations

from backend.tests.conftest import ingest, make_source_event


async def test_expertise_endpoint_requires_dashboard_session(client):
    response = await client.http.get("/api/sessions/whatever-id/expertise")
    assert response.status_code == 401


async def test_expertise_endpoint_unknown_session_404(client):
    login = await client.login()
    assert login.status_code == 200
    response = await client.http.get("/api/sessions/definitely-missing/expertise")
    assert response.status_code == 404


async def test_expertise_snapshot_sums_evidence_from_events(client):
    login = await client.login()
    assert login.status_code == 200

    # Recent timestamps: the snapshot engine's activity window ignores older
    # evidence by design (decay only covers recent observed activity).
    from datetime import UTC, datetime, timedelta

    base = datetime.now(UTC) - timedelta(seconds=30)
    events = [
        make_source_event(
            kind=kind,
            source_event=source_event,
            index=index,
            tool=tool,
            target=target,
            occurred_at=(base + timedelta(seconds=index)).isoformat(timespec="milliseconds"),
        )
        for index, (kind, source_event, tool, target) in enumerate(
            [
                ("tool.requested", "PreToolUse", "Read", "docs/index.md"),
                ("tool.completed", "PostToolUse", "Shell", "infra/Dockerfile"),
                ("tool.failed", "PostToolUseFailure", "Shell", "infra/Dockerfile"),
            ]
        )
    ]
    skill_event = make_source_event(
        kind="skill.activated",
        source_event="SessionSkillActivated",
        index=3,
        occurred_at=(base + timedelta(seconds=3)).isoformat(timespec="milliseconds"),
    )
    # Skill events carry the verified skill name in their sanitized summary.
    skill_event["summary"] = {"skill": "opencode"}
    accepted = await ingest(client, events + [skill_event])
    assert accepted.status_code == 200

    listing = await client.http.get("/api/sessions")
    sessions = listing.json()["sessions"]
    session_id = sessions[0]["id"]

    response = await client.http.get(f"/api/sessions/{session_id}/expertise")
    assert response.status_code == 200, response.text
    snap = response.json()

    assert snap["session_id"] == session_id
    assert {region["key"] for region in snap["regions"]} == {
        "code_exploration",
        "frontend",
        "backend",
        "testing",
        "database",
        "infrastructure",
        "debugging",
    }
    infra = next(region for region in snap["regions"] if region["key"] == "infrastructure")
    assert infra["state"] in ("active", "fading", "idle")  # evidence was just ingested
    assert infra["evidence"], "evidence rows must explain the intensity"
    assert infra["evidence"][0]["basis"] == "inferred"
    assert infra["evidence"][0]["rule_id"]

    # Skill activations are explicit and separate from region intensity.
    assert [skill["name"] for skill in snap["skills"]] == ["opencode"]
    assert snap["skills"][0]["recent"] is True
    assert snap["skills"][0]["evidence_event_ids"], "skill rows carry their evidence ids"

    # Notes must disclose honesty about intensity and deactivation.
    assert "not effort" in snap["notes"]
    assert "no explicit deactivation signal" in snap["notes"]

    config = snap["config"]
    assert config["half_life_seconds"] > 0
    assert config["activate_threshold"] > config["fade_threshold"]
