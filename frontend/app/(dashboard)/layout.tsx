import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { ProtectedRoute } from "@/components/layout/protected-route";

/**
 * Dashboard route-group layout.
 *
 * The `dashboard` className activates the warm-paper design tokens defined
 * in `app/globals.css` (`.dashboard { ... }`). Sidebar + Topbar + page
 * content all render inside this wrapper, so every shadcn token (bg-card,
 * text-foreground, border-border, ...) resolves to its warm-paper
 * equivalent here while non-dashboard routes (`/login`, `/api-keys`,
 * `/compliance`, etc.) continue to inherit the global `.dark` theme from
 * <html class="dark">.
 *
 * `bg-background` is the warm-paper `--paper` colour inside this scope.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <div className="dashboard min-h-screen bg-background text-foreground">
        <Sidebar />
        <Topbar />
        <main className="ml-56 mt-14 min-h-[calc(100vh-3.5rem)] p-6">{children}</main>
      </div>
    </ProtectedRoute>
  );
}
