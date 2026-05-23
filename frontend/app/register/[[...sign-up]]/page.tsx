"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { SignUp, Show } from "@clerk/nextjs";
import { useAuth } from "@/hooks/use-auth";
import { registerOrg, type RegisterResult } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ShieldCheck, Copy, Check, AlertCircle, ArrowRight } from "lucide-react";

// Phase 2 (narrow): the legacy two-step org-creation + API-key issuance flow
// is the primary path. Clerk sign-up is exposed as a secondary "preview" path
// inside a <details> disclosure. Phase 3 (E4) rebuilds API-key issuance on top
// of Clerk-authenticated sessions.
export default function RegisterPage() {
  const [orgName, setOrgName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<RegisterResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  const { login } = useAuth();
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!orgName.trim()) return;
    setLoading(true);
    setError("");
    try {
      const data = await registerOrg({ org_name: orgName.trim() });
      setResult(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Registration failed. Please try again.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = async () => {
    if (!result) return;
    await navigator.clipboard.writeText(result.api_key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleGoToDashboard = async () => {
    if (!result) return;
    await login(result.api_key);
    router.push("/dashboard");
  };

  // ── Step 2: Show the generated key ──────────────────────────────────────────
  if (result) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-4">
        <Card className="w-full max-w-lg">
          <CardHeader className="text-center">
            <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-lg bg-green-500/10">
              <ShieldCheck className="h-7 w-7 text-green-400" />
            </div>
            <CardTitle className="text-xl">You&apos;re set up</CardTitle>
            <CardDescription>
              Your organization <strong className="text-foreground">{result.org_name}</strong> is ready.
              Save your API key — it will only be shown once.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {/* Key display */}
            <div className="rounded-lg border bg-muted/40 p-4">
              <p className="mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Your API Key
              </p>
              <div className="flex items-center gap-2">
                <code className="flex-1 overflow-x-auto rounded bg-background px-3 py-2 font-mono text-sm text-foreground whitespace-nowrap border">
                  {result.api_key}
                </code>
                <button
                  onClick={handleCopy}
                  className="shrink-0 rounded-md border p-2 text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                  title="Copy to clipboard"
                >
                  {copied ? (
                    <Check className="h-4 w-4 text-green-400" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                </button>
              </div>
            </div>

            {/* Warning */}
            <div className="flex gap-2 rounded-md bg-amber-500/10 border border-amber-500/20 p-3 text-sm text-amber-400">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <span>
                This key grants full access to your audit trail. Store it in a secure secrets manager.
                It won&apos;t be shown again.
              </span>
            </div>

            {/* Confirmation checkbox */}
            <label className="flex cursor-pointer items-center gap-3 select-none">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
                className="h-4 w-4 rounded border accent-blue-500"
              />
              <span className="text-sm text-muted-foreground">
                I&apos;ve saved my API key in a safe place
              </span>
            </label>

            <Button
              onClick={handleGoToDashboard}
              disabled={!confirmed}
              className="w-full"
            >
              Go to dashboard
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ── Step 1: Enter org name ───────────────────────────────────────────────────
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-md space-y-4">
        <Card className="w-full">
          <CardHeader className="text-center">
            <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-lg bg-emerald-500/10">
              <ShieldCheck className="h-7 w-7 text-emerald-400" />
            </div>
            <CardTitle className="text-xl">Create your account</CardTitle>
            <CardDescription>
              Set up your organization to start recording AI actions
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <Input
                  type="text"
                  placeholder="Acme Corp"
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  maxLength={200}
                  autoFocus
                />
                <p className="mt-1.5 text-xs text-muted-foreground">
                  Your company or project name
                </p>
              </div>

              {error && (
                <div className="flex items-center gap-2 rounded-md bg-red-500/10 p-3 text-sm text-red-400">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  {error}
                </div>
              )}

              <Button
                type="submit"
                className="w-full"
                disabled={loading || !orgName.trim()}
              >
                {loading ? (
                  <span className="flex items-center gap-2">
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                    Creating...
                  </span>
                ) : (
                  "Create account"
                )}
              </Button>

              <p className="text-center text-sm text-muted-foreground">
                Already have an account?{" "}
                <Link href="/login" className="text-emerald-400 hover:text-emerald-300 underline underline-offset-4">
                  Sign in
                </Link>
              </p>
            </form>

            <details className="mt-6 group">
              <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground select-none">
                Or sign up with email (preview)
              </summary>
              <div className="mt-4 flex justify-center">
                {/* Show-when-signed-out gate: same reason as /login —
                    <SignUp /> auto-redirects to forceRedirectUrl when a
                    session already exists, and /dashboard bounces back here
                    without a legacy API key. See
                    app/login/[[...sign-in]]/page.tsx. */}
                <Show when="signed-out">
                  <SignUp
                    path="/register"
                    routing="path"
                    signInUrl="/login"
                    forceRedirectUrl="/dashboard"
                  />
                </Show>
              </div>
            </details>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
