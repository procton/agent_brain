"""Expertise snapshot engine: evidence -> active/fading/inactive regions.

Scope guardrails (taken literally from AGENTS.md §9):
- region intensity is *recent observed activity*, never cognitive effort,
  proficiency, attention, or answer confidence;
- the decay function is configurable and testable with a controlled clock;
- debugging needs repeated failures (a single failed command proves nothing);
- explicit skill usage is shown ONLY from verified activation events
  (OpenCode `session.skill.activated`) and decays like everything else — there
  is no "deactivation" signal in the source, so visibility is honest fading.

Intensity math (documented contract):
    intensity(region) = sum over evidence in window of 2 ** (-age_seconds / half_life)
    state thresholds (defaults): intensity >= activate_threshold (0.5 → an
    event keeps its region "active" for ~one half-life) · then "fading" until
    fade_threshold (0.1) · below that "idle" (dim: still recent inside the
    activity window) or "inactive" when the window contains no evidence at all.
Everything is rounded to 2 decimals in the snapshot; unrounded values drive the
thresholds so `with a controlled clock` tests stay exact.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.app.classification.rules import REGION_LABELS, REGIONS, classify_event
from backend.app.schemas.base import EventKind

SKILL_EVENT_KIND: EventKind = "skill.activated"


@dataclass(frozen=True)
class ExpertiseConfig:
    """Snapshot parameters; every value is documented and override-able."""

    half_life_seconds: int = 20  # intensity halves this often while fading
    activity_window_seconds: int = 15 * 60  # older evidence is ignored entirely
    activate_threshold: float = 0.5  # one last evidence stays active ~1 half-life
    fade_threshold: float = 0.1  # below this a fading region goes dim
    evidence_per_region: int = 5
    skill_window_seconds: int = 5 * 60  # explicit skill visibility lifetime
    debugging_min_failures: int = 2  # repeated-failure rule threshold
    debugging_failure_window_seconds: int = 10 * 60
    staleness_threshold_seconds: int = 5 * 60  # "no events received" marker

    @classmethod
    def from_settings(cls, settings) -> ExpertiseConfig:
        def value(name: str, fallback):
            return getattr(settings, name, fallback)

        return cls(
            half_life_seconds=int(value("expertise_decay_half_life_seconds", cls.half_life_seconds)),
            activity_window_seconds=int(
                value("expertise_activity_window_seconds", cls.activity_window_seconds)
            ),
            activate_threshold=float(value("expertise_activate_threshold", cls.activate_threshold)),
            fade_threshold=float(value("expertise_fade_threshold", cls.fade_threshold)),
            evidence_per_region=int(value("expertise_evidence_per_region", cls.evidence_per_region)),
            skill_window_seconds=int(value("expertise_skill_window_seconds", cls.skill_window_seconds)),
            debugging_min_failures=int(
                value("expertise_debugging_min_failures", cls.debugging_min_failures)
            ),
            debugging_failure_window_seconds=int(
                value("expertise_debugging_failure_window_seconds", cls.debugging_failure_window_seconds)
            ),
            staleness_threshold_seconds=int(
                value("staleness_threshold_seconds", cls.staleness_threshold_seconds)
            ),
        )


def region_state(intensity: float, config: ExpertiseConfig) -> str:
    """Approved state vocabulary: active | fading | idle | inactive."""
    if intensity >= config.activate_threshold:
        return "active"
    if intensity > config.fade_threshold:
        return "fading"
    if 0 < intensity <= config.fade_threshold:
        return "idle"
    return "inactive"


def _as_float(event: dict) -> float:
    """Event ordering timestamp (occurred_at when present, else received_at)."""

    stamp = event.get("occurred_at") or event.get("received_at")
    if not stamp:
        raise ValueError("event without any timestamp cannot be positioned on the decay clock")
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def _decayed(kind_counts: list[tuple[float, str]], now_ts: float, config: ExpertiseConfig) -> float:
    total = 0.0
    for ts, _evidence_id in kind_counts:
        age = now_ts - ts
        if age > config.activity_window_seconds:
            continue
        total += 2 ** (-max(age, 0.0) / config.half_life_seconds)
    return total


def build_snapshot(
    events: list[dict],
    *,
    config: ExpertiseConfig,
    now: datetime,
) -> dict:
    """Aggregate normalized events into the expertise/skills snapshot.

    `events` are normalized event dicts of ONE session, any order; each must
    carry `event_id`, `cursor`, `kind`, `occurred_at`, `received_at`,
    `correlation.tool_call_id` for the debugging rule, and its sanitized
    `summary`.
    """
    now_ts = now.timestamp()
    regions_intensity: dict[str, list[tuple[float, str]]] = {region: [] for region in REGIONS}
    evidence: dict[str, list[dict]] = {region: [] for region in REGIONS}
    failures: list[tuple[float, str, str, str]] = []  # (ts, stamp, event_id, token)
    skills: dict[str, dict] = {}
    last_seen: tuple[float, str | None] = (float("-inf"), None)  # (max ts, its stamp)

    # Stable order for tie-breaking by cursor.
    ordered = sorted(events, key=lambda e: e.get("cursor") or 0)
    for event in ordered:
        try:
            ts = _as_float(event)
        except ValueError:
            continue  # timestamp-less events cannot add recent activity
        stamp = event.get("occurred_at") or event.get("received_at")
        if ts > last_seen[0]:
            last_seen = (ts, stamp)
        age = now_ts - ts
        if age > config.activity_window_seconds:
            continue
        event_id = event.get("event_id") or ""
        kind = event.get("kind")
        summary = event.get("summary") or {}

        for label in classify_event(kind, summary, evidence_event_id=event_id):
            region = label["label"]
            regions_intensity[region].append((ts, event_id))
            evidence[region].append(
                {
                    "event_id": event_id,
                    "cursor": event.get("cursor"),
                    "kind": kind,
                    "ts": event.get("occurred_at") or event.get("received_at"),
                    "tool": summary.get("tool"),
                    "target": summary.get("target"),
                    "command": summary.get("command"),
                    "basis": label["basis"],
                    "rule_id": label["rule_id"],
                    "confidence": label["confidence"],
                }
            )

        if kind == SKILL_EVENT_KIND:
            name = (summary.get("skill") or "").strip()
            if name:
                entry = skills.setdefault(
                    name,
                    {
                        "name": name,
                        "first_activated_at": event.get("occurred_at") or event.get("received_at"),
                        "last_activated_at": None,
                        "activation_count": 0,
                        "evidence_event_ids": [],
                    },
                )
                entry["activation_count"] += 1
                entry["last_activated_at"] = event.get("occurred_at") or event.get("received_at")
                entry["evidence_event_ids"].append(event_id)

        if kind == "tool.failed":
            token = summary.get("command") or summary.get("target") or "_unspecified_"
            failures.append(
                (
                    ts,
                    event.get("occurred_at") or event.get("received_at"),
                    event_id,
                    token,
                )
            )

    # Repeat-failure debugging rule (never a single failure).
    recent_failures = [f for f in failures if now_ts - f[0] <= config.debugging_failure_window_seconds]
    if len(recent_failures) >= config.debugging_min_failures:
        for ts_f, stamp, evidence_id, token in recent_failures[-config.debugging_min_failures :]:
            regions_intensity["debugging"].append((ts_f, evidence_id))
            evidence["debugging"].append(
                {
                    "event_id": evidence_id,
                    "cursor": None,
                    "kind": "tool.failed",
                    "ts": stamp,
                    "tool": token if token != "_unspecified_" else None,
                    "target": None,
                    "command": None,
                    "basis": "inferred",
                    "rule_id": "repeated-failure",
                    "confidence": "low",
                }
            )

    region_rows: list[dict] = []
    for region in REGIONS:
        intensity = min(_decayed(regions_intensity[region], now_ts, config), 4.0)
        region_evidence = sorted(
            evidence[region],
            key=lambda item: item["cursor"] or 0,
            reverse=True,
        )
        region_rows.append(
            {
                "key": region,
                "label": REGION_LABELS[region],
                "state": "inactive" if not regions_intensity[region] else region_state(intensity, config),
                "intensity": round(min(intensity, 99), 2),
                "evidence": region_evidence[: config.evidence_per_region],
                "evidence_count": len(region_evidence),
            }
        )

    skill_rows = sorted(
        (
            {
                **entry,
                "recent": (
                    now_ts
                    - _as_float({"occurred_at": entry["last_activated_at"] or entry["first_activated_at"]})
                    <= config.skill_window_seconds
                ),
            }
            for entry in skills.values()
        ),
        key=lambda entry: entry["last_activated_at"] or "",
        reverse=True,
    )

    # Staleness: measured from the LAST event of any age (view-level, honest:
    # this says "no events received lately", never "agent stopped thinking").
    last_event_at: str | None = None
    stale_seconds: int | None = None
    if last_seen[0] != float("-inf"):
        last_event_at = last_seen[1]
        stale_seconds = max(0, int(now_ts - last_seen[0]))
    stale = stale_seconds is not None and stale_seconds > config.staleness_threshold_seconds

    return {
        "schema_version": 1,
        "regions": region_rows,
        "skills": skill_rows,
        "last_event_at": last_event_at,
        "stale_seconds": stale_seconds,
        "stale": stale,
        "config": {
            "half_life_seconds": config.half_life_seconds,
            "activity_window_seconds": config.activity_window_seconds,
            "activate_threshold": config.activate_threshold,
            "fade_threshold": config.fade_threshold,
            "skill_window_seconds": config.skill_window_seconds,
            "staleness_threshold_seconds": config.staleness_threshold_seconds,
        },
        "notes": (
            "Intensity is recent observed activity, not effort or proficiency. "
            "Region evidence is rule-based inference; skills are explicit, "
            "verified activations and fade after the visible window (the source "
            "provides no explicit deactivation signal). `stale` simply means the "
            "last event is older than the staleness threshold."
        ),
    }
