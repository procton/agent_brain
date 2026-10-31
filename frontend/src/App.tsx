import { useCallback, useEffect, useState } from "react";
import { fetchSessions } from "./api/client";
import type { SessionView } from "./api/types";
import SessionBar from "./features/sessions/SessionBar";
import ActivityTimeline from "./features/timeline/ActivityTimeline";
import { useLiveSession } from "./features/timeline/useLiveSession";
import ExpertiseMap from "./features/expertise-map/ExpertiseMap";
import EvidencePanel from "./features/expertise-map/EvidencePanel";
import SkillBadges from "./features/expertise-map/SkillBadges";
import { useExpertise } from "./features/expertise-map/useExpertise";
import { AccessCodeGate } from "./components/AccessCodeGate";
import { RenderingStates } from "./components/States";

export default function App() {
  const [sessions, setSessions] = useState<SessionView[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<SessionView | null>(null);

  // Region selection is per-session and derived (no reset effect): a
  // selection from another session never leaks into the current session view.
  const [selection, setSelection] = useState<{ sessionId: string; key: string } | null>(null);
  const selectedRegionKey =
    selection && selection.sessionId === selected?.id ? selection.key : null;
  const selectRegion = useCallback(
    (key: string | null) => {
      if (key === null || !selected) {
        setSelection(null);
        return;
      }
      setSelection({ sessionId: selected.id, key });
    },
    [selected]
  );

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

  // New events arrive → immediate expertise refetch; polling continues so
  // decay also progresses without traffic (fading regions must settle).
  const expertise = useExpertise(
    selected?.id ?? null,
    live.events.length,
    () => setLoadError("unauthorized")
  );

  // Region selection is per-session; a different session resets it.
  // (Derived above: no effect needed.)

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

  const expertiseRegions = expertise.snapshot?.regions ?? [];
  const selectedRegion =
    expertiseRegions.find((region) => region.key === selectedRegionKey) ?? null;

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

        <div className="main-row">
          <div className="map-column">
            <SkillBadges skills={expertise.snapshot?.skills ?? []} />
            <ExpertiseMap
              regions={expertiseRegions}
              selectedKey={selectedRegionKey}
              onSelect={selectRegion}
            />
            {expertise.error ? (
              <p className="map-notes map-error" role="status">
                Expertise snapshot unavailable ({expertise.error}) — regions show
                the last known state, not live data.
              </p>
            ) : (
              <p className="map-notes">
                {expertise.snapshot?.notes ??
                  "Regions light up from recently observed activity and fade as it ages."}
              </p>
            )}
          </div>
          <EvidencePanel region={selectedRegion} />
        </div>

        <section className="timeline-block" aria-label="Activity timeline">
          <h2 className="timeline-title">Activity timeline</h2>
          <ActivityTimeline
            events={live.events}
            hasOlderNotLoaded={live.hasOlderNotLoaded}
            status={live.status}
          />
        </section>
      </section>
    </main>
  );
}
