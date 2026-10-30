// Mock WebSocket for component tests.
// Manually pump messages; the test controls server frames explicitly.

import { expect, vi } from "vitest";

export class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  url: string;
  readyState = 1;
  onopen: EventListener | null = null;
  onclose: EventListener | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: EventListener | null = null;
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
    // open on the next macro task like a real handshake would
    setTimeout(() => this.onopen?.(new Event("open")), 0);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
  }

  serverEmits(message: unknown): void {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

export function lastSocket(): MockWebSocket {
  return MockWebSocket.instances[MockWebSocket.instances.length - 1];
}

export function resetSockets(): void {
  MockWebSocket.instances = [];
}

export function subscribeMessageOf(socket: MockWebSocket): { after: number } {
  const sent = JSON.parse(socket.sent[0]) as { type: string; after: number };
  expect(sent.type).toBe("subscribe");
  return sent;
}

// convenience: silent timers
export const installFakeWebSocket = () => {
  vi.stubGlobal("WebSocket", MockWebSocket);
  return {
    unstub: () => vi.unstubAllGlobals(),
  };
};
