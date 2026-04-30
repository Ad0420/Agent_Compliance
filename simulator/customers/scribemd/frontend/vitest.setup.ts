/**
 * Global test setup.
 *
 * - Wires `@testing-library/jest-dom` matchers into Vitest's `expect`.
 * - Replaces `globalThis.EventSource` with `MockEventSource`, a tiny stub
 *   that exposes `addEventListener`, `close`, `readyState`, and a
 *   `triggerEvent(name, data)` helper so tests can fire SSE events
 *   imperatively. The most-recent instance is exposed via
 *   `MockEventSource.instances` for tests to grab.
 * - Replaces `globalThis.fetch` with a default that throws — every test
 *   must explicitly stub fetch via `vi.fn()`. This keeps tests hermetic
 *   and surfaces forgotten stubs loudly.
 */

import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, vi } from "vitest";

type EventSourceListener = (evt: MessageEvent) => void;

class MockEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  static instances: MockEventSource[] = [];
  static last(): MockEventSource | undefined {
    return MockEventSource.instances[MockEventSource.instances.length - 1];
  }

  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSED = 2;

  readonly url: string;
  readonly withCredentials: boolean;
  readyState = 0;

  onopen: ((evt: Event) => void) | null = null;
  onerror: ((evt: Event) => void) | null = null;
  onmessage: ((evt: MessageEvent) => void) | null = null;

  private readonly listeners: Map<string, Set<EventSourceListener>> = new Map();

  constructor(url: string, init?: { withCredentials?: boolean }) {
    this.url = url;
    this.withCredentials = init?.withCredentials ?? false;
    MockEventSource.instances.push(this);
  }

  addEventListener(name: string, fn: EventSourceListener): void {
    let set = this.listeners.get(name);
    if (!set) {
      set = new Set();
      this.listeners.set(name, set);
    }
    set.add(fn);
  }

  removeEventListener(name: string, fn: EventSourceListener): void {
    this.listeners.get(name)?.delete(fn);
  }

  close(): void {
    this.readyState = MockEventSource.CLOSED;
  }

  /** Test helper — fire a named event with the given data payload. */
  triggerEvent(name: string, data: unknown): void {
    const raw = typeof data === "string" ? data : JSON.stringify(data);
    const evt = new MessageEvent(name, { data: raw });
    this.listeners.get(name)?.forEach((fn) => fn(evt));
  }

  /** Test helper — simulate the `open` SSE event. */
  triggerOpen(): void {
    this.readyState = MockEventSource.OPEN;
    if (this.onopen) this.onopen(new Event("open"));
  }

  /** Test helper — simulate a network error while the stream is live. */
  triggerError(): void {
    if (this.onerror) this.onerror(new Event("error"));
  }

  /** Test helper — simulate a clean close (readyState=CLOSED then onerror). */
  triggerCloseEnd(): void {
    this.readyState = MockEventSource.CLOSED;
    if (this.onerror) this.onerror(new Event("error"));
  }
}

// Expose globally — `useEncounterEvents` references `EventSource` directly.
(globalThis as unknown as { EventSource: typeof MockEventSource }).EventSource =
  MockEventSource;
(globalThis as unknown as { MockEventSource: typeof MockEventSource }).MockEventSource =
  MockEventSource;

beforeEach(() => {
  // Reset captured EventSource instances between tests.
  MockEventSource.instances = [];
  // Default fetch — fails loudly so tests must stub.
  globalThis.fetch = vi.fn(() => {
    throw new Error(
      "fetch was called without being stubbed — every test must vi.fn() its fetch.",
    );
  }) as unknown as typeof fetch;
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

export { MockEventSource };
