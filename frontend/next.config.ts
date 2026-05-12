import { execSync } from "node:child_process";
import type { NextConfig } from "next";

// CSP that allows Clerk's components + their CAPTCHA challenge to load.
// Clerk loads its frontend bundle from `*.clerk.accounts.dev` (dev) and
// `*.clerk.com` (prod), and Clerk's bot-protection embeds a Cloudflare Turnstile
// iframe from `challenges.cloudflare.com`. The previous header set was
// `X-Frame-Options: DENY`, which broke Clerk's CAPTCHA outright. We rely on
// `frame-ancestors 'self'` here instead — it's the modern equivalent and
// supersedes `X-Frame-Options` per the CSP spec, while letting Clerk embed
// its own iframes inside our origin.
//
// `'unsafe-inline'` and `'unsafe-eval'` for `script-src` are required by both
// Next.js (chunked client bundles, Server Component hydration) and Clerk.
// Tightening these to nonce-based CSP is tracked separately.
const cspDirectives = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://*.clerk.accounts.dev https://*.clerk.com https://challenges.cloudflare.com",
  "frame-src 'self' https://*.clerk.accounts.dev https://*.clerk.com https://challenges.cloudflare.com",
  "frame-ancestors 'self'",
  "connect-src 'self' https://*.clerk.accounts.dev https://*.clerk.com https://api.clerk.com https://clerk-telemetry.com",
  "img-src 'self' data: https://*.clerk.com https://*.clerk.accounts.dev https://img.clerk.com",
  "worker-src 'self' blob:",
  "style-src 'self' 'unsafe-inline'",
  "font-src 'self' data:",
];

const securityHeaders = [
  // X-Frame-Options intentionally omitted: replaced by `frame-ancestors 'self'`
  // in the CSP above. Keeping `X-Frame-Options: DENY` would break Clerk's
  // Cloudflare-Turnstile CAPTCHA, which embeds an iframe into our pages.
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "Content-Security-Policy", value: cspDirectives.join("; ") },
];

// Resolve the last-modified timestamp of the maturity page at build time so
// the `/maturity` "last updated" stamp can't rot. We try git first (committed
// state) and fall back to "now" when git history isn't available (shallow
// clones, build environments without git, etc).
const maturityLastUpdated = (() => {
  try {
    const out = execSync("git log -1 --format=%cI -- app/maturity/page.tsx", {
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString()
      .trim();
    if (out) return out;
  } catch {
    // fall through
  }
  return new Date().toISOString();
})();

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_MATURITY_LAST_UPDATED: maturityLastUpdated,
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
