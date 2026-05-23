import { SignIn } from "@clerk/nextjs";

/**
 * Sign-in page (E4): Clerk only.
 *
 * Catch-all route segment so Clerk's sub-paths (sso-callback, factor-one,
 * verify-email-address, etc.) all resolve to this same page. The widget
 * routes to the right sub-flow based on URL state.
 */
export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <SignIn
        path="/login"
        routing="path"
        signUpUrl="/register"
        forceRedirectUrl="/dashboard"
      />
    </div>
  );
}
