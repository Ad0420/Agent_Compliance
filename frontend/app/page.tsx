import Link from "next/link";
import { ShieldCheck, Link2, Search, FileText } from "lucide-react";

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">

      {/* Nav */}
      <nav className="sticky top-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-sm px-8 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <ShieldCheck className="h-5 w-5 text-blue-400" />
          <span className="font-semibold tracking-tight text-foreground">Vera</span>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/login"
            className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            Sign in
          </Link>
          <Link
            href="/register"
            className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-500 transition-colors"
          >
            Get started
          </Link>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative flex flex-col items-center justify-center text-center px-6 py-36 overflow-hidden">
        {/* Glow */}
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(ellipse 70% 40% at 50% 0%, rgba(59,130,246,0.12), transparent)",
          }}
        />

        <div className="relative z-10 flex flex-col items-center">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-blue-500/30 bg-blue-500/10 px-3.5 py-1 text-xs font-medium text-blue-400 tracking-wide">
            <ShieldCheck className="h-3.5 w-3.5" />
            EU AI Act · GDPR · Colorado AI Act
          </div>

          <h1 className="max-w-2xl text-4xl font-bold tracking-tight sm:text-[3.25rem] sm:leading-[1.15]">
            Every action your AI takes.{" "}
            <span className="text-blue-400">Logged, chained, verified.</span>
          </h1>

          <p className="mt-6 max-w-lg text-base leading-relaxed text-muted-foreground">
            Vera creates a tamper-proof audit trail for AI agents. When something
            goes wrong — or a regulator asks — you have an immutable record of
            exactly what happened.
          </p>

          <div className="mt-9 flex items-center gap-4">
            <Link
              href="/register"
              className="rounded-md bg-blue-600 px-6 py-2.5 text-sm font-medium text-white hover:bg-blue-500 transition-colors shadow-lg shadow-blue-500/20"
            >
              Get started free
            </Link>
            <Link
              href="/login"
              className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              Sign in →
            </Link>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="border-t border-border/60 px-8 py-20">
        <div className="mx-auto max-w-4xl grid grid-cols-1 gap-6 sm:grid-cols-3">
          {[
            {
              icon: Link2,
              title: "Tamper-evident chain",
              desc: "Every record is SHA-256 hashed and linked to the previous one. Any modification breaks the chain — instantly detectable.",
            },
            {
              icon: Search,
              title: "Data subject lookup",
              desc: "Find every AI decision made about a specific person in seconds. Required under GDPR and EU AI Act Article 86.",
            },
            {
              icon: FileText,
              title: "One-click audit reports",
              desc: "Export a signed PDF compliance report with chain integrity status, checkpoints, and full action history.",
            },
          ].map(({ icon: Icon, title, desc }) => (
            <div
              key={title}
              className="rounded-xl border border-border/60 bg-card/60 p-6 space-y-4 hover:border-blue-500/30 hover:bg-card transition-all duration-200"
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/10 border border-blue-500/20">
                <Icon className="h-5 w-5 text-blue-400" />
              </div>
              <h3 className="font-semibold text-sm">{title}</h3>
              <p className="text-sm text-muted-foreground leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Why now */}
      <section className="border-t border-border/60 px-8 py-20 bg-card/30">
        <div className="mx-auto max-w-3xl">
          <p className="text-xs font-semibold uppercase tracking-widest text-blue-400 text-center mb-4">
            Why it matters
          </p>
          <h2 className="text-2xl font-bold text-center mb-12">
            When something goes wrong, can you answer these?
          </h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {[
              "What exactly did the agent do, and in what order?",
              "Did a human approve that action, or did it act on its own?",
              "Has anyone modified the logs since the incident?",
              "Which users were affected by that decision?",
              "What data went in? What came out?",
              "Can you prove all of this to a regulator?",
            ].map((q) => (
              <div
                key={q}
                className="flex items-start gap-3 rounded-lg border border-red-500/20 bg-red-500/5 px-4 py-3.5"
              >
                <span className="mt-0.5 shrink-0 text-red-400 font-bold text-sm">✕</span>
                <p className="text-sm text-muted-foreground">{q}</p>
              </div>
            ))}
          </div>
          <p className="mt-10 text-center text-sm text-muted-foreground max-w-md mx-auto">
            Most teams deploying AI agents today cannot answer these.
            <span className="text-foreground font-medium"> Vera makes every answer instant and provable.</span>
          </p>
        </div>
      </section>

      {/* Integrate */}
      <section className="border-t border-border/60 px-8 py-20">
        <div className="mx-auto max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-widest text-blue-400 text-center mb-4">
            Integration
          </p>
          <h2 className="text-2xl font-bold text-center mb-10">Integrate in minutes</h2>
          <div className="rounded-xl border border-border/60 bg-card overflow-hidden shadow-xl shadow-black/20">
            {/* Terminal header */}
            <div className="flex items-center gap-1.5 border-b border-border/60 bg-card/80 px-4 py-3">
              <span className="h-3 w-3 rounded-full bg-red-500/70" />
              <span className="h-3 w-3 rounded-full bg-amber-500/70" />
              <span className="h-3 w-3 rounded-full bg-green-500/70" />
              <span className="ml-3 text-xs text-muted-foreground/50 font-mono">agent.py</span>
            </div>
            <div className="p-6 font-mono text-sm space-y-1 text-muted-foreground">
              <p><span className="text-blue-400">pip install</span> vera-sdk</p>
              <p className="pt-3 text-muted-foreground/40"># Wrap your agent with one decorator</p>
              <p><span className="text-blue-400">from</span> vera <span className="text-blue-400">import</span> VeraClient, audit</p>
              <p className="pt-3">client = VeraClient(api_key=<span className="text-amber-400">&quot;al_live_...&quot;</span>)</p>
              <p className="pt-3"><span className="text-purple-400">@audit</span>(action_name=<span className="text-amber-400">&quot;approve_loan&quot;</span>)</p>
              <p><span className="text-blue-400">def</span> <span className="text-green-400">approve_loan</span>(applicant_id, amount):</p>
              <p className="pl-6 text-muted-foreground/60">...</p>
              <p className="pt-3 text-muted-foreground/40"># Every call is now logged, hashed, and verifiable</p>
            </div>
          </div>
          <p className="mt-6 text-center text-sm text-muted-foreground">
            Works with LangChain, OpenAI, and CrewAI out of the box.
          </p>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-border/60 px-8 py-20 text-center">
        <h2 className="text-2xl font-bold mb-4">Ready to add a compliance layer?</h2>
        <p className="text-muted-foreground text-sm mb-8 max-w-sm mx-auto">
          Set up your organization in 30 seconds. No credit card required.
        </p>
        <div className="flex items-center justify-center gap-4">
          <Link
            href="/register"
            className="inline-flex rounded-md bg-blue-600 px-6 py-2.5 text-sm font-medium text-white hover:bg-blue-500 transition-colors shadow-lg shadow-blue-500/20"
          >
            Get started free
          </Link>
          <Link
            href="/login"
            className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            Sign in →
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border/60 px-8 py-8">
        <div className="mx-auto max-w-4xl flex flex-col items-center gap-3 text-center">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-blue-400/60" />
            <span className="text-sm font-medium text-muted-foreground/70">Vera</span>
          </div>
          <p className="text-xs text-muted-foreground/40 max-w-lg">
            This website is a prototype built for testing and research purposes only.
            No commercial activity takes place here — no services are sold, no revenue
            is generated, and no payment is accepted or solicited.
          </p>
        </div>
      </footer>

    </div>
  );
}
