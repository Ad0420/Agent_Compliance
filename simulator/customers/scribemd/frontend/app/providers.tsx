"use client";

/**
 * Top-level client providers.
 *
 * Currently only wraps `AuthProvider`. There is intentionally no
 * QueryClient, Redux store, or theming provider — the data layer is plain
 * React hooks against `fetch`. Add new providers here as the app grows.
 */

import * as React from "react";

import { AuthProvider } from "@/hooks/use-auth";

export function Providers({
  children,
}: {
  children: React.ReactNode;
}): React.JSX.Element {
  return <AuthProvider>{children}</AuthProvider>;
}
