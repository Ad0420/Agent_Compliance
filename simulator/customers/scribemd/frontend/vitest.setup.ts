/**
 * Global test setup.
 *
 * - Registers `@testing-library/jest-dom` matchers (toBeInTheDocument etc.)
 *   onto Vitest's `expect`.
 * - Installs a `MockEventSource` as the global `EventSource` so SSE-driven
 *   hooks can be exercised without a network. Tests can grab the live
 *   instances through `MockEventSource.instances`.
 */

import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

import { MockEventSource } from "./__tests__/helpers/mock-event-source";

// Install the EventSource mock globally. happy-dom does not ship one.
// The cast through `unknown` is to match the static-shape (CONNECTING/OPEN/CLOSED)
// of the real EventSource type without dragging the full DOM definition.
(globalThis as unknown as { EventSource: typeof MockEventSource }).EventSource =
  MockEventSource;

afterEach(() => {
  cleanup();
  MockEventSource.reset();
  vi.restoreAllMocks();
});
