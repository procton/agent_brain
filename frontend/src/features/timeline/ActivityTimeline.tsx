// Activity timeline: chronological list of observable agent events.
// Text-first, keyboard-accessible, useful without animation.

import type { NormalizedEventView } from "./useLiveSession";
import { KIND_LABELS } from "../../api/types";

export default function ActivityTimeline(props: {
  events: NormalizedEventView[];
  hasOlderNotLoaded: boolean;
  status: string;
}) {
  const { events, hasOlderNotLoaded } = props;

  if (events.length === 0) {
    return <div className="timeline-empty" role="status">No events observed for this session yet.</div>;
  }

  return (
    <section
      aria-label="Session activity timeline"
      className="timeline"
      data-testid="timeline"
    >
      {hasOlderNotLoaded ? (
        <p className="timeline-note" role="status">
          older events were not loaded in this window
        </p>
      ) : null}
      <ol className="timeline-list">
        {events.map(renderEvent)}
      </ol>
    </section>
  );
}

function renderEvent(event: NormalizedEventView) {
  const label = KIND_LABELS[event.kind] ?? event.kind;
  const detail = describe(event);
  const when = event.occurred_at ?? event.received_at;
  return (
    <li
      key={event.event_id}
      className={`timeline-item ${event.kind.replace(".", "-")}`}
      data-kind={event.kind}
      tabIndex={0}
    >
      <span className="timeline-cursor">#{event.cursor}</span>
      <span className="timeline-kind">{label}</span>
      <span className="timeline-sourceevent">{event.source_event}</span>
      <span className="timeline-detail">{detail}</span>
      {event.kind === "tool.requested" ? (
        <span className="badge badge-unresolved">unresolved</span>
      ) : null}
      {event.kind === "tool.failed" ? (
        <span className="badge badge-failed">failed</span>
      ) : null}
      <time className="timeline-time" dateTime={when ?? undefined}>
        {formatTime(when)}
      </time>
    </li>
  );
}

function describe(event: NormalizedEventView): string {
  const parts: string[] = [];
  if (event.tool) parts.push(event.tool);
  if (event.target) parts.push(event.target);
  if (event.project) parts.push(`project: ${event.project}`);
  return parts.join(" · ");
}

export function formatTime(iso: string | null): string {
  if (!iso) return "—";
  // deterministic, timezone-free display: keep the ISO instant, show local
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}
