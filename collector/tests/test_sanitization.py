"""Sanitization unit tests: unknown fields dropped, no raw commands survive."""

from __future__ import annotations

from collector.sanitization import make_summary_from_payload, sanitized_command_signature


def test_allowlisted_fields_survive():
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": "src/app.tsx"},
        "description": "reading entry point",
    }
    summary = make_summary_from_payload(payload)
    assert summary == {
        "tool": "Read",
        "target": "src/app.tsx",
        "description": "reading entry point",
    }


def test_unknown_and_sensitive_fields_dropped():
    payload = {
        "tool_name": "Bash",
        "prompt": "SECRET USER PROMPT",
        "command": "curl http://example.com/steal && echo done",
        "file_path": "src/app.py",
        "transcript": "full transcript here",
    }
    summary = make_summary_from_payload(payload)
    assert "prompt" not in summary
    assert "transcript" not in summary
    # raw command text must never appear anywhere
    assert "curl" not in str(summary)
    assert "steal" not in str(summary)
    assert summary.get("target") == "src/app.py"


def test_command_reduced_to_category_signature():
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "pytest tests/ -q --cov=x"},
    }
    summary = make_summary_from_payload(payload)
    assert summary["command"] == "pytest"
    assert "cov" not in summary["command"]


def test_interpreted_shell_is_never_stored():
    payload = {"tool_name": "Bash", "tool_input": {"command": "echo $(cat creds)"}}
    summary = make_summary_from_payload(payload)
    assert "command" not in summary


def test_command_signature_categories():
    assert sanitized_command_signature("pytest -q") == "pytest"
    assert sanitized_command_signature("git push origin main") == "git"
    assert sanitized_command_signature("docker build .") == "container-cli"
    assert sanitized_command_signature("alembic upgrade head") == "schema-migration"
    assert sanitized_command_signature("UNKNOWN_TOOL 1") is None
