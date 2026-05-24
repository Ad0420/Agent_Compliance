/**
 * /api-keys — Clerk-authenticated API key issuance UI (Workstream E4).
 *
 * Server component. Reads the active Clerk session, calls
 * `GET /v1/dashboard/api-keys` on the backend, and renders the table.
 * Interactive parts (create modal, revoke confirm) live in the
 * `<ApiKeyTable>` client island.
 *
 * Auth boundary:
 *   - No Clerk session  → render a "sign in" CTA, no backend call.
 *   - No backend membership (Clerk webhook hasn't landed yet) → show a
 *     friendly "your org is still provisioning" message.
 *   - Backend 401 → bubbled up as "session expired".
 *
 * UI gating uses the Clerk org role (`org:admin` etc) for the create/revoke
 * buttons, but the backend is the source of truth: a non-admin who somehow
 * issues a POST will get a 403 from the API.
 */
import Link from "next/link";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getClerkBackendToken,
  getClerkSessionSummary,
} from "@/lib/auth-server";
import {
  listDashboardApiKeys,
  VeraApiError,
  type DashboardApiKey,
} from "@/lib/api-server";

import { ApiKeyTable } from "./_components/api-key-table";

export const dynamic = "force-dynamic";

export default async function ApiKeysPage() {
  const session = await getClerkSessionSummary();
  if (!session) {
    return <SignInPrompt />;
  }
  // Belt-and-braces: the summary already checked userId, but ensure we have
  // a backend-bound token before attempting the call.
  const token = await getClerkBackendToken();
  if (!token) {
    return <SignInPrompt />;
  }
  if (!session.orgId) {
    return <NoActiveOrg />;
  }

  let keys: DashboardApiKey[] = [];
  let provisioning = false;
  let errorMessage: string | null = null;
  try {
    keys = await listDashboardApiKeys();
  } catch (err) {
    if (err instanceof VeraApiError) {
      if (err.status === 400 || err.status === 403) {
        // Either "No active organization in Clerk session" (400) or
        // "Not a member of this organization" (403). Both happen when the
        // organization.created webhook hasn't reached the backend yet —
        // Svix typically delivers in <2s but the user might have raced it.
        provisioning = true;
      } else if (err.status === 401) {
        errorMessage = "Your session has expired. Please sign in again.";
      } else {
        errorMessage = `Backend error (${err.status}). Try refreshing.`;
      }
    } else {
      errorMessage = "Could not reach the Vera backend.";
    }
  }

  const isAdmin = session.orgRole === "org:admin" || session.orgRole === "admin";

  return (
    <main className="mx-auto max-w-4xl space-y-6 p-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">API Keys</h1>
        <p className="text-sm text-muted-foreground">
          Generate API keys for the Vera SDK. Keys are scoped to the active Clerk
          organization.
        </p>
      </header>

      {provisioning ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Your organization is being provisioned
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>
              We&apos;re still receiving your Clerk organization details. This
              usually takes a second or two. Refresh the page in a moment.
            </p>
            <p>
              If this persists, please check the Clerk webhook configuration in
              the dashboard, or contact support.
            </p>
          </CardContent>
        </Card>
      ) : errorMessage ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Something went wrong</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-red-400">
            {errorMessage}
          </CardContent>
        </Card>
      ) : (
        <ApiKeyTable
          initialKeys={keys}
          canMint={isAdmin}
          canRevoke={isAdmin}
        />
      )}
    </main>
  );
}

function SignInPrompt() {
  return (
    <main className="mx-auto max-w-md p-6">
      <Card>
        <CardHeader>
          <CardTitle>Sign in required</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>Sign in to manage API keys for your organization.</p>
          <Link
            href="/login"
            className="text-emerald-400 underline-offset-2 hover:underline"
          >
            Go to sign-in →
          </Link>
        </CardContent>
      </Card>
    </main>
  );
}

function NoActiveOrg() {
  return (
    <main className="mx-auto max-w-md p-6">
      <Card>
        <CardHeader>
          <CardTitle>No active organization</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>
            You&apos;re signed in but no organization is selected. Use the
            organization switcher in your Clerk user menu to select or create an
            org, then return here.
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
