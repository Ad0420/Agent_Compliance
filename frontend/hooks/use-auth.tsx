"use client";

import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";
import { useClerk } from "@clerk/nextjs";
import { getApiKey, setApiKey as storeApiKey, clearApiKey, getIsAdmin, setIsAdmin as storeIsAdmin } from "@/lib/auth";
import { getOrganization, getApiKeys } from "@/lib/api-client";
import type { Organization } from "@/lib/api-types";

interface AuthState {
  apiKey: string | null;
  organization: Organization | null;
  isAdmin: boolean;
  isLoading: boolean;
}

interface AuthContextValue extends AuthState {
  login: (apiKey: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const { signOut: clerkSignOut } = useClerk();
  const [state, setState] = useState<AuthState>({
    apiKey: null,
    organization: null,
    isAdmin: false,
    isLoading: true,
  });

  useEffect(() => {
    const key = getApiKey();
    if (key) {
      getOrganization()
        .then((org) => {
          setState({
            apiKey: key,
            organization: org,
            isAdmin: getIsAdmin(),
            isLoading: false,
          });
        })
        .catch(() => {
          clearApiKey();
          setState({ apiKey: null, organization: null, isAdmin: false, isLoading: false });
        });
    } else {
      setState((prev) => ({ ...prev, isLoading: false }));
    }
  }, []);

  const login = useCallback(async (apiKey: string) => {
    storeApiKey(apiKey);
    const org = await getOrganization();

    // Probe for admin access
    let isAdmin = false;
    try {
      await getApiKeys();
      isAdmin = true;
    } catch {
      isAdmin = false;
    }
    storeIsAdmin(isAdmin);

    setState({ apiKey, organization: org, isAdmin, isLoading: false });
  }, []);

  const logout = useCallback(async () => {
    // Clear the legacy API key first — this always succeeds and is what the
    // existing pilot users rely on. The Clerk signOut is best-effort: errors
    // are swallowed so a Clerk outage can't trap a user in a logged-in UI.
    clearApiKey();
    try {
      await clerkSignOut();
    } catch (e) {
      // Don't surface to UI — the legacy session is already gone, which is
      // the user's primary expectation. Log for debugging.
      console.warn("Clerk signOut failed (legacy logout still completed)", e);
    }
    setState({ apiKey: null, organization: null, isAdmin: false, isLoading: false });
  }, [clerkSignOut]);

  const contextValue: AuthContextValue = { ...state, login, logout };

  return (
    <AuthContext.Provider value={contextValue}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
