import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// Routes that require an authenticated Clerk session.
// Public routes (`/`, `/login`, `/register`, `/regulations/*`) pass through.
// Phase 2E note: the existing dashboard pages still use API-key auth against
// the backend. After this middleware lands, unauthenticated browsers are
// redirected to /login by Clerk before the dashboard ever renders. The
// dashboard pages themselves are untouched in this PR — Phase 3 (E4) wires
// them up to use `getClerkBackendToken()` from `lib/auth-server.ts`.
const isProtectedRoute = createRouteMatcher([
  "/dashboard(.*)",
  "/api/protected(.*)",
]);

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
