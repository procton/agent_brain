"""Knowhow axis rules: technology tags from sanitized metadata (.py → python…).

Same honesty contract as the region rules: only allowlisted evidence, no
guessed tags, extensions never imply proficiency; verified tags come only
from exact skill-name matches on a real activation event.
"""

from __future__ import annotations

from backend.app.classification.knowhow import (
    VOCABULARY,
    classify_knowhow,
)


def names(tags: list[dict]) -> list[str]:
    return [tag["name"] for tag in tags]


def test_vocabulary_is_stable_and_nonempty():
    assert "python" in VOCABULARY
    assert len(VOCABULARY) == len(set(VOCABULARY))


def test_python_extension_is_observed_with_evidence_chain():
    tags = classify_knowhow(
        "tool.completed",
        {"tool": "edit", "target": "src/engine.py"},
        evidence_event_id="evt-1",
    )
    assert names(tags) == ["python"]
    tag = tags[0]
    assert tag["basis"] == "observed"
    assert tag["rule_id"] in {"tech-extension"}
    assert tag["confidence"] == "medium"
    assert tag["evidence_event_id"] == "evt-1"


def test_pytest_command_tags_python_with_high_confidence():
    tags = classify_knowhow(
        "tool.requested",
        {"tool": "shell", "command": "pytest"},
        evidence_event_id="evt-2",
    )
    assert names(tags) == ["python"]
    assert tags[0]["rule_id"] == "pytest-command"
    assert tags[0]["confidence"] == "high"


def test_target_and_command_merge_without_duplicates_and_keep_first_priority():
    tags = classify_knowhow(
        "tool.requested",
        {"tool": "shell", "target": "run.py", "command": "pytest"},
        evidence_event_id="evt-3",
    )
    assert names(tags) == ["python"]  # one row for the same tech
    assert tags[0]["rule_id"] == "pytest-command"  # first-match wins


def test_typescript_extension_and_container_basename_are_separate_tags():
    ts = classify_knowhow(
        "tool.completed",
        {"tool": "edit", "target": "frontend/components/checkout.tsx"},
        evidence_event_id="evt-4",
    )
    assert names(ts) == ["typescript"]

    containers = classify_knowhow(
        "tool.completed",
        {"tool": "edit", "target": "deploy/docker/Dockerfile"},
        evidence_event_id="evt-4b",
    )
    assert names(containers) == ["containers"]


def test_git_and_runtime_and_container_commands():
    tags = classify_knowhow(
        "tool.requested",
        {"tool": "shell", "command": "git"},
        evidence_event_id="evt-5",
    )
    assert names(tags) == ["git"]
    assert classify_knowhow(
        "tool.requested", {"tool": "shell", "command": "javascript-runtime"}, evidence_event_id="e"
    )[0]["name"] in ("javascript",)
    assert (
        classify_knowhow(
            "tool.requested", {"tool": "shell", "command": "container-cli"}, evidence_event_id="e"
        )[0]["name"]
        == "containers"
    )


def test_lint_format_is_deliberately_untagable():
    tags = classify_knowhow(
        "tool.requested",
        {"tool": "shell", "command": "lint-format"},
        evidence_event_id="evt-6",
    )
    assert names(tags) == []  # ruff/py/eslint are indistinguishable in the coarse token


def test_unlisted_extension_is_dropped_never_guessed():
    tags = classify_knowhow(
        "tool.requested",
        {"tool": "edit", "target": "notes/todo.txt"},
        evidence_event_id="evt-7",
    )
    assert names(tags) == []


def test_migrations_segment_tags_sql_low_confidence():
    tags = classify_knowhow(
        "tool.requested",
        {"tool": "edit", "target": "backend/migrations/0002/x.py"},
        evidence_event_id="evt-8",
    )
    assert set(names(tags)) == {"python", "sql"}
    by_name = {t["name"]: t for t in tags}
    assert by_name["sql"]["confidence"] == "low"


def test_skill_activation_only_gives_verified_tag_on_exact_vocabulary():
    verified = classify_knowhow(
        "skill.activated",
        {"skill": "python"},
        evidence_event_id="evt-s1",
    )
    assert names(verified) == ["python"]
    assert verified[0]["basis"] == "verified"

    # Non-vocabulary skill names stay in the skills list; no knowhow tag.
    nothing = classify_knowhow(
        "skill.activated",
        {"skill": "commit-writing-guidelines"},
        evidence_event_id="evt-s2",
    )
    assert names(nothing) == []


def test_session_kinds_carry_no_knowhow():
    tags = classify_knowhow(
        "session.started",
        {"tool": "read", "target": "src/main.py"},
        evidence_event_id="evt-9",
    )
    assert names(tags) == []


def test_composite_filenames_keep_their_technology():
    """Multi-dot names must still tag (longest suffix chain, not only the first)."""
    for target, expected in (
        ("src/main.test.tsx", "typescript"),
        ("src/app.module.css", "css"),
        ("scripts/build.spec.js", "javascript"),
    ):
        tags = classify_knowhow(
            "tool.completed",
            {"tool": "edit", "target": target},
            evidence_event_id="evt-10",
        )
        assert names(tags) == [expected], target


def test_dotfiles_like_d_ts_do_not_double_tag_or_skip():
    tags = classify_knowhow(
        "tool.completed",
        {"tool": "edit", "target": "src/types/app.d.ts"},
        evidence_event_id="evt-11",
    )
    assert names(tags) == ["typescript"]

    hidden = classify_knowhow(
        "tool.completed",
        {"tool": "edit", "target": "src/.hidden.py"},
        evidence_event_id="evt-12",
    )
    assert names(hidden) == ["python"]
