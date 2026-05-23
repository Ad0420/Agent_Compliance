"use client";

import { useAuth } from "@/hooks/use-auth";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

/**
 * Gate the dashboard route group on an active Clerk session (E4 cutover).
 *
 * Was: localStorage API-key presence check. Now: Clerk session presence.
 * The API-key path is dead for human auth; SDKs still use it, but humans
 * sign in with Clerk.
 *
 * Loading state: render a spinner while Clerk hydrates the session. This is
 * a real client-side wait (Clerk's session loads after first paint) so we
 * can't avoid the flash without server-component refactors.
 */
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isLoading, isSignedIn } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isSignedIn) {
      router.push("/login");
    }
  }, [isSignedIn, isLoading, router]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-emerald-400 border-t-transparent" />
      </div>
    );
  }

  if (!isSignedIn) return null;

  return <>{children}</>;
}
