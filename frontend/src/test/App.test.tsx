// App-level behavior with mocked fetch + MockWebSocket: no real backend.

import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { NormalizedEvent, SessionView } from "../api/types";
import {
  MockWebSocket,
  lastSocket,
  resetSockets,
  subscribeMessageOf,
} from "./MockWebSocket";

beforeEach(() => {
  resetSockets();
  MockWebSocket.instances = [];
  vi.stubGlobal("WebSocket", MockWebSocket);
});

afterEach(() => {
  cleanup(); // testing-library/react cannot auto-register with globals:false
  vi.unstubAllGlobals();
});

function makeSession(session: Partial<SessionView> = {}): SessionView {
  return {
    id: "sess-1",
    source: "synthetic",
    source_session_id: "synthetic-demo-0001",
    machine_id: "synthetic-demo-machine",
    is_synthetic: true,
    project_label: "demo",
    display_title: "Synthetic demo session",
    state: "turn_active",
    event_count: 2,
    first_event_at: null,
    last_activity_at: null,
    latest_cursor: 2,
    ...session,
  };
}

function makeEvent(
  index: number,
  overrides: Partial<NormalizedEvent> = {}
): NormalizedEvent {
  return {
    schema_version: 1,
    event_id: `evt-${index}`,
    cursor: index,
    machine_id: "synthetic-demo-machine",
    session_id: "synthetic-demo-0001",
    source: "synthetic",
    source_event: "PreToolUse",
    kind: "tool.requested",
    occurred_at: "2026-10-29T10:00:00.000Z",
    received_at: "2026-10-29T10:00:01.000Z",
    correlation: { tool_call_id: null, agent_id: null, parent_agent_id: null },
    summary: { tool: "Read", target: "README.md" },
    ...overrides,
  };
}

type FetchCall = { path: string; method: string };

function installFetch(routes: (call: FetchCall) => Response | undefined) {
  const fetchMock = vi.fn(async (input: string | URL | Request) => {
    const path =
      typeof input === "string"
        ? input
        : input instanceof Request
          ? input.url
          : input.toString();
    const method = input instanceof Request ? input.method : "GET";
    const parsed = new URL(path, "http://localhost");
    const response = routes({ path: parsed.pathname + parsed.search, method });
    if (response) return response;
    throw new Error(`unrouted fetch: ${method} ${parsed.pathname}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const standardSessionRoutes = () =>
  installFetch((call) => {
    if (call.path === "/api/sessions") {
      return jsonResponse({ sessions: [makeSession()], generated_at: "" });
    }
    if (call.path === "/api/sessions/sess-1/snapshot") {
      return jsonResponse({
        session: makeSession(),
        events: [makeEvent(1), makeEvent(2, { kind: 'tool.completed', source_event: 'PostToolUse' })],
        latest_cursor: 2,
        first_loaded_cursor: 1,
        has_older_events: false,
      });
    }
    return undefined;
  });

describe("App states", () => {
  it("shows loading then renders session + live status", async () => {
    standardSessionRoutes();
    render(<App />);
    await waitFor(() => {
      expect(screen.getAllByText(/Synthetic demo session/).length).toBeGreaterThan(0);
    });
    // websocket subscribe sent with snapshot high water
    await waitFor(() => expect(lastSocket().sent.length).toBeGreaterThan(0));
    const subscribe = subscribeMessageOf(lastSocket());
    expect(subscribe.after).toBe(2);

    const socket = lastSocket();
    socket.serverEmits({ type: "ready", session: makeSession() });
    socket.serverEmits({ type: "replay_done", last_cursor: 2 });
    await waitFor(() => {
      expect(screen.getByText("live (connected)")).toBeInTheDocument();
    });
    expect(await screen.findByTestId("timeline")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    // synthetic sessions are clearly labeled
    expect(screen.getAllByText(/demo · synthetic/i).length).toBeGreaterThan(0);
  });

  it("shows the useful empty state when no sessions exist", async () => {
    installFetch((call) =>
      call.path === "/api/sessions"
        ? jsonResponse({ sessions: [], generated_at: "" })
        : undefined
    );
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("No sessions yet");
    });
    expect(await screen.findByText(/observatory demo-publish/)).toBeInTheDocument();
    expect(await screen.findByText(/observatory collector --once/)).toBeInTheDocument();
    expect(screen.queryByTestId("timeline")).not.toBeInTheDocument();
  });

  it("shows an error state with retry when the backend is unreachable", async () => {
    installFetch(() => new Response("nope", { status: 503 }));
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
  });

  it("recovers history and deduplicates after refresh + live overlap", async () => {
    standardSessionRoutes();
    render(<App />);
    await waitFor(() => expect(lastSocket().sent.length).toBeGreaterThan(0));
    const socket = lastSocket();
    socket.serverEmits({ type: "ready", session: makeSession() });
    // replay overlapping the snapshot: includes a duplicate and a fresh event
    socket.serverEmits({
      type: "events",
      events: [makeEvent(2, { kind: "tool.completed", source_event: "PostToolUse" }), makeEvent(3, { kind: "tool.failed", summary: { tool: "Bash", target: "tests/" } })],
      last_cursor: 3,
      replay: true,
    });
    socket.serverEmits({ type: "replay_done", last_cursor: 3 });
    await waitFor(() => {
      const rows = screen.getAllByRole("listitem");
      expect(rows).toHaveLength(3);
    });
    // duplicate with same id but later cursor order must not create 4 rows
    socket.serverEmits({
      type: "events",
      events: [makeEvent(2)],
      last_cursor: 2,
    });
    await waitFor(() => {
      expect(screen.getAllByRole("listitem")).toHaveLength(3);
    });
  });

  it("renders unresolved and failed badges distinctly", async () => {
    standardSessionRoutes();
    render(<App />);
    await waitFor(() => expect(lastSocket().sent.length).toBeGreaterThan(0));
    const socket = lastSocket();
    socket.serverEmits({ type: "ready", session: makeSession() });
    socket.serverEmits({
      type: "events",
      events: [
        makeEvent(3, { kind: "tool.failed", summary: { tool: "Bash", target: "tests/" } }),
        makeEvent(4, { kind: "tool.completed", summary: { tool: "Bash", target: "tests/" } }),
      ],
      last_cursor: 4,
    });
    await waitFor(() => {
      expect(document.querySelectorAll(".badge-failed")).toHaveLength(1);
      expect(document.querySelectorAll(".badge-unresolved")).toHaveLength(1);
    });
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("unresolved")).toBeInTheDocument();
  });

  it("shows access code gate after an unauthorized listing", async () => {
    installFetch(() => new Response("unauthorized", { status: 401 }));
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => {
      expect(screen.getByLabelText("Access code")).toBeInTheDocument();
    });
    await user.type(screen.getByLabelText("Access code"), "abcd1234");
    expect(screen.getByRole("button", { name: "Unlock dashboard" })).toBeEnabled();
  });
});
