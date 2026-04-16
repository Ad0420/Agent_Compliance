"use client";

import { useAuth } from "@/hooks/use-auth";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { apiKey, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !apiKey) {
      router.push("/login");
    }
  }, [apiKey, isLoading, router]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-emerald-400 border-t-transparent" />
      </div>
    );
  }

  if (!apiKey) return null;

  return <>{children}</>;
}
