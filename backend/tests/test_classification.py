"""Classification rules + expertise snapshot engine.

Clock-controlled tests per AGENTS.md §9: the decay function never calls the
system clock — `build_snapshot(..., now=...)` always receives it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.app.classification import ExpertiseConfig, build_snapshot, classify_event

BASE = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds")


def make_event(
    cursor: int, kind: str, summary: dict, *, at: datetime | None = None, event_id: str | None = None
) -> dict:
    stamp = iso(at or BASE)
    return {
        "event_id": event_id or f"evt-{cursor:03d}",
        "cursor": cursor,
        "kind": kind,
        "occurred_at": stamp,
        "received_at": stamp,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Per-event rules
# ---------------------------------------------------------------------------


def test_read_tool_marks_code_exploration():
    labels = classify_event(
        "tool.requested", {"tool": "read", "target": "README.md"}, evidence_event_id="e1"
    )
    assert [label["label"] for label in labels] == ["code_exploration"]
    assert labels[0]["rule_id"] == "read-tools"
    assert labels[0]["basis"] == "inferred"


def test_tsx_target_supports_frontend_and_not_react_claim():
    labels = classify_event(
        "tool.completed", {"tool": "edit", "target": "src/components/Checkout.tsx"}, evidence_event_id="e2"
    )
    assert "frontend" in {label["label"] for label in labels}
    # A .tsx target does not prove any professional claim: confidence stays qualitative.
    assert all(label["confidence"] in ("low", "medium", "high") for label in labels)
    assert all(label["basis"] == "inferred" for label in labels)


def test_test_path_and_pytest_command_mark_testing():
    path_labels = classify_event(
        "tool.requested", {"tool": "edit", "target": "backend/tests/test_ingest.py"}, evidence_event_id="e3"
    )
    assert "testing" in {label["label"] for label in path_labels}

    cmd_labels = classify_event(
        "tool.completed", {"tool": "shell", "command": "pytest"}, evidence_event_id="e4"
    )
    assert "testing" in {label["label"] for label in cmd_labels}
    assert any(label["rule_id"] == "command-test-signature" for label in cmd_labels)


def test_migration_target_marks_database_and_dockerfile_infra():
    db_labels = classify_event(
        "tool.completed",
        {"tool": "edit", "target": "backend/migrations/versions/0002_x.py"},
        evidence_event_id="e5",
    )
    assert "database" in {label["label"] for label in db_labels}

    f_labels = classify_event(
        "tool.completed", {"tool": "edit", "target": "infra/Dockerfile"}, evidence_event_id="e6"
    )
    assert "infrastructure" in {label["label"] for label in f_labels}


def test_no_labels_without_recognized_evidence():
    assert (
        classify_event("tool.completed", {"tool": "shell", "command": "git"}, evidence_event_id="e7") == []
    )
    assert classify_event("session.started", {}, evidence_event_id="e8") == []


def test_single_failure_never_proves_debugging_per_event():
    labels = classify_event("tool.failed", {"tool": "shell", "command": "test"}, evidence_event_id="e9")
    assert "debugging" not in {label["label"] for label in labels}


# ---------------------------------------------------------------------------
# Snapshot engine (controlled clock)
# ---------------------------------------------------------------------------


def _config(**overrides) -> ExpertiseConfig:
    return ExpertiseConfig(**overrides)


def test_one_fresh_event_activates_then_fades_then_goes_dim():
    events = [make_event(1, "tool.requested", {"tool": "read", "target": "a.py"})]
    cfg = _config()

    fresh = build_snapshot(events, config=cfg, now=BASE + timedelta(seconds=2))
    region = next(r for r in fresh["regions"] if r["key"] == "code_exploration")
    assert region["state"] == "active"
    assert region["intensity"] >= cfg.activate_threshold

    half = build_snapshot(events, config=cfg, now=BASE + timedelta(seconds=2 * cfg.half_life_seconds))
    fading = next(r for r in half["regions"] if r["key"] == "code_exploration")
    assert fading["state"] == "fading"
    assert cfg.fade_threshold < fading["intensity"] < cfg.activate_threshold

    dim = build_snapshot(events, config=cfg, now=BASE + timedelta(seconds=4 * cfg.half_life_seconds))
    dimmed = next(r for r in dim["regions"] if r["key"] == "code_exploration")
    assert dimmed["state"] in ("idle", "inactive")


def test_decayed_function_halving_is_exact():
    events = [make_event(1, "tool.requested", {"tool": "read", "target": "a.py"})]
    cfg = _config()
    exactly_t0 = build_snapshot(events, config=cfg, now=BASE)
    after_half_life = build_snapshot(
        events, config=cfg, now=BASE + timedelta(seconds=cfg.half_life_seconds)
    )
    intensity_0 = next(r for r in exactly_t0["regions"] if r["key"] == "code_exploration")["intensity"]
    intensity_half = next(r for r in after_half_life["regions"] if r["key"] == "code_exploration")[
        "intensity"
    ]
    assert intensity_0 == 1.0
    assert intensity_half == 0.5


def test_out_of_window_evidence_is_ignored():
    events = [
        make_event(
            1,
            "tool.completed",
            {"tool": "shell", "target": "infra/Dockerfile"},
            at=BASE - timedelta(hours=1),
        )
    ]
    snap = build_snapshot(events, config=_config(), now=BASE)
    infra = next(r for r in snap["regions"] if r["key"] == "infrastructure")
    assert infra["state"] == "inactive"
    assert infra["intensity"] == 0.0
    assert infra["evidence_count"] == 0


def test_debugging_requires_repeated_failures():
    two = [
        make_event(1, "tool.failed", {"tool": "shell", "command": "test"}, at=BASE - timedelta(seconds=30)),
        make_event(2, "tool.failed", {"tool": "shell", "command": "test"}, at=BASE - timedelta(seconds=5)),
    ]
    snap = build_snapshot(two, config=_config(), now=BASE)
    debugging = next(r for r in snap["regions"] if r["key"] == "debugging")
    assert debugging["state"] == "active"
    assert debugging["evidence"][0]["rule_id"] == "repeated-failure"
    assert all(e["basis"] == "inferred" for e in debugging["evidence"])

    one = two[:1]
    snap1 = build_snapshot(one, config=_config(), now=BASE)
    assert next(r for r in snap1["regions"] if r["key"] == "debugging")["state"] == "inactive"


def test_skill_activations_are_explicit_and_fade():
    events = [
        make_event(1, "skill.activated", {"skill": "opencode", "name": "OpenCode"}, event_id="s1"),
        make_event(2, "tool.requested", {"tool": "read", "target": "docs/x.md"}),
    ]
    cfg = _config()
    fresh = build_snapshot(events, config=cfg, now=BASE + timedelta(seconds=10))
    assert [s["name"] for s in fresh["skills"]] == ["opencode"]
    assert fresh["skills"][0]["recent"] is True
    assert fresh["skills"][0]["activation_count"] == 1
    assert "s1" in fresh["skills"][0]["evidence_event_ids"]

    expired = build_snapshot(
        events, config=cfg, now=BASE + timedelta(seconds=cfg.skill_window_seconds + 30)
    )
    assert expired["skills"][0]["recent"] is False

    # Skills never enter region evidence as a *rule-based* label.
    exploration = next(r for r in expired["regions"] if r["key"] == "code_exploration")
    assert all(e["event_id"] != "s1" for e in exploration["evidence"])


def test_no_timestamp_events_are_ignored_not_fatal():
    events = [make_event(1, "tool.requested", {"tool": "read", "target": "a.py"})]
    events[0]["occurred_at"] = None
    events[0]["received_at"] = None  # defensive: the backend always stamps received_at
    snap = build_snapshot(events, config=_config(), now=BASE)
    assert next(r for r in snap["regions"] if r["key"] == "code_exploration")["state"] == "inactive"


def test_region_evidence_rows_carry_full_explanation():
    events = [make_event(1, "tool.completed", {"tool": "shell", "command": "container-cli"})]
    snap = build_snapshot(events, config=_config(), now=BASE)
    infra = next(r for r in snap["regions"] if r["key"] == "infrastructure")
    row = infra["evidence"][0]
    assert row["basis"] == "inferred"
    assert row["rule_id"] == "command-container-cli"
    assert row["confidence"] == "high"
    assert row["cursor"] == 1


def test_expertise_config_follows_env_overrides(tmp_path, monkeypatch):
    from pathlib import Path

    from backend.app.config import Settings

    monkeypatch.setenv("OBSERVATORY_EXPERTISE_HALF_LIFE_SECONDS", "7")
    monkeypatch.setenv("OBSERVATORY_EXPERTISE_ACTIVITY_WINDOW_SECONDS", "123")
    monkeypatch.setenv("OBSERVATORY_EXPERTISE_ACTIVATE_THRESHOLD", "0.7")
    monkeypatch.setenv("OBSERVATORY_EXPERTISE_FADE_THRESHOLD", "0.2")
    monkeypatch.setenv("OBSERVATORY_EXPERTISE_EVIDENCE_PER_REGION", "9")
    monkeypatch.setenv("OBSERVATORY_EXPERTISE_SKILL_WINDOW_SECONDS", "60")
    monkeypatch.setenv("OBSERVATORY_EXPERTISE_DEBUGGING_MIN_FAILURES", "4")
    monkeypatch.setenv("OBSERVATORY_EXPERTISE_DEBUGGING_WINDOW_SECONDS", "55")
    monkeypatch.setenv("OBSERVATORY_STALENESS_THRESHOLD_SECONDS", "11")

    settings = Settings(data_dir=Path(tmp_path) / "data")
    config = ExpertiseConfig.from_settings(settings)

    assert config.half_life_seconds == 7
    assert config.activity_window_seconds == 123
    assert config.activate_threshold == 0.7
    assert config.fade_threshold == 0.2
    assert config.evidence_per_region == 9
    assert config.skill_window_seconds == 60
    assert config.debugging_min_failures == 4
    assert config.debugging_failure_window_seconds == 55
    assert config.staleness_threshold_seconds == 11
