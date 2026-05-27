"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Home, ShieldCheck, Settings, Scale, Key, Users, Inbox, FileText } from "lucide-react";

// PR 12 (Phase 1 Stream F item F6) introduces /home as the real landing
// page and adds /customers as the multi-tenant first-class nav entry per
// `dashboard-design.md` §Information architecture. Order matters: Home
// (daily check) → Customers (the multi-tenant core) → Compliance (org-wide
// attestations) → Reviews (HITL queue) → API Keys (SDK plumbing) →
// Settings (everything else).
//
// Wave 2D PR C2 adds /compliance/reviews as a top-level shortcut for the
// HITL Review queue — the page lives under /compliance to keep its URL
// breadcrumb honest, but reviewers hit it dozens of times a day so we
// surface a dedicated nav entry alongside Compliance (the section header)
// rather than burying it one click deep.
//
// Phase 4 Wave 2 PR C1 — ``/compliance`` is now the asymmetric Compliance
// Posture page (six universal dimensions: measured cards + collapsed
// awaiting-data row). The pre-Phase-4 Clerk-only reviewer page was moved
// to ``/compliance-reviewer-legacy`` so saved-view URLs keep resolving;
// it intentionally has no sidebar entry now that posture is the
// canonical Compliance landing.
// Phase 5 PR B1 adds /compliance/templates as a sibling shortcut alongside
// the existing /compliance/reviews entry. Templates are counsel-attestable
// policy artefacts; surfacing them next to the rest of the Compliance
// section keeps the IA flat and discoverable without nesting one click
// deeper. The active-state logic above already handles the
// /compliance vs /compliance/* most-specific-match shadowing.
const NAV_ITEMS = [
  { href: "/home", label: "Home", icon: Home },
  { href: "/customers", label: "Customers", icon: Users },
  { href: "/compliance", label: "Compliance", icon: Scale },
  { href: "/compliance/templates", label: "Templates", icon: FileText },
  { href: "/compliance/reviews", label: "Reviews", icon: Inbox },
  { href: "/api-keys", label: "API Keys", icon: Key },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 z-30 flex h-screen w-56 flex-col border-r border-border bg-sidebar">
      <div className="flex h-14 items-center gap-2 border-b border-border px-4">
        <ShieldCheck className="h-6 w-6 text-foreground" />
        <span className="text-base font-semibold tracking-tight">Vera</span>
      </div>
      <nav className="flex-1 space-y-1 p-3">
        {NAV_ITEMS.map((item) => {
          // /home is exact-match only — `/home` should not light up for `/homework` or any other prefix collision.
          // For everything else, only treat the link as active for the page itself or a true child route
          // (e.g. `/customers/123`), never for adjacent siblings like `/customers-archive`.
          //
          // Wave 2D C2: `/compliance/reviews` is a sibling of `/compliance` with its own nav entry.
          // If a more specific NAV_ITEMS entry matches the current pathname, this less-specific one
          // should defer (don't light up Compliance when the user is on /compliance/reviews).
          const hasMoreSpecificMatch = NAV_ITEMS.some(
            (other) =>
              other.href !== item.href &&
              other.href.startsWith(item.href + "/") &&
              (pathname === other.href ||
                pathname.startsWith(other.href + "/")),
          );
          const isActive =
            !hasMoreSpecificMatch &&
            (pathname === item.href ||
              (item.href !== "/home" && pathname.startsWith(item.href + "/")));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
              )}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-border p-3">
        <p className="text-[10px] text-muted-foreground/50">Vera v0.1.0</p>
      </div>
    </aside>
  );
}
