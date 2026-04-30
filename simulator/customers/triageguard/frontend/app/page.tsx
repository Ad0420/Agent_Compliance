"use client";

/**
 * Root redirector.
 *
 * Branches off the auth state from `useAuth`:
 *   - while the `/me` probe is in flight, render a calm splash with the
 *     wordmark and a pulsing status dot — no flash of unauthenticated UI.
 *   - once resolved, replace the route with `/triage` (signed in) or
 *     `/login` (signed out). The redirect uses `router.replace` so the
 *     splash never shows up in browser history.
 *
 * The look book has been moved to `/look` — see `app/look/page.tsx`.
 */

import * as React from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/hooks/use-auth";
import { Wordmark } from "@/components/brand/Wordmark";
import { StatusDot } from "@/components/ui/status-dot";

export default function RootRedirector() {
  const { signedInAs, isLoading } = useAuth();
  const router = useRouter();

  React.useEffect(() => {
    if (isLoading) return;
    router.replace(signedInAs ? "/triage" : "/login");
  }, [isLoading, signedInAs, router]);

  return (
    <div className="min-h-screen bg-[var(--paper)] flex items-center justify-center px-6">
      <div className="flex flex-col items-center gap-6">
        <Wordmark size="lg" />
        <StatusDot status="running" label="Loading your workspace" />
      </div>
    </div>
  );
}
