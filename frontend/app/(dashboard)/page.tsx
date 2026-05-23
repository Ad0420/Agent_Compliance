import { redirect } from "next/navigation";

// PR 0c retired the legacy /dashboard route group; PR 12 (Phase 1 IA cutover)
// introduces /home as the post-login landing page. /home doesn't exist yet —
// PR 12 will add it.
export default function RootRedirect() {
  redirect("/home");
}
