// useExpertise: polls the session expertise snapshot so the skills map stays
// near-live while the dashboard is open. The backend computes the snapshot on
// read with its own clock, so polling (not pushing) is honest here: decay is
// applied server-side at generation time.
//
// - refetches immediately when the session changes or new events arrive;
// - polls on a fixed interval otherwise (decay must progress even without new
//   events, otherwise "fading" regions would never visibly go dim);
// - switching sessions clears the previous map; a refetch triggered by event
//   traffic keeps the last good snapshot until fresh data arrives;
// - a poll failure never clears the last good snapshot — the failure banner is
//   shown inline so missing data is never silently hidden;
// - auth_required (401) surfaces through onAuthRequired, like the rest.

import { useEffect, useRef, useState } from "react";
import { ApiError, fetchExpertise } from "../../api/client";
import type { ExpertiseSnapshot } from "../../api/types";

export const EXPERTISE_POLL_MS = 2000;

export interface ExpertiseView {
  snapshot: ExpertiseSnapshot | null;
  error: string | null;
}

export function useExpertise(
  sessionId: string | null,
  eventsKey: number,
  onAuthRequired: () => void
): ExpertiseView {
  const [snapshot, setSnapshot] = useState<ExpertiseSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lastSessionId = useRef<string | null>(null);

  useEffect(() => {
    let disposed = false;

    // Reset loaded data only when the session itself changes.
    if (lastSessionId.current !== sessionId) {
      lastSessionId.current = sessionId;
      setSnapshot(null);
      setError(null);
    }
    if (sessionId === null) return;

    async function poll() {
      try {
        const data = await fetchExpertise(sessionId as string);
        if (disposed) return;
        setSnapshot(data);
        setError(null);
      } catch (err) {
        if (disposed) return;
        if (err instanceof ApiError && err.status === 401) {
          onAuthRequired();
          return;
        }
        setError(err instanceof Error ? err.message : String(err));
      }
    }

    void poll();
    const timer = setInterval(() => void poll(), EXPERTISE_POLL_MS);
    return () => {
      disposed = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, eventsKey]);

  return { snapshot, error };
}
