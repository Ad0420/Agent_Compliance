"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Home, ShieldCheck, Settings, Scale, Key, Users } from "lucide-react";

// PR 12 (Phase 1 Stream F item F6) introduces /home as the real landing
// page and adds /customers as the multi-tenant first-class nav entry per
// `dashboard-design.md` §Information architecture. Order matters: Home
// (daily check) → Customers (the multi-tenant core) → Compliance (org-wide
// attestations) → API Keys (SDK plumbing) → Settings (everything else).
const NAV_ITEMS = [
  { href: "/home", label: "Home", icon: Home },
  { href: "/customers", label: "Customers", icon: Users },
  { href: "/compliance", label: "Compliance", icon: Scale },
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
          const isActive = pathname === item.href || (item.href !== "/home" && pathname.startsWith(item.href));
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
