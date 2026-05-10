#!/usr/bin/env node
/**
 * CI guard: fail the build if Clerk environment variables are missing or
 * still set to placeholder values. Wire this into the deploy pipeline (e.g.
 * a Vercel "Build Command" prefix or a GitHub Actions step) BEFORE
 * `next build` runs:
 *
 *   node scripts/check-env.mjs && next build
 *
 * Local dev with placeholder values is intentionally permitted — the
 * middleware warns loudly but lets the request through so engineers can
 * iterate on non-auth features without filling in real Clerk keys.
 */

const REQUIRED_KEYS = [
  "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
  "CLERK_SECRET_KEY",
];

const PLACEHOLDER_MARKERS = [
  "placeholder",
  "pk_test_...",
  "sk_test_...",
  "replace_before_deploy",
];

let failed = false;

for (const key of REQUIRED_KEYS) {
  const value = process.env[key] ?? "";
  if (!value) {
    console.error(`ERROR: ${key} is not set.`);
    failed = true;
    continue;
  }
  const lower = value.toLowerCase();
  if (PLACEHOLDER_MARKERS.some((m) => lower.includes(m))) {
    console.error(
      `ERROR: ${key} contains a placeholder marker. Set a real key from ` +
        `https://dashboard.clerk.com before deploying.`,
    );
    failed = true;
  }
}

if (failed) {
  console.error(
    "\nDeploy blocked. Configure real Clerk keys in your hosting provider's " +
      "environment variable settings, then re-run the build.",
  );
  process.exit(1);
}

console.log("[check-env] Clerk env vars look real. Proceeding.");
