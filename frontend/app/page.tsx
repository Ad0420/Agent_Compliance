import Link from "next/link";
import { ShieldCheck, Link2, Search, FileText } from "lucide-react";

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">

      {/* Nav */}
      <nav className="border-b border-border px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-blue-400" />
          <span className="font-semibold tracking-tight">Vera</span>
        </div>
        <Link
          href="/login"
          className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-500 transition-colors"
        >
          Sign in
        </Link>
      </nav>

      {/* Hero */}
      <section className="flex flex-col items-center justify-center text-center px-6 py-28 flex-1">
        <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-blue-500/30 bg-blue-500/10 px-3 py-1 text-xs text-blue-400">
          <ShieldCheck className="h-3.5 w-3.5" />
          Built for EU AI Act compliance
        </div>
        <h1 className="max-w-2xl text-4xl font-bold tracking-tight sm:text-5xl">
          Every action your AI takes.{" "}
          <span className="text-blue-400">Logged, chained, verified.</span>
        </h1>
        <p className="mt-5 max-w-xl text-base text-muted-foreground">
          Vera creates a tamper-proof audit trail for AI agents. Prove to
          regulators what your AI did — and that the record hasn&apos;t been touched.
        </p>
        <div className="mt-8 flex items-center gap-3">
          <Link
            href="/login"
            className="rounded-md bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-500 transition-colors"
          >
            Get started
          </Link>
          <a
            href="https://github.com/advikunni/Agent_Compliance"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-md border border-border px-5 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            View source
          </a>
        </div>
      </section>

      {/* Features */}
      <section className="border-t border-border px-6 py-16">
        <div className="mx-auto max-w-4xl grid grid-cols-1 gap-8 sm:grid-cols-3">
          <div className="space-y-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/10">
              <Link2 className="h-5 w-5 text-blue-400" />
            </div>
            <h3 className="font-semibold">Tamper-evident chain</h3>
            <p className="text-sm text-muted-foreground">
              Every record is SHA-256 hashed and linked to the previous one.
              Any modification breaks the chain — instantly detectable.
            </p>
          </div>
          <div className="space-y-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/10">
              <Search className="h-5 w-5 text-blue-400" />
            </div>
            <h3 className="font-semibold">Data subject lookup</h3>
            <p className="text-sm text-muted-foreground">
              Find every AI decision made about a specific person in seconds.
              Required under GDPR and EU AI Act Article 86.
            </p>
          </div>
          <div className="space-y-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/10">
              <FileText className="h-5 w-5 text-blue-400" />
            </div>
            <h3 className="font-semibold">One-click audit reports</h3>
            <p className="text-sm text-muted-foreground">
              Export a signed PDF compliance report including chain integrity
              status, checkpoints, and full action history.
            </p>
          </div>
        </div>
      </section>

      {/* Why now */}
      <section className="border-t border-border px-6 py-16">
        <div className="mx-auto max-w-3xl">
          <h2 className="text-xl font-semibold text-center mb-10">When something goes wrong, can you answer these?</h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {[
              "What exactly did the agent do, and in what order?",
              "Did a human approve that action, or did it act on its own?",
              "Has anyone modified the logs since the incident?",
              "Which users were affected by that decision?",
              "What data went in? What came out?",
              "Can you prove all of this to a regulator?",
            ].map((q) => (
              <div key={q} className="flex items-start gap-3 rounded-lg border border-border bg-card p-4">
                <span className="mt-0.5 text-red-400 text-lg leading-none">×</span>
                <p className="text-sm text-muted-foreground">{q}</p>
              </div>
            ))}
          </div>
          <p className="mt-8 text-center text-sm text-muted-foreground">
            Most teams deploying AI agents today cannot answer these. Vera makes every answer instant and provable.
          </p>
        </div>
      </section>

      {/* How it works */}
      <section className="border-t border-border px-6 py-16 bg-card/50">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-xl font-semibold mb-10">Integrate in minutes</h2>
          <div className="rounded-lg border border-border bg-card p-5 text-left font-mono text-sm text-muted-foreground space-y-1">
            <p><span className="text-blue-400">pip install</span> vera-sdk</p>
            <p className="pt-2"><span className="text-muted-foreground/50"># Wrap your agent</span></p>
            <p><span className="text-blue-400">from</span> vera <span className="text-blue-400">import</span> VeraClient, audit</p>
            <p className="pt-2">client = VeraClient(api_key=<span className="text-amber-400">&quot;al_live_...&quot;</span>)</p>
            <p className="pt-2"><span className="text-purple-400">@audit</span>(action_name=<span className="text-amber-400">&quot;approve_loan&quot;</span>)</p>
            <p><span className="text-blue-400">def</span> <span className="text-green-400">approve_loan</span>(applicant_id, amount):</p>
            <p>&nbsp;&nbsp;&nbsp;&nbsp;...</p>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border px-6 py-8 text-center space-y-2">
        <p className="text-xs text-muted-foreground/70">
          <span className="font-medium text-muted-foreground">Vera</span> &mdash; Tamper-proof audit trail for AI agents
        </p>
        <p className="text-xs text-muted-foreground/50 max-w-xl mx-auto">
          This website is a prototype built for testing and research purposes only.
          No commercial activity takes place here — no services are sold, no revenue
          is generated, and no payment is accepted or solicited.
        </p>
      </footer>

    </div>
  );
}
