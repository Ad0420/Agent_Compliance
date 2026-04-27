"use client";

import { useState } from "react";
import { useAuth } from "@/hooks/use-auth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Copy, Check, Zap } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://your-backend-url";

function CodeBlock({ code, apiKey }: { code: string; apiKey: string }) {
  const [copied, setCopied] = useState(false);
  const filled = code.replace("YOUR_API_KEY", apiKey || "YOUR_API_KEY");

  const handleCopy = async () => {
    await navigator.clipboard.writeText(filled);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative rounded-lg bg-zinc-950 border border-zinc-800">
      <button
        onClick={handleCopy}
        className="absolute right-3 top-3 rounded p-1.5 text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 transition-colors"
        title="Copy"
      >
        {copied ? <Check className="h-3.5 w-3.5 text-green-400" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
      <pre className="overflow-x-auto p-4 pr-12 text-xs leading-relaxed text-zinc-300 font-mono whitespace-pre">
        {filled}
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
  const { apiKey } = useAuth();
  const [tab, setTab] = useState<Tab>("http");

  return (
    <Card className="border-emerald-500/20 bg-emerald-500/5">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-emerald-400" />
          <CardTitle className="text-base">Send your first action</CardTitle>
        </div>
        <p className="text-sm text-muted-foreground">
          Your audit trail is empty. Record your first AI action to get started.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
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

        <CodeBlock
          code={tab === "python" ? PYTHON_SNIPPET : HTTP_SNIPPET}
          apiKey={apiKey ?? ""}
        />

        <p className="text-xs text-muted-foreground">
          Once you run this, refresh the page to see your action appear in the table.
        </p>
      </CardContent>
    </Card>
  );
}
