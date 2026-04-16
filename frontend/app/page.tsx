import Link from "next/link";
import { ShieldCheck, Link2, Search, FileText } from "lucide-react";
import { RegulationsTabs } from "@/components/landing/regulations-tabs";

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">

      {/* Nav */}
      <nav className="sticky top-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-md px-8 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <ShieldCheck className="h-5 w-5 text-emerald-400" />
          <span className="font-semibold tracking-tight text-foreground">Vera</span>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="#regulations"
            className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            Regulations
          </Link>
          <Link
            href="/login"
            className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            Sign in
          </Link>
          <Link
            href="/register"
            className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 transition-colors"
          >
            Get started
          </Link>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative flex flex-col items-center justify-center text-center px-6 py-44 overflow-hidden">
        {/* Layered background: emerald glow + subtle dot grid */}
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage:
              "radial-gradient(ellipse 75% 55% at 50% -5%, rgba(52,211,153,0.13) 0%, transparent 65%), " +
              "radial-gradient(circle, rgba(255,255,255,0.025) 1px, transparent 1px)",
            backgroundSize: "100% 100%, 28px 28px",
          }}
        />

        <div className="relative z-10 flex flex-col items-center">
          <div className="mb-7 inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/8 px-4 py-1.5 text-xs font-medium text-emerald-400 tracking-widest uppercase">
            <ShieldCheck className="h-3.5 w-3.5" />
            EU AI Act · GDPR · Colorado AI Act
          </div>

          <h1 className="max-w-2xl text-4xl font-bold tracking-tight sm:text-[3.5rem] sm:leading-[1.1]">
            Every action your AI takes.{" "}
            <span className="bg-gradient-to-r from-emerald-400 to-teal-300 bg-clip-text text-transparent">
              Logged, chained, verified.
            </span>
          </h1>

          <p className="mt-7 max-w-lg text-[1rem] leading-relaxed text-muted-foreground">
            Vera creates a tamper-proof audit trail for AI agents. When something
            goes wrong — or a regulator asks — you have an immutable record of
            exactly what happened.
          </p>

          <div className="mt-10 flex items-center gap-5">
            <Link
              href="/register"
              className="rounded-lg bg-emerald-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-emerald-500 transition-colors shadow-lg shadow-emerald-500/20"
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
      <section className="border-t border-border/50 px-8 py-20">
        <div className="mx-auto max-w-4xl grid grid-cols-1 gap-5 sm:grid-cols-3">
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
              className="group rounded-xl border border-border/50 bg-card p-6 space-y-4 hover:border-emerald-500/30 transition-all duration-200"
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                <Icon className="h-5 w-5 text-emerald-400" />
              </div>
              <h3 className="font-semibold text-sm tracking-tight">{title}</h3>
              <p className="text-sm text-muted-foreground leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Why now */}
      <section className="border-t border-border/50 px-8 py-20 bg-card/20">
        <div className="mx-auto max-w-3xl">
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-400 text-center mb-4">
            Why it matters
          </p>
          <h2 className="text-2xl font-bold text-center mb-12 tracking-tight">
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
            Most teams deploying AI agents today cannot answer these.{" "}
            <span className="text-foreground font-medium">Vera makes every answer instant and provable.</span>
          </p>
        </div>
      </section>

      {/* Integrate */}
      <section className="border-t border-border/50 px-8 py-20">
        <div className="mx-auto max-w-2xl">
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-400 text-center mb-4">
            Integration
          </p>
          <h2 className="text-2xl font-bold text-center mb-10 tracking-tight">Integrate in minutes</h2>
          <div className="rounded-xl border border-border/50 bg-card overflow-hidden shadow-2xl shadow-black/30">
            {/* Terminal header */}
            <div className="flex items-center gap-1.5 border-b border-border/50 bg-muted/30 px-4 py-3">
              <span className="h-2.5 w-2.5 rounded-full bg-red-500/60" />
              <span className="h-2.5 w-2.5 rounded-full bg-amber-500/60" />
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/60" />
              <span className="ml-3 text-xs text-muted-foreground/40 font-mono">agent.py</span>
            </div>
            <div className="p-6 font-mono text-sm space-y-1 text-muted-foreground">
              <p><span className="text-emerald-400">pip install</span> vera-sdk</p>
              <p className="pt-3 text-muted-foreground/35"># Wrap your agent with one decorator</p>
              <p><span className="text-emerald-400">from</span> vera <span className="text-emerald-400">import</span> VeraClient, audit</p>
              <p className="pt-3">client = VeraClient(api_key=<span className="text-amber-400">&quot;vr_live_...&quot;</span>)</p>
              <p className="pt-3"><span className="text-violet-400">@audit</span>(action_name=<span className="text-amber-400">&quot;approve_loan&quot;</span>)</p>
              <p><span className="text-emerald-400">def</span> <span className="text-teal-300">approve_loan</span>(applicant_id, amount):</p>
              <p className="pl-6 text-muted-foreground/40">...</p>
              <p className="pt-3 text-muted-foreground/35"># Every call is now logged, hashed, and verifiable</p>
            </div>
          </div>
          <p className="mt-6 text-center text-sm text-muted-foreground">
            Works with LangChain, OpenAI, and CrewAI out of the box.
          </p>
        </div>
      </section>

      {/* Regulations */}
      <section id="regulations" className="border-t border-border/50 px-8 py-20 bg-card/20">
        <div className="mx-auto max-w-4xl">
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-400 text-center mb-4">
            Regulatory Landscape
          </p>
          <h2 className="text-2xl font-bold text-center mb-3 tracking-tight">
            Two major laws. One deadline. Both require audit trails.
          </h2>
          <p className="text-center text-sm text-muted-foreground mb-10 max-w-lg mx-auto">
            The EU AI Act and Colorado AI Act impose strict obligations on companies using AI for high-stakes decisions.
            The compliance window closes in 2026.
          </p>
          <RegulationsTabs />
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-border/50 px-8 py-24 text-center">
        <h2 className="text-2xl font-bold mb-4 tracking-tight">Ready to add a compliance layer?</h2>
        <p className="text-muted-foreground text-sm mb-9 max-w-sm mx-auto">
          Set up your organization in 30 seconds. No credit card required.
        </p>
        <div className="flex items-center justify-center gap-5">
          <Link
            href="/register"
            className="inline-flex rounded-lg bg-emerald-600 px-7 py-2.5 text-sm font-semibold text-white hover:bg-emerald-500 transition-colors shadow-lg shadow-emerald-500/20"
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
      <footer className="border-t border-border/50 px-8 py-8">
        <div className="mx-auto max-w-4xl flex flex-col items-center gap-3 text-center">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-emerald-400/50" />
            <span className="text-sm font-medium text-muted-foreground/60">Vera</span>
          </div>
          <p className="text-xs text-muted-foreground/35 max-w-lg">
            This website is a prototype built for testing and research purposes only.
            No commercial activity takes place here — no services are sold, no revenue
            is generated, and no payment is accepted or solicited.
          </p>
        </div>
      </footer>

    </div>
  );
}
