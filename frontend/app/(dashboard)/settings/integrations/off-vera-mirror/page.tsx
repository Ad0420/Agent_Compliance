"use client";

/**
 * Settings → Integrations → Off-Vera evidence mirror (Phase 3 Wave 3D.3).
 *
 * Configuration surface for the customer-controlled S3 bucket Vera
 * mirrors every sealed checkpoint into. The mirror is the durable,
 * authoritative copy of the evidence trail — if Vera ever became
 * unreachable, an auditor can verify the entire history against the
 * customer's own bucket without us.
 *
 * Page is admin + developer to view; admin-only to mutate.
 */

import Link from "next/link";

import { Loading } from "@/components/ui/loading";
import { S3MirrorConfigPanel } from "@/components/settings/s3-mirror-config";
import { useAuth } from "@/hooks/use-auth";

export default function OffVeraMirrorPage() {
  const { isLoading: authLoading } = useAuth();

  if (authLoading) {
    return (
      <div
        className="flex items-center gap-2 text-sm text-[color:var(--ink-2)]"
        aria-busy="true"
      >
        <Loading.Spinner label="Loading" />
        <span>Loading…</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Header />
      <Explainer />
      <S3MirrorConfigPanel />
    </div>
  );
}

function Header() {
  return (
    <div>
      <h1 className="text-2xl font-bold tracking-tight">
        Off-Vera evidence mirror
      </h1>
      <p className="text-sm text-[color:var(--ink-2)]">
        Configure the S3 bucket Vera writes sealed checkpoints into.{" "}
        <Link href="/settings/integrations" className="underline">
          Back to Integrations
        </Link>
      </p>
    </div>
  );
}

function Explainer() {
  return (
    <div className="rounded-lg border border-[color:var(--ink-4)] bg-[color:var(--paper-2)] p-4 text-sm text-[color:var(--ink-2)]">
      <p>
        Every sealed checkpoint — plus the action records under it — is
        also written to an S3 bucket your team owns. The mirror is the
        authoritative copy of your evidence trail: if Vera ever became
        unreachable, your auditor can verify the entire chain against
        your bucket without contacting us.
      </p>
      <p className="mt-2">
        Recommended: configure the mirror before any regulator-ready
        export is generated. The bucket should have Object Lock enabled
        and a retention window of at least 7 years.
      </p>
    </div>
  );
}
