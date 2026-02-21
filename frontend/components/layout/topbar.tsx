"use client";

import { useAuth } from "@/hooks/use-auth";
import { useChainVerification } from "@/hooks/use-verification";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { LogOut } from "lucide-react";
import { cn } from "@/lib/utils";

export function Topbar() {
  const { organization, logout } = useAuth();
  const { data: chainStatus } = useChainVerification();
  const router = useRouter();

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

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
      <div className="flex items-center gap-4">
        {organization && (
          <span className="text-sm text-muted-foreground">{organization.name}</span>
        )}
        <Button variant="ghost" size="sm" onClick={handleLogout} className="text-muted-foreground">
          <LogOut className="mr-1 h-4 w-4" />
          Logout
        </Button>
      </div>
    </header>
  );
}
