"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ShieldCheck, Eye, EyeOff, AlertCircle } from "lucide-react";

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
      router.push("/");
    } catch {
      setError("Invalid API key. Check your key and try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-lg bg-blue-500/10">
            <ShieldCheck className="h-7 w-7 text-blue-400" />
          </div>
          <CardTitle className="text-xl">Action Ledger</CardTitle>
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

            <p className="text-center text-xs text-muted-foreground">
              Get your API key by running{" "}
              <code className="rounded bg-accent px-1 py-0.5 font-mono text-[11px]">
                python setup_local.py
              </code>
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
