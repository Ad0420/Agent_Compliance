import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the TriageGuard happy-path e2e.
 *
 * Two `webServer` entries: one boots the FastAPI backend on 8002 with
 * stubbed Vera + LLMs (the harness imports the canonical fakes from
 * the pytest smoke), the other boots the Next.js dev server on 3002.
 * Playwright shuts both down after the run.
 *
 * Single browser (chromium) on purpose — this is a sales-demo
 * regression test, not a cross-browser compat suite. Add more
 * projects if/when the surface justifies it.
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI
    ? [["list"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "never" }]],

  use: {
    baseURL: "http://localhost:3002",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: [
    {
      // Backend with stubs installed. `cwd` is the repo root so the
      // `simulator.customers.triageguard...` package import resolves.
      command: "python -m simulator.customers.triageguard.e2e.harness.server",
      cwd: "../../../..",
      port: 8002,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        // Match the harness defaults — set here too so the values are
        // visible in the playwright run record.
        TRIAGEGUARD_PASSKEY: "e2e-passkey-123",
        CORS_ORIGINS: "http://localhost:3002,http://127.0.0.1:3002",
        TRIAGEGUARD_REVIEW_TIMEOUT_SECONDS: "30",
        PYTHONUNBUFFERED: "1",
      },
    },
    {
      command: "npm run dev",
      cwd: "../frontend",
      port: 3002,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        NEXT_PUBLIC_TRIAGEGUARD_API_URL: "http://localhost:8002",
      },
    },
  ],
});
