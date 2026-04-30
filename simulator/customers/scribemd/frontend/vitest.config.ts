/**
 * Vitest config for the ScribeMD frontend hook tests.
 *
 * - happy-dom is the lightweight DOM the hooks actually need (no canvas, no
 *   layout) — RTL drives it via `renderHook`.
 * - The `@/...` alias mirrors the Next.js / tsconfig path map so existing
 *   imports in `hooks/*` resolve unchanged.
 */

import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": root,
    },
  },
  test: {
    environment: "happy-dom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["__tests__/**/*.{test,spec}.{ts,tsx}"],
  },
});
