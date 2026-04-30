import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

/**
 * Vitest configuration for the ScribeMD frontend.
 *
 * - `happy-dom` for a fast browser-ish environment (cheap EventSource shims).
 * - Single setup file installs `@testing-library/jest-dom` matchers and a
 *   global `EventSource` mock so SSE-driven hooks can be exercised.
 * - `@/*` alias mirrors `tsconfig.json` so test files import from the same
 *   paths the app uses.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./"),
    },
  },
  test: {
    environment: "happy-dom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["__tests__/**/*.test.{ts,tsx}"],
    css: false,
  },
});
