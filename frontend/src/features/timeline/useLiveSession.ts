// useLiveSession: HTTP snapshot -> websocket subscribe(after=snapshot cursor)
// -> live streaming.
//
// Reconnect policy (bounded exponential backoff + jitter, capped at 10 s):
// each attempt asks the server to replay from our last delivered cursor, so a
// reconnect can only duplicate (deduped in the feed), never lose events.
// Connection status is separate from session activity — a silent socket never
// becomes fabricated telemetry.

import { useEffect, useReducer } from "react";
import { ApiError, fetchSnapshot, wsUrlFor } from "../../api/client";
import type { NormalizedEvent, SessionView, WsServerMessage } from "../../api/types";
import {
  addLiveEvents,
  applySessionUpdate,
  emptyFeed,
  loadSnapshot,
  type FeedState,
} from "./feed";

export type ConnectionStatus =
  | "loading"
  | "live"
  | "reconnecting"
  | "error"
  | "auth_required";

export interface FeedView {
  events: NormalizedEventView[];
  session: SessionView | null;
  status: ConnectionStatus;
  hasOlderNotLoaded: boolean;
  errorMessage: string | null;
}

export interface NormalizedEventView {
  event_id: string;
  cursor: number;
  kind: string;
  source_event: string;
  occurred_at: string | null;
  received_at: string;
  tool: string | null;
  target: string | null;
  project: string | null;
}

const INITIAL_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 10_000;

interface HookState {
  status: ConnectionStatus;
  error: string | null;
  feed: FeedState;
}

type HookAction =
  | { type: "snapshot"; session: SessionView; events: NormalizedEvent[]; hasOlder: boolean }
  | { type: "events"; events: NormalizedEvent[] }
  | { type: "session"; session: SessionView }
  | { type: "status"; status: ConnectionStatus }
  | { type: "error"; message: string };

function reducer(state: HookState, action: HookAction): HookState {
  switch (action.type) {
    case "snapshot":
      return {
        ...state,
        feed: loadSnapshot(state.feed, action.session, action.events, action.hasOlder),
      };
    case "events":
      return { ...state, feed: addLiveEvents(state.feed, action.events) };
    case "session":
      return { ...state, feed: applySessionUpdate(state.feed, action.session) };
    case "status":
      return state.status === action.status ? state : { ...state, status: action.status };
    case "error":
      return { ...state, error: action.message };
  }
}

function toView(event: NormalizedEvent): NormalizedEventView {
  const summary = event.summary ?? {};
  return {
    event_id: event.event_id,
    cursor: event.cursor,
    kind: event.kind,
    source_event: event.source_event,
    occurred_at: event.occurred_at,
    received_at: event.received_at,
    tool: summary.tool ?? null,
    target: summary.target ?? null,
    project: summary.project ?? null,
  };
}

export function computeFeedView(state: HookState): FeedView {
  return {
    events: state.feed.events.map(toView),
    session: state.feed.session,
    status: state.status,
    hasOlderNotLoaded: state.feed.hasOlder,
    errorMessage: state.error,
  };
}

export function useLiveSession(
  session: SessionView | null,
  enabled: boolean
): FeedView {
  const [state, dispatch] = useReducer(reducer, undefined, () => ({
    status: "loading" as ConnectionStatus,
    error: null as string | null,
    feed: emptyFeed(),
  }));

  const sessionId = session?.id ?? null;

  useEffect(() => {
    if (!enabled || sessionId === null) return;
    let disposed = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attemptNumber = 0;

    function setStatus(status: ConnectionStatus) {
      if (!disposed) dispatch({ type: "status", status });
    }

    async function loadSnapshotThenConnect() {
      try {
        const snapshot = await fetchSnapshot(sessionId as string);
        if (disposed) return;
        dispatch({
          type: "snapshot",
          session: snapshot.session,
          events: snapshot.events,
          hasOlder: snapshot.has_older_events,
        });
        lastKnownCursor = Math.max(lastKnownCursor, snapshot.latest_cursor);
      } catch (err) {
        if (disposed) return;
        if (err instanceof ApiError && err.status === 401) {
          setStatus("auth_required");
          return;
        }
        setStatus("error");
        dispatch({ type: "error", message: messageOf(err) });
        return;
      }
      scheduleConnect();
    }

    function scheduleConnect() {
      if (disposed) return;
      attemptNumber += 1;
      connect(afterCursor());
    }

    /** Resume cursor is derived from the reducer-held feed indirectly: the
     * snapshot cursor and any live `last_cursor` have been persisted inside
     * reducer state; we keep a live mirror here because dispatch is async. */
    let lastKnownCursor = 0;

    function afterCursor(): number {
      return lastKnownCursor;
    }

    function onLiveMessages(message: WsServerMessage): void {
      if (message.type === "events") {
        for (const event of message.events) {
          lastKnownCursor = Math.max(lastKnownCursor, event.cursor);
        }
        dispatch({ type: "events", events: message.events });
      } else if (message.type === "replay_done") {
        lastKnownCursor = Math.max(lastKnownCursor, message.last_cursor);
      } else if (message.type === "ready" || message.type === "session") {
        dispatch({ type: "session", session: message.session });
        if (!disposed) setStatus("live");
      }
    }

    function connect(after: number) {
      if (disposed) return;
      setStatus(attemptNumber === 1 ? "loading" : "reconnecting");
      let localSocket: WebSocket;
      try {
        localSocket = new WebSocket(wsUrlFor(sessionId as string));
      } catch {
        onError();
        return;
      }
      socket = localSocket;
      localSocket.onopen = () => {
        localSocket.send(JSON.stringify({ type: "subscribe", after }));
      };
      localSocket.onmessage = (messageEvent) => {
        if (disposed) return;
        if (typeof messageEvent.data !== "string") return;
        let message: WsServerMessage;
        try {
          message = JSON.parse(messageEvent.data) as WsServerMessage;
        } catch {
          return; // malformed server message: never invent state
        }
        if (message.type === "error") {
          if (message.detail === "dashboard session required") {
            setStatus("auth_required");
            localSocket.close();
            return;
          }
          setStatus("error");
          dispatch({ type: "error", message: message.detail });
          localSocket.close();
          return;
        }
        onLiveMessages(message);
      };
      localSocket.onclose = () => {
        onError();
      };
      localSocket.onerror = () => {
        /* close handler schedules the reconnect */
      };
    }

    function onError() {
      socket = null;
      if (disposed) return;
      const capped = Math.min(MAX_BACKOFF_MS, INITIAL_BACKOFF_MS * 2 ** attemptNumber);
      const jitter = Math.random() * capped * 0.25;
      setStatus("reconnecting");
      reconnectTimer = setTimeout(() => {
        attemptNumber += 1;
        connect(afterCursor());
      }, Math.min(MAX_BACKOFF_MS, capped + jitter));
    }

    void loadSnapshotThenConnect();

    return () => {
      disposed = true;
      if (reconnectTimer !== null) clearTimeout(reconnectTimer);
      if (socket) {
        socket.onclose = null;
        socket.onerror = null;
        socket.onmessage = null;
        socket.onopen = null;
        socket.close(1000, "component disposed");
      }
    };
  }, [sessionId, enabled]);

  return computeFeedView(state);
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) return `Backend error (${err.status})`;
  return err instanceof Error ? err.message : "unknown error";
}
