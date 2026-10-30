// Shared informative states: loading, error, and the useful empty state.
// The empty state explains exactly what to do next (per AGENT.md), pointing at
// the synthetic demo workflow — no fabricated live data is ever shown here.

export function RenderingStates(props: {
  kind: "loading" | "empty" | "error";
  detail?: string;
  onRetry?: () => void;
}) {
  const { kind, detail, onRetry } = props;
  if (kind === "loading") {
    return (
      <div className="state state-loading" role="status">
        <h1>Loading sessions…</h1>
        <p>Connecting to the local observatory backend.</p>
      </div>
    );
  }
  if (kind === "error") {
    return (
      <div className="state state-error" role="alert">
        <h1>Observatory unavailable</h1>
        <p>{detail ?? "The local backend could not be reached."}</p>
        <ul>
          <li>Check that the backend is running: <code>observatory doctor</code></li>
          <li>Wait for the page to retry automatically, or press Retry.</li>
        </ul>
        {onRetry ? (
          <button type="button" onClick={onRetry}>
            Retry
          </button>
        ) : null}
      </div>
    );
  }
  return (
    <div className="state state-empty" role="status">
      <h1>No sessions yet</h1>
      <p>
        The dashboard shows sessions that arrive through the local event spool.
        Nothing has been captured yet.
      </p>
      <ol>
        <li>
          Generate a demo session without any agent installed:{" "}
          <code>observatory demo-publish</code>
        </li>
        <li>
          Deliver it to the backend:{" "}
          <code>observatory collector --once</code>
        </li>
        <li>Reload this page to see the synthetic demo session.</li>
      </ol>
      <p className="state-note">
        Real agent capture (Claude Code hooks) is a later milestone — this slice
        is validated with explicitly synthetic events.
      </p>
    </div>
  );
}
