"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { SignIn, Show } from "@clerk/nextjs";
import { useAuth } from "@/hooks/use-auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ShieldCheck, Eye, EyeOff, AlertCircle } from "lucide-react";

// Phase 2 (narrow): the legacy API-key form is the primary auth path. Pilot
// users have working API keys in localStorage and existing tooling depends on
// the API-key flow. Clerk sign-in is exposed as a secondary "preview" path
// inside a <details> disclosure so we can dogfood it without forcing it on
// pilots. Phase 3 (E4) flips the default once the dashboard is migrated to
// Clerk-issued sessions.
export default function LoginPage() {
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim()) return;

    setLoading(true);
    setError("");
    try {
      await login(apiKey.trim());
      router.push("/dashboard");
    } catch {
      setError("Invalid API key. Check your key and try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-md space-y-4">
        <Card className="w-full">
          <CardHeader className="text-center">
            <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-lg bg-emerald-500/10">
              <ShieldCheck className="h-7 w-7 text-emerald-400" />
            </div>
            <CardTitle className="text-xl">Vera</CardTitle>
            <CardDescription>
              Enter your API key to access the audit dashboard
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="relative">
                <Input
                  type={showKey ? "text" : "password"}
                  placeholder="al_live_..."
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  className="pr-10 font-mono text-sm"
                  autoFocus
                />
                <button
                  type="button"
                  onClick={() => setShowKey(!showKey)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>

              {error && (
                <div className="flex items-center gap-2 rounded-md bg-red-500/10 p-3 text-sm text-red-400">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  {error}
                </div>
              )}

              <Button type="submit" className="w-full" disabled={loading || !apiKey.trim()}>
                {loading ? (
                  <span className="flex items-center gap-2">
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                    Connecting...
                  </span>
                ) : (
                  "Connect"
                )}
              </Button>

              <p className="text-center text-sm text-muted-foreground">
                Don&apos;t have an account?{" "}
                <Link href="/register" className="text-emerald-400 hover:text-emerald-300 underline underline-offset-4">
                  Create one
                </Link>
              </p>
            </form>

            <details className="mt-6 group">
              <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground select-none">
                Or sign in with email (preview)
              </summary>
              <div className="mt-4 flex justify-center">
                {/* Show-when-signed-out gate: <SignIn /> auto-redirects to
                    forceRedirectUrl when a Clerk session already exists.
                    /dashboard then bounces back to /login (no legacy API key
                    in localStorage), causing an infinite loop. Until E4
                    migrates the dashboard off the legacy API-key auth, only
                    mount the widget when there's no Clerk session. */}
                <Show when="signed-out">
                  <SignIn
                    path="/login"
                    routing="path"
                    signUpUrl="/register"
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
