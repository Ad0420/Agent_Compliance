import { SignIn } from "@clerk/nextjs";

// TODO(branding): The previous login page used a custom shadcn Card with
// a Vera shield logo and emerald accents. For Phase 2E we ship Clerk's
// hosted component as-is to unblock the pilot. A later pass should pipe
// the Vera brand through Clerk's `appearance` prop or build a custom
// flow with Clerk hooks (useSignIn) to match the dashboard look.
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
