import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { ProtectedRoute } from "@/components/layout/protected-route";

/**
 * Dashboard route-group layout.
 *
 * Wraps every dashboard route in a `.dashboard` scope so the dashboard-specific
 * CSS variables defined in app/globals.css (denser spacing, oxidised status
 * palette, Petrona-only serif, tighter shadows) cascade automatically.
 *
 * Phase 0 Day 1: scope wrapper only. Sidebar / Topbar / nav rewrite lands
 * Day 2 in Stream A.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <div className="dashboard">
        <Sidebar />
        <Topbar />
        <main className="ml-56 mt-14 min-h-[calc(100vh-3.5rem)] p-6">{children}</main>
      </div>
    </ProtectedRoute>
  );
}
