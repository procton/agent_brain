// Pure feed state: deduplication + ordering for one session's events.
//
// The backend replay protocol can only ever duplicate (register-listener-
// before-replay), never drop, so the client owns dedup by (event_id, cursor).
// All operations are pure so they compose inside a React reducer.

import type { NormalizedEvent, SessionView } from "../../api/types";

export interface FeedState {
  events: NormalizedEvent[];
  session: SessionView | null;
  // lowest cursor the FEED actually holds (from snapshot or live)
  oldestLoadedCursor: number | null;
  // snapshot bookkeeping, set on loadSnapshot
  hasOlder: boolean;
  // cursors known contiguous: everything between floor and highWater present
  contiguous: boolean;
}

export function emptyFeed(): FeedState {
  return {
    events: [],
    session: null,
    oldestLoadedCursor: null,
    hasOlder: false,
    contiguous: true,
  };
}

/**
 * Replace state after loading a (possibly partial) HTTP snapshot.
 *
 * The snapshot covers the latest `window` events; `hasOlderEvents` marks a
 * partial start. Contiguity is claimed only when the snapshot window starts
 * at the session's true first event (hasOlderEvents=false).
 */
export function loadSnapshot(
  feed: FeedState,
  session: SessionView,
  events: NormalizedEvent[],
  hasOlderEvents: boolean
): FeedState {
  let next: FeedState = emptyFeed();
  next.session = session;
  next.hasOlder = hasOlderEvents;
  next.contiguous = !hasOlderEvents;
  // events arrive sorted; validate ordering defensively
  const ordered = [...events].sort((a, b) => a.cursor - b.cursor);
  for (const event of ordered) {
    next = insert(next, event, { connectSide: "snapshot" });
  }
  return next;
}

export function addLiveEvents(
  feed: FeedState,
  events: NormalizedEvent[]
): FeedState {
  let next = feed;
  for (const event of events) {
    next = insert(next, event, { connectSide: "live" });
  }
  return next;
}

export function applySessionUpdate(
  feed: FeedState,
  session: SessionView
): FeedState {
  return { ...feed, session };
}

/**
 * After reconnect: if our loaded range had a lower-bound gap we must ask the
 * server to replay from 0 (server skips duplicates), else from highWater.
 */
export function resumeAfter(feed: FeedState): number {
  return feed.contiguous && feed.events.length > 0 ? highWater(feed) : 0;
}

export function highWater(feed: FeedState): number {
  return feed.events.length ? feed.events[feed.events.length - 1].cursor : 0;
}

interface InsertOptions {
  connectSide: "snapshot" | "live";
}

function insert(
  feed: FeedState,
  event: NormalizedEvent,
  _options: InsertOptions
): FeedState {
  if (feed.events.some((e) => e.event_id === event.event_id)) {
    return feed; // duplicate (retry/replay race); never duplicated in the UI
  }
  if (feed.events.some((e) => e.cursor === event.cursor)) {
    return feed; // cursor already occupied by another id: suspected backend bug
  }
  // Late servers may deliver out of order after a replay/live interleaving;
  // keep cursor order stable.
  const events = insertSorted(feed.events, event);
  let contiguous = feed.contiguous;
  if (_options.connectSide === "live" && feed.events.length > 0) {
    const lastCursor = feed.events[feed.events.length - 1].cursor;
    if (event.cursor > lastCursor) {
      contiguous = false; // server delivered a NEW live event above load tail:
      // contiguity unknown again; conservatively require full replay next time
    }
  }
  return {
    ...feed,
    events,
    contiguous,
    oldestLoadedCursor:
      feed.oldestLoadedCursor === null
        ? event.cursor
        : Math.min(feed.oldestLoadedCursor, event.cursor),
  };
}

/** Binary search insertion keeping list sorted by cursor; O(n) splice insert. */
export function insertSorted(
  list: NormalizedEvent[],
  event: NormalizedEvent
): NormalizedEvent[] {
  if (!list.length || event.cursor > list[list.length - 1].cursor) {
    return [...list, event];
  }
  let low = 0;
  let high = list.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (list[mid].cursor < event.cursor) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  const copy = [...list];
  copy.splice(low, 0, event);
  return copy;
}
