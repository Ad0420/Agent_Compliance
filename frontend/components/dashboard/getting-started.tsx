"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Copy, Check, Zap, Key } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://your-backend-url";

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative rounded-lg border border-[color:var(--ink-4)] bg-[color:var(--paper-3)]">
      <button
        onClick={handleCopy}
        className="absolute right-3 top-3 rounded p-1.5 text-[color:var(--ink-3)] transition-colors hover:bg-[color:var(--ink-5)] hover:text-[color:var(--ink)]"
        title="Copy"
      >
        {copied ? <Check className="h-3.5 w-3.5 text-[color:var(--olive)]" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
      <pre className="overflow-x-auto whitespace-pre p-4 pr-12 font-mono text-xs leading-relaxed text-[color:var(--ink)]">
        {code}
      </pre>
    </div>
  );
}

const PYTHON_SNIPPET = `# Python SDK
# pip install vera-sdk

from vera import VeraClient

client = VeraClient(
    api_url="${API_URL}",
    api_key="YOUR_API_KEY",
    agent_name="my-agent",
)

client.record_action(
    action_type="decision",
    action_name="approve_loan",
    result="success",
    authorized_by="policy-engine-v1",
)`;

const HTTP_SNIPPET = `curl -X POST ${API_URL}/v1/actions \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "agent_name": "my-agent",
    "action_type": "decision",
    "action_name": "approve_loan",
    "result": "success",
    "authorized_by": "policy-engine-v1",
    "action_timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"
  }'`;

type Tab = "python" | "http";

export function GettingStarted() {
  const [tab, setTab] = useState<Tab>("http");

  return (
    <Card className="border-[color:var(--olive)]/20 bg-[color:var(--olive-bg)]/30">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-[color:var(--olive)]" />
          <CardTitle className="text-base">Send your first action</CardTitle>
        </div>
        <p className="text-sm text-muted-foreground">
          Your audit trail is empty. Mint an API key, drop it into your SDK
          config, and record your first AI action.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Primary CTA: get a key. The SDK can't run without one. */}
        <div className="flex items-center justify-between rounded-md border bg-background px-3 py-2">
          <div className="flex items-center gap-2">
            <Key className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm">
              Don&apos;t have an API key yet? Create one to get started.
            </span>
          </div>
          <Button asChild size="sm">
            <Link href="/api-keys?create=1">Create API key →</Link>
          </Button>
        </div>

        {/* Tab switcher */}
        <div className="flex gap-1 rounded-md bg-muted p-1 w-fit">
          {(["python", "http"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
                tab === t
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {t === "python" ? "Python SDK" : "HTTP / curl"}
            </button>
          ))}
        </div>

        <CodeBlock code={tab === "python" ? PYTHON_SNIPPET : HTTP_SNIPPET} />

        <p className="text-xs text-muted-foreground">
          Replace <code className="font-mono">YOUR_API_KEY</code> with the key you minted on the
          {" "}
          <Link href="/api-keys" className="text-[color:var(--olive)] underline underline-offset-4 hover:opacity-80">
            API Keys
          </Link>
          {" "}page. Once you run this, refresh to see your action in the table.
        </p>
      </CardContent>
    </Card>
  );
}
