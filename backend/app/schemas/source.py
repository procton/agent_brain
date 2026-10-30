"""Layer 1: sanitized source events as persisted by the local spool.

These models describe the *sanitized* envelope that the collector sends to the
backend. They are application-level contracts, not claims about any agent's
native hook payload. Raw prompts, command text, file contents and tool output
must already have been removed upstream (sanitization happens in the capture
path, before anything is written to the spool).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from backend.app.schemas.base import SCHEMA_VERSION

_NONNULL_STRING = StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
_ID_STRING = StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
_EVENT_NAME = StringConstraints(strip_whitespace=True, min_length=1, max_length=64)


class Correlation(BaseModel):
    """Correlation identifiers, populated only when source evidence supports them."""

    model_config = ConfigDict(extra="forbid")

    tool_call_id: str | None = None
    agent_id: str | None = None
    parent_agent_id: str | None = None


class SourceEvent(BaseModel):
    """One sanitized event as delivered from the spool to the backend."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = SCHEMA_VERSION
    event_id: Annotated[str, _ID_STRING]
    machine_id: Annotated[str, _ID_STRING]
    session_id: Annotated[str, _ID_STRING]
    source: Annotated[str, _EVENT_NAME]
    source_event: Annotated[str, _EVENT_NAME]
    kind: str = Field(..., description="One of EventKind")
    occurred_at: str | None = None
    recorded_at: str
    correlation: Correlation = Field(default_factory=Correlation)
    summary: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _set_schema_version(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("schema_version") in (None, "1", 1):
            data = {**data, "schema_version": SCHEMA_VERSION}
        return data

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value: str) -> str:
        from backend.app.schemas.base import EVENT_KINDS

        if value not in EVENT_KINDS:
            raise ValueError(f"unknown event kind: {value!r}")
        return value

    @field_validator("summary")
    @classmethod
    def _validate_summary(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 8:
            raise ValueError("summary must contain at most 8 keys")
        if len(value) > 0 and any(not isinstance(k, str) or not k for k in value):
            raise ValueError("summary keys must be non-empty strings")
        return value


class EventBatch(BaseModel):
    """Batch envelope posted by the collector."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    events: list[SourceEvent] = Field(..., max_length=100, min_length=1)


__all__ = [
    "Correlation",
    "SourceEvent",
    "EventBatch",
    "SCHEMA_VERSION",
]
