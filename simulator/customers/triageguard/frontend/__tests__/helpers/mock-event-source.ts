/**
 * Minimal `EventSource` mock — enough to drive `useSessionEvents`.
 *
 * - Records every constructed instance on `MockEventSource.instances` so
 *   tests can assert URL + options and dispatch synthetic events.
 * - Supports the named `addEventListener` API the hook relies on plus the
 *   `onopen`/`onerror` shorthands.
 * - `dispatch(name, data)` wakes any matching listeners with a fake
 *   `MessageEvent`. `triggerOpen()` and `triggerError()` mimic the lifecycle
 *   callbacks.
 */

export interface MockEventSourceInit {
  withCredentials?: boolean;
}

type Listener = (event: MessageEvent) => void;

export class MockEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  static instances: MockEventSource[] = [];

  static reset(): void {
    MockEventSource.instances = [];
  }

  readonly url: string;
  readonly withCredentials: boolean;
  readyState: number = MockEventSource.CONNECTING;

  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;

  closeCalled = false;

  private listeners = new Map<string, Set<Listener>>();

  constructor(url: string, init: MockEventSourceInit = {}) {
    this.url = url;
    this.withCredentials = init.withCredentials ?? false;
    MockEventSource.instances.push(this);
  }

  addEventListener(name: string, fn: EventListenerOrEventListenerObject): void {
    const handler = typeof fn === "function" ? fn : (e: Event) => fn.handleEvent(e);
    let bucket = this.listeners.get(name);
    if (!bucket) {
      bucket = new Set();
      this.listeners.set(name, bucket);
    }
    bucket.add(handler as Listener);
  }

  removeEventListener(
    name: string,
    fn: EventListenerOrEventListenerObject,
  ): void {
    const bucket = this.listeners.get(name);
    if (!bucket) return;
    // Best-effort removal — exact identity match for direct functions only.
    if (typeof fn === "function") {
      bucket.delete(fn as Listener);
    }
  }

  close(): void {
    this.closeCalled = true;
    this.readyState = MockEventSource.CLOSED;
  }

  /** Test helpers — not part of the spec. */

  triggerOpen(): void {
    this.readyState = MockEventSource.OPEN;
    this.onopen?.(new Event("open"));
  }

  triggerError(opts: { closed?: boolean } = {}): void {
    if (opts.closed) {
      this.readyState = MockEventSource.CLOSED;
    }
    this.onerror?.(new Event("error"));
  }

  dispatch(name: string, data: unknown): void {
    const payload = typeof data === "string" ? data : JSON.stringify(data);
    const event = new MessageEvent(name, { data: payload });
    const bucket = this.listeners.get(name);
    if (bucket) {
      for (const fn of bucket) fn(event);
    }
    if (name === "message") this.onmessage?.(event);
  }
}
