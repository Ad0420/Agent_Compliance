import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { ProtectedRoute } from "@/components/layout/protected-route";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <Sidebar />
      <Topbar />
      <main className="ml-56 mt-14 min-h-[calc(100vh-3.5rem)] p-6">{children}</main>
    </ProtectedRoute>
  );
}
