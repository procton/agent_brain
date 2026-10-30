import { describe, expect, it } from "vitest";
import type { NormalizedEvent, SessionView } from "../../api/types";
import {
  addLiveEvents,
  applySessionUpdate,
  emptyFeed,
  loadSnapshot,
  resumeAfter,
} from "./feed";

function makeEvent(index: number, cursor = index, id = `evt-${index}`): NormalizedEvent {
  return {
    schema_version: 1,
    event_id: id,
    cursor,
    machine_id: "test-machine",
    session_id: "session-a",
    source: "synthetic",
    source_event: "PreToolUse",
    kind: "tool.requested",
    occurred_at: null,
    received_at: "2026-10-29T10:00:00.000Z",
    correlation: { tool_call_id: null, agent_id: null, parent_agent_id: null },
    summary: { tool: "Read", target: "README.md" },
  };
}

function snapshotSession(overrides: Partial<SessionView> = {}): SessionView {
  return {
    id: "session-a",
    source: "synthetic",
    source_session_id: "synthetic-demo-0001",
    machine_id: "test-machine",
    is_synthetic: true,
    project_label: "demo",
    display_title: "Synthetic demo session",
    state: "turn_active",
    event_count: 3,
    first_event_at: null,
    last_activity_at: null,
    latest_cursor: 3,
    ...overrides,
  };
}

describe("feed state (pure functions)", () => {
  it("loads a snapshot and reports cursors", () => {
    let feed = emptyFeed();
    feed = loadSnapshot(feed, snapshotSession(), [makeEvent(1, 1), makeEvent(2, 3)], false);
    expect(feed.events).toHaveLength(2);
    expect(feed.contiguous).toBe(true);
  });

  it("deduplicates identical cursors and event ids", () => {
    let feed = emptyFeed();
    feed = loadSnapshot(feed, snapshotSession(), [makeEvent(1, 1)], false);
    feed = addLiveEvents(feed, [makeEvent(2, 1), makeEvent(3, 2, "other-id")]);
    expect(feed.events).toHaveLength(2);
  });

  it("drops an event whose event_id was seen with a different cursor", () => {
    let feed = emptyFeed();
    feed = loadSnapshot(feed, snapshotSession(), [makeEvent(1, 1)], false);
    feed = addLiveEvents(feed, [makeEvent(9, 42, "evt-1")]);
    expect(feed.events).toHaveLength(1);
  });

  it("inserts late low-cursor events in cursor order", () => {
    let feed = emptyFeed();
    feed = loadSnapshot(feed, snapshotSession(), [makeEvent(1, 5), makeEvent(2, 9)], false);
    feed = addLiveEvents(feed, [makeEvent(3, 7)]);
    const cursors = feed.events.map((e) => e.cursor);
    expect(cursors).toEqual([5, 7, 9]);
  });

  it("merges session metadata updates", () => {
    let feed = emptyFeed();
    feed = loadSnapshot(feed, snapshotSession(), [makeEvent(1, 1)], false);
    feed = applySessionUpdate(feed, snapshotSession({ state: "turn_finished" }));
    expect(feed.session?.state).toBe("turn_finished");
  });

  it("requires full replay when the snapshot window was partial", () => {
    let feed = emptyFeed();
    feed = loadSnapshot(feed, snapshotSession(), [makeEvent(1, 41)], true);
    expect(feed.hasOlder).toBe(true);
    expect(resumeAfter(feed)).toBe(0);
  });

  it("resumes from high water when the snapshot was complete", () => {
    let feed = emptyFeed();
    feed = loadSnapshot(
      feed,
      snapshotSession(),
      [makeEvent(1, 1), makeEvent(2, 2)],
      false
    );
    expect(resumeAfter(feed)).toBe(2);
  });

  it("keeps resumeAfter=0 after a live event arrives above the snapshot tail", () => {
    // Sample only the latest tail, then live events arrive: the loaded window
    // may now be non-contiguous with earlier history.
    let feed = emptyFeed();
    feed = loadSnapshot(feed, snapshotSession(), [makeEvent(1, 3)], false);
    feed = addLiveEvents(feed, [makeEvent(2, 7)]);
    expect(feed.contiguous).toBe(false);
    expect(resumeAfter(feed)).toBe(0);
  });
});
