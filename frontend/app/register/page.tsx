import { SignUp } from "@clerk/nextjs";

// TODO(branding): The previous register page was a two-step custom flow:
// (1) collect org name -> POST /v1/orgs/register, (2) display the freshly
// minted API key with a copy/confirm gate before redirecting to /dashboard.
// Clerk now owns step 1 (account creation). The org-and-API-key issuance
// flow gets rebuilt in Phase 3 (E4) inside the dashboard using
// `getClerkBackendToken()` from `lib/auth-server.ts`. For Phase 2E we ship
// Clerk's hosted component as-is to unblock the pilot.
export default function RegisterPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <SignUp
        path="/register"
        routing="path"
        signInUrl="/login"
        forceRedirectUrl="/dashboard"
      />
    </div>
  );
}
