// Session selector + project label + connection status.

import type { SessionView } from "../../api/types";
import { STATE_LABELS } from "../../api/types";

import type { ConnectionStatus } from "../timeline/useLiveSession";

export const STATUS_TEXT: Record<ConnectionStatus, string> = {
  loading: "loading…",
  live: "live (connected)",
  reconnecting: "reconnecting…",
  error: "error",
  auth_required: "access code required",
};

export default function SessionBar(props: {
  sessions: SessionView[];
  selected: SessionView | null;
  onSelect: (session: SessionView) => void;
  status: ConnectionStatus;
}) {
  const { sessions, selected, onSelect, status } = props;
  return (
    <header className="session-bar">
      <div className="brand">
        <span className="brand-title">Agent Activity Observatory</span>
        <span className="brand-note">
          metadata-first · local · not agent telemetry of hidden model process
        </span>
      </div>
      <div className="controls">
        {selected?.is_synthetic ? (
          <span
            className="badge badge-demo"
            title="This session contains explicitly synthetic demo data, not captured agent telemetry."
          >
            demo · synthetic data
          </span>
        ) : null}
        <label className="field">
          <span className="field-label">Session</span>
          <select
            aria-label="Select session"
            value={selected?.id ?? ""}
            onChange={(event) => {
              const found = sessions.find((s) => s.id === event.target.value);
              if (found) onSelect(found);
            }}
          >
            {sessions.length === 0 ? (
              <option value="">no sessions yet</option>
            ) : null}
            {sessions.map((session) => (
              <option key={session.id} value={session.id}>
                {session.display_title}
              </option>
            ))}
          </select>
        </label>
        {selected ? (
          <span className="badge" data-state={selected.state}>
            session: {STATE_LABELS[selected.state] ?? selected.state}
          </span>
        ) : null}
        <span className={`badge badge-${status}`} data-status={status}>
          <StatusDot status={status} /> {STATUS_TEXT[status]}
        </span>
      </div>
    </header>
  );
}

function StatusDot({ status }: { status: ConnectionStatus }) {
  return <span className="dot" aria-hidden="true" data-dot={status} />;
}
