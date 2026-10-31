// Wire types mirroring backend/app/schemas/normalized.py (schema v1).

export interface Correlation {
  tool_call_id: string | null;
  agent_id: string | null;
  parent_agent_id: string | null;
  [key: string]: string | null | undefined;
}

export type EventKind =
  | "session.started"
  | "prompt.submitted"
  | "turn.started"
  | "tool.requested"
  | "tool.completed"
  | "tool.failed"
  | "subagent.started"
  | "subagent.completed"
  | "skill.activated"
  | "agent.notification"
  | "turn.completed"
  | "session.ended";

export interface NormalizedEvent {
  schema_version: 1;
  event_id: string;
  cursor: number;
  machine_id: string;
  session_id: string;
  source: string;
  source_event: string;
  kind: EventKind | string;
  occurred_at: string | null;
  received_at: string;
  correlation: Correlation;
  summary: Record<string, string>;
}

export type SessionState = "unknown" | "turn_active" | "turn_finished" | "ended";

export interface SessionView {
  id: string;
  source: string;
  source_session_id: string;
  machine_id: string;
  is_synthetic: boolean;
  project_label: string | null;
  display_title: string;
  state: SessionState;
  event_count: number;
  first_event_at: string | null;
  last_activity_at: string | null;
  latest_cursor: number;
}

export interface SnapshotResponse {
  session: SessionView;
  events: NormalizedEvent[];
  latest_cursor: number;
  first_loaded_cursor: number | null;
  has_older_events: boolean;
}

export interface EventsPage {
  events: NormalizedEvent[];
  has_more: boolean;
  next_after: number | null;
}

// WebSocket message shapes (server -> client)
export type WsServerMessage =
  | { type: "ready"; session: SessionView }
  | { type: "replay_done"; last_cursor: number }
  | { type: "events"; events: NormalizedEvent[]; last_cursor: number; replay?: boolean }
  | { type: "session"; session: SessionView; last_cursor: number }
  | { type: "error"; detail: string };

export const KIND_LABELS: Record<string, string> = {
  "session.started": "Session started",
  "prompt.submitted": "Prompt submitted",
  "turn.started": "Turn started",
  "tool.requested": "Tool requested",
  "tool.completed": "Tool completed",
  "tool.failed": "Tool failed",
  "subagent.started": "Subagent started",
  "subagent.completed": "Subagent completed",
  "skill.activated": "Skill activated",
  "agent.notification": "Notification",
  "turn.completed": "Turn finished",
  "session.ended": "Session ended",
};

export const STATE_LABELS: Record<string, string> = {
  unknown: "unknown",
  turn_active: "turn active",
  turn_finished: "turn finished",
  ended: "ended",
};

// ---------------------------------------------------------------------------
// Expertise/skills snapshot (GET /api/sessions/{id}/expertise)
// Mirrors backend/app/schemas/expertise.py. Region intensity is recent
// observed activity with decay — never effort, proficiency, or usage.
// ---------------------------------------------------------------------------

export type RegionState = "active" | "fading" | "idle" | "inactive";

export type LabelBasis = "observed" | "inferred";

export interface ExpertiseEvidence {
  event_id: string | null;
  cursor: number | null;
  kind: string | null;
  ts: string | null;
  tool: string | null;
  target: string | null;
  command: string | null;
  basis: LabelBasis | string;
  rule_id: string;
  confidence: string;
}

export interface ExpertiseRegion {
  key: string;
  label: string;
  state: RegionState;
  intensity: number;
  evidence: ExpertiseEvidence[];
  evidence_count: number;
}

export interface SkillActivation {
  name: string;
  first_activated_at: string | null;
  last_activated_at: string | null;
  activation_count: number;
  evidence_event_ids: string[];
  recent: boolean;
}

export interface ExpertiseSnapshot {
  schema_version: number;
  session_id: string;
  source: string;
  generated_at: string;
  regions: ExpertiseRegion[];
  skills: SkillActivation[];
  config: Record<string, number>;
  notes: string;
}
