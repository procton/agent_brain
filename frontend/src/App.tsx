import { useCallback, useEffect, useState } from "react";
import { fetchSessions } from "./api/client";
import type { SessionView } from "./api/types";
import SessionBar from "./features/sessions/SessionBar";
import ActivityTimeline from "./features/timeline/ActivityTimeline";
import { useLiveSession } from "./features/timeline/useLiveSession";
import { AccessCodeGate } from "./components/AccessCodeGate";
import { RenderingStates } from "./components/States";

export default function App() {
  const [sessions, setSessions] = useState<SessionView[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<SessionView | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchSessions();
      setLoadError(null);
      setSessions(data.sessions);
      setSelected((current) => {
        if (current && data.sessions.some((s) => s.id === current.id)) {
          return current;
        }
        return data.sessions[0] ?? null;
      });
    } catch (err) {
      if (err instanceof Error && err.message.includes("401")) {
        setSessions(null);
        setSelected(null);
        setLoadError("unauthorized");
      } else {
        setLoadError(err instanceof Error ? err.message : String(err));
      }
    }
  }, []);

  useEffect(() => {
    // Data-fetch-on-mount with async state updates; `load` awaits before any
    // setState, so this cannot cascade synchronously.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    // Periodic session-list refresh: new sessions appear without a reload.
    const timer = setInterval(() => void load(), 5000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const live = useLiveSession(selected, true);

  if (loadError === "unauthorized" || live.status === "auth_required") {
    return (
      <AccessCodeGate
        onSuccess={() => load()}
        authRequired={live.status === "auth_required"}
      />
    );
  }

  if (sessions === null && loadError) {
    return <RenderingStates kind="error" detail={loadError} onRetry={() => void load()} />;
  }

  if (sessions === null) {
    return <RenderingStates kind="loading" />;
  }

  if (sessions.length === 0) {
    return <RenderingStates kind="empty" />;
  }

  if (live.status === "error") {
    return (
      <RenderingStates
        kind="error"
        detail={live.errorMessage ?? "live connection failed"}
        onRetry={() => void load()}
      />
    );
  }

  return (
    <main className="app-shell">
      <SessionBar
        sessions={sessions}
        selected={selected}
        onSelect={setSelected}
        status={live.status}
      />
      <section className="content" aria-label="Session overview">
        <div className="content-header">
          {selected ? (
            <h1 className="session-title">
              {selected.display_title}
              {selected.is_synthetic ? (
                <span
                  className="badge badge-demo"
                  title="Explicitly synthetic fixture data — not captured agent telemetry."
                >
                  demo · synthetic
                </span>
              ) : null}
              {selected.machine_id ? (
                <span className="badge">machine: {selected.machine_id}</span>
              ) : null}
            </h1>
          ) : null}
        </div>
        <ActivityTimeline
          events={live.events}
          hasOlderNotLoaded={live.hasOlderNotLoaded}
          status={live.status}
        />
      </section>
    </main>
  );
}
