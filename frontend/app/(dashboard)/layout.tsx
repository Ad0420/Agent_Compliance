import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { ProtectedRoute } from "@/components/layout/protected-route";
import { OnboardingWizardProvider } from "@/hooks/use-onboarding-wizard";
import { OnboardingWizard } from "@/components/wizard/onboarding-wizard";

/**
 * Dashboard route-group layout.
 *
 * The `dashboard` className activates the warm-paper design tokens defined
 * in `app/globals.css` (`.dashboard { ... }`). Sidebar + Topbar + page
 * content all render inside this wrapper, so every shadcn token (bg-card,
 * text-foreground, border-border, ...) resolves to its warm-paper
 * equivalent here while non-dashboard routes (`/login`, `/api-keys`,
 * `/compliance-reviewer-legacy`, etc.) continue to inherit the global
 * `.dark` theme from <html class="dark">. (``/compliance`` itself moved
 * into the `(dashboard)` group in Phase 4 Wave 2 PR C1.)
 *
 * `bg-background` is the warm-paper `--paper` colour inside this scope.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <OnboardingWizardProvider>
        <div className="dashboard min-h-screen bg-background text-foreground">
          <Sidebar />
          <Topbar />
          <main className="ml-56 mt-14 min-h-[calc(100vh-3.5rem)] p-6">{children}</main>
          {/* Phase 1 PR 14 — 5-question onboarding wizard. Single
              instance hoisted to the layout so any tree under
              /(dashboard)/* can call useOnboardingWizard().open(). */}
          <OnboardingWizard />
        </div>
      </OnboardingWizardProvider>
    </ProtectedRoute>
  );
}
