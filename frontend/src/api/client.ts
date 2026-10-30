// Same-origin API client. Credentials never appear in URLs (cookie-based
// browser session is set by POST /api/auth/browser-session with the code in
// the request body); the collector ingest token is NEVER loaded here.

import type {
  EventsPage,
  SessionView,
  SnapshotResponse,
} from "./types";

const BASE = "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new ApiError(response.status, `request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchAuthStatus(): Promise<{ authenticated: boolean }> {
  return requestJson<{ authenticated: boolean }>("/auth/status");
}

export async function loginWithCode(code: string): Promise<void> {
  const response = await fetch(BASE + "/auth/browser-session", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ code }),
  });
  if (!response.ok) {
    throw new ApiError(
      response.status,
      response.status === 403
        ? "invalid access code"
        : `login failed (${response.status})`
    );
  }
}

export function fetchSessions(): Promise<{ sessions: SessionView[] }> {
  return requestJson<{ sessions: SessionView[]; generated_at: string }>("/sessions");
}

export function fetchSnapshot(sessionId: string): Promise<SnapshotResponse> {
  return requestJson<SnapshotResponse>(`/sessions/${encodeURIComponent(sessionId)}/snapshot`);
}

export function fetchEventsPage(
  sessionId: string,
  after: number,
  limit: number
): Promise<EventsPage> {
  return requestJson<EventsPage>(
    `/sessions/${encodeURIComponent(sessionId)}/events?after=${after}&limit=${limit}`
  );
}

export function wsUrlFor(sessionId: string): string {
  // Path-only URL with no credentials; the browser attaches the session cookie.
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${BASE}/sessions/${encodeURIComponent(sessionId)}/live`;
}
