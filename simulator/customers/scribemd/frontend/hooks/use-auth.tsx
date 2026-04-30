"use client";

/**
 * `AuthProvider` + `useAuth` — the only place we keep the
 * "is the clinician signed in?" flag.
 *
 * - On mount, the provider probes `/api/auth/me` once. While that request is
 *   in flight, `isLoading` is `true` and `signedInAs` is `null`.
 * - The provider does **not** redirect. The view layer owns redirect logic;
 *   we only expose state.
 */

import * as React from "react";

import { login as apiLogin, logout as apiLogout, me as apiMe } from "@/lib/api/auth";

interface AuthContextValue {
  signedInAs: string | null;
  isLoading: boolean;
  login(passkey: string): Promise<void>;
  logout(): Promise<void>;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

export function AuthProvider({
  children,
}: {
  children: React.ReactNode;
}): React.JSX.Element {
  const [signedInAs, setSignedInAs] = React.useState<string | null>(null);
  const [isLoading, setIsLoading] = React.useState<boolean>(true);

  // Initial /me probe. Run once on mount; the dep array is intentionally empty.
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const who = await apiMe();
        if (!cancelled) setSignedInAs(who);
      } catch {
        // Network errors during the probe are treated as "not signed in".
        // We deliberately swallow rather than expose — the view layer
        // re-tries via login().
        if (!cancelled) setSignedInAs(null);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = React.useCallback(async (passkey: string) => {
    await apiLogin(passkey);
    // Cookie is now set; resolve the user name from the server so we don't
    // have to bake the display string into the login response.
    const who = await apiMe();
    setSignedInAs(who);
  }, []);

  const logout = React.useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      // Always drop local state — even if the server call fails, the user
      // intends to be logged out.
      setSignedInAs(null);
    }
  }, []);

  const value = React.useMemo<AuthContextValue>(
    () => ({ signedInAs, isLoading, login, logout }),
    [signedInAs, isLoading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = React.useContext(AuthContext);
  if (!ctx) {
    throw new Error(
      "useAuth must be used within an <AuthProvider />. Wrap your tree in app/providers.tsx.",
    );
  }
  return ctx;
}
