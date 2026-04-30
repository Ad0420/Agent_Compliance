"use client";

/**
 * /login — passkey splash.
 *
 * Single centered card. The nurse types a passkey, hits "Sign in",
 * and on success lands on `/triage`. No "forgot passkey" link, no
 * SSO buttons — the demo bench keeps the surface minimal so the next
 * screen (the live session) is the focal point.
 */

import * as React from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/hooks/use-auth";
import { ApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Wordmark } from "@/components/brand/Wordmark";

export default function LoginPage() {
  const { login, signedInAs, isLoading } = useAuth();
  const router = useRouter();

  const [passkey, setPasskey] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  // If we already have a session when this page mounts, bounce straight
  // to the workspace — no point asking the nurse to re-authenticate.
  React.useEffect(() => {
    if (!isLoading && signedInAs) {
      router.replace("/triage");
    }
  }, [isLoading, signedInAs, router]);

  const handleSubmit = React.useCallback(
    async (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      if (submitting) return;
      setSubmitting(true);
      setError(null);
      try {
        await login(passkey);
        router.push("/triage");
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          setError("That passkey didn't match.");
        } else {
          const msg =
            err instanceof Error
              ? err.message
              : "Something went wrong. Try again.";
          setError(msg);
        }
      } finally {
        setSubmitting(false);
      }
    },
    [login, passkey, router, submitting],
  );

  return (
    <div className="min-h-screen bg-[var(--paper)] flex flex-col items-center justify-center px-6 py-12">
      <div className="mb-10">
        <Wordmark size="xl" />
      </div>

      <Card elevation="lg" className="w-full max-w-md">
        <CardContent className="pt-8 pb-7 px-7">
          <h1
            className="font-serif text-2xl font-normal text-[var(--ink)]"
            style={{ letterSpacing: "-0.015em" }}
          >
            Sign in
          </h1>
          <p className="mt-1.5 font-sans text-sm text-[var(--ink-3)]">
            Enter your passkey to open the triage queue.
          </p>

          <form onSubmit={handleSubmit} className="mt-6 flex flex-col gap-4">
            <label className="flex flex-col gap-1.5">
              <span className="font-sans text-xs font-medium text-[var(--ink-2)]">
                Passkey
              </span>
              <Input
                type="password"
                autoComplete="current-password"
                autoFocus
                value={passkey}
                onChange={(e) => setPasskey(e.target.value)}
                disabled={submitting}
                aria-invalid={error ? "true" : undefined}
                aria-describedby={error ? "login-error" : undefined}
              />
            </label>

            {error && (
              <div
                id="login-error"
                role="alert"
                className="rounded-xl bg-[var(--crimson-soft)] px-3.5 py-2.5 font-sans text-sm text-[var(--crimson)] ring-1 ring-inset ring-[rgba(185,28,28,0.22)]"
              >
                {error}
              </div>
            )}

            <Button
              type="submit"
              variant="primary"
              size="lg"
              disabled={submitting || passkey.length === 0}
              className="w-full mt-1"
            >
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <p className="mt-7 max-w-md text-center font-sans text-sm text-[var(--ink-3)]">
        AI triage for the telehealth front door.
      </p>
    </div>
  );
}
