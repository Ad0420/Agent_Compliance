"use client";

import { OrganizationSwitcher, UserButton } from "@clerk/nextjs";
import { useChainVerification } from "@/hooks/use-verification";
import { cn } from "@/lib/utils";

/**
 * Dashboard topbar (post-E4).
 *
 * Chain-status pill on the left (unchanged) + Clerk's OrganizationSwitcher
 * and UserButton on the right. UserButton owns sign-out; there's no more
 * legacy localStorage to clear, so the bespoke Logout button is gone.
 */
export function Topbar() {
  const { data: chainStatus } = useChainVerification();

  return (
    <header className="fixed left-56 right-0 top-0 z-20 flex h-14 items-center justify-between border-b border-border bg-card/80 px-6 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        {chainStatus && (
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "h-2.5 w-2.5 rounded-full",
                chainStatus.is_valid ? "bg-emerald-400" : "bg-red-400 animate-pulse",
              )}
            />
            <span className="text-xs text-muted-foreground">
              {chainStatus.is_valid ? "Chain Intact" : "Chain Broken"}
            </span>
          </div>
        )}
      </div>
      <div className="flex items-center gap-3">
        <OrganizationSwitcher
          hidePersonal
          afterCreateOrganizationUrl="/dashboard"
          afterSelectOrganizationUrl="/dashboard"
        />
        {/* Sign-out redirect target comes from NEXT_PUBLIC_CLERK_SIGN_IN_URL
            (=/login). In Clerk v7 UserButton doesn't take a per-instance
            afterSignOutUrl prop; the provider-level fallback handles it. */}
        <UserButton />
      </div>
    </header>
  );
}
