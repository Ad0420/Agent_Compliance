"use client";

/**
 * Settings → Integrations
 *
 * Phase 2 Wave 2C PR C3 — surfaces the org's webhook subscriptions and
 * the delivery-health panel for each. Subscription create/edit/delete is
 * out of scope here (today the SDK / API drives webhook lifecycle); this
 * page is the operator's diagnostic surface for "is my customer getting
 * the events I think they are?".
 */

import * as React from "react";
import Link from "next/link";
import { Webhook } from "lucide-react";

import { EmptyState } from "@/components/ui/empty-state";
import { IntegrationCard } from "@/components/ui/integration-card";
import { Loading } from "@/components/ui/loading";
import { WebhookHealthPanel } from "@/components/settings/webhook-health-panel";
import { useAuth } from "@/hooks/use-auth";
import { useWebhooks } from "@/hooks/use-webhooks";
import type { WebhookSubscription } from "@/lib/api-types";

function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

export default function IntegrationsPage() {
  const { isAdmin, isLoading: authLoading } = useAuth();
  const { data, isLoading, isError, error } = useWebhooks();

  if (authLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground" aria-busy="true">
        <Loading.Spinner label="Loading" />
        <span>Loading…</span>
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="space-y-6">
        <Header />
        <p className="text-sm text-muted-foreground">
          Integrations are admin-only. Ask an org admin for access.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Header />

      {isLoading ? (
        <div
          className="flex items-center gap-2 text-sm text-muted-foreground"
          aria-busy="true"
        >
          <Loading.Spinner label="Loading webhooks" />
          <span>Loading webhooks…</span>
        </div>
      ) : isError ? (
        <p className="text-sm text-muted-foreground" role="alert">
          Couldn&apos;t load webhooks
          {error instanceof Error ? ` — ${error.message}` : ""}.
        </p>
      ) : (data?.webhooks ?? []).length === 0 ? (
        <EmptyState
          title="No webhook subscriptions yet"
          subtitle="Create a subscription via the API to start receiving event deliveries. Health and delivery history will appear here."
        />
      ) : (
        <ul className="grid gap-4 lg:grid-cols-2">
          {(data?.webhooks ?? []).map((sub) => (
            <li key={sub.id}>
              <WebhookCard subscription={sub} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Header() {
  return (
    <div>
      <h1 className="text-2xl font-bold tracking-tight">Integrations</h1>
      <p className="text-sm text-muted-foreground">
        Webhook subscriptions and their delivery health.{" "}
        <Link href="/settings" className="underline">
          Back to Settings
        </Link>
      </p>
    </div>
  );
}

function WebhookCard({ subscription }: { subscription: WebhookSubscription }) {
  const host = hostnameOf(subscription.url);
  // The shipped IntegrationCard primitive renders status + description
  // inside its body; the health panel sits *below* the card so the
  // stats grid and accordion get full width without fighting the
  // 220px-min-height layout.
  return (
    <div className="flex flex-col gap-3">
      <IntegrationCard
        name={subscription.description || host}
        logo={<Webhook aria-hidden="true" className="size-5" />}
        description={`Subscribed to ${subscription.event_types.length} ${
          subscription.event_types.length === 1 ? "event" : "events"
        }: ${subscription.event_types.join(", ")}`}
        status={
          subscription.is_active
            ? { variant: "ok", label: "Enabled" }
            : { variant: "muted", label: "Disabled" }
        }
        domain={{ label: host }}
      />
      <div className="rounded-[14px] border border-[color:var(--ink-4)] bg-[color:var(--paper-2)] p-6 shadow-[var(--shadow-1)]">
        <WebhookHealthPanel webhookId={subscription.id} />
      </div>
    </div>
  );
}
