import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the ScribeMD happy-path e2e.
 *
 * Two `webServer` entries: one boots the FastAPI backend on 8001 with
 * stubbed Vera + LLMs, the other boots the Next.js dev server on 3001.
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
    baseURL: "http://localhost:3001",
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
      // `simulator.customers.scribemd...` package import resolves.
      command: "python -m simulator.customers.scribemd.e2e.harness.server",
      cwd: "../../../..",
      port: 8001,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        // Match the harness defaults — set here too so the values are
        // visible in the playwright run record.
        SCRIBEMD_PASSKEY: "test-passkey-123",
        CORS_ORIGINS: "http://localhost:3001,http://127.0.0.1:3001",
        SCRIBEMD_APPROVAL_TIMEOUT_SECONDS: "10",
        PYTHONUNBUFFERED: "1",
      },
    },
    {
      command: "npm run dev",
      cwd: "../frontend",
      port: 3001,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        NEXT_PUBLIC_SCRIBEMD_API_URL: "http://localhost:8001",
      },
    },
  ],
});
