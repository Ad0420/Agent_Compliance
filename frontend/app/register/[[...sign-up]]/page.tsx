import { SignUp } from "@clerk/nextjs";

/**
 * Sign-up page (E4): Clerk only.
 *
 * Catch-all route segment so Clerk's sub-paths (sso-callback,
 * verify-email-address, continue, etc.) all resolve here. After sign-up the
 * Clerk webhook provisions the matching backend Organization + OrgMembership
 * rows; the user lands on /dashboard which gates on the resulting session.
 */
export default function RegisterPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <SignUp
        path="/register"
        routing="path"
        signInUrl="/login"
        forceRedirectUrl="/home"
      />
    </div>
  );
}
