import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// Phase 2 scope (narrow):
// `clerkMiddleware` runs broadly (per `config.matcher` below) so Clerk's
// session context is available to any page that wants it, but `auth.protect()`
// only fires on the inner matcher below. Today that is *only* `/api/protected/*`
// — the dashboard pages still use the legacy localStorage API-key flow gated
// by `<ProtectedRoute>` in `app/(dashboard)/layout.tsx`.
//
// `/dashboard(.*)` is intentionally NOT included here. Adding Clerk's redirect
// to `/login` for `/dashboard/*` would brick existing pilot users who have a
// valid API key in localStorage but no Clerk session. The dashboard migration
// off legacy auth onto Clerk sessions is tracked as workstream E4 in
// mvp-hardening-plan.md (Phase 3).
const isProtectedRoute = createRouteMatcher([
  "/api/protected(.*)",
  // /dashboard(.*) intentionally NOT included until Phase 3 (E4) migrates
  // dashboard pages from legacy localStorage API-key auth to Clerk sessions.
  // See mvp-hardening-plan.md workstream E4.
]);

// Loud startup warning if the publishable key is missing or still a
// placeholder. We *don't* throw — that would brick local dev for engineers
// who haven't filled in `.env.local` yet, and the page-level Clerk components
// already surface a useful error. We *do* warn loudly on every middleware
// invocation so it shows up in Vercel logs immediately after deploy. CI also
// runs `scripts/check-env.mjs` to fail builds with placeholder values.
const PUB_KEY = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ?? "";
if (PUB_KEY === "" || PUB_KEY.includes("placeholder")) {
  console.warn(
    "[vera] NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is unset or contains 'placeholder'. " +
      "Clerk components will fail to mount in production. Configure real keys " +
      "in Vercel environment settings before deploy.",
  );
}

export default clerkMiddleware(async (auth, req) => {
  if (isProtectedRoute(req)) {
    await auth.protect();
  }
});

export const config = {
  matcher: [
    // Skip Next.js internals and static files
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    // Always run for API routes
    "/(api|trpc)(.*)",
  ],
};
