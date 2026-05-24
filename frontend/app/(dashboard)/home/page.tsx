import { redirect } from "next/navigation";

// Stub until PR 12 ships the real Home page (per v1-implementation-plan.md Phase 1 PR 12).
// Clerk sign-in / sign-up / org-switch and the (dashboard) root all redirect here;
// /compliance is the only post-login surface that still exists today, so forward to it
// to keep the auth flow intact.
export default function HomeStub() {
  redirect("/compliance");
}
