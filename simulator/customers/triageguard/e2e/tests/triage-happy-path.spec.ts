/**
 * Happy-path e2e — login through ER escalation, in real chromium.
 *
 * Beats:
 *   1. `/` → redirect to `/login`
 *   2. fill passkey, click "Sign in" → land on `/triage`
 *   3. red_flag_chest_pain is the default-selected fixture; click
 *      "Start triage session" → live pipeline renders
 *   4. wait for the four pipeline stages, scoped to the
 *      `aria-label="Triage session pipeline"` region (live-pipeline.tsx)
 *      to avoid the strict-mode collision with the topbar status text
 *      (PR #122 lesson — applied)
 *   5. wait for the review gate's "Escalate to ER" button as the
 *      "we're parked at the HITL" signal, then click it
 *   6. wait for the routed-screen hero "Patient routed to ER."
 *   7. assert "View audit trail" link has target="_blank" and an href
 *      that contains `/actions/`
 *
 * No `page.waitForTimeout` — every wait is anchored to a locator + a
 * tight timeout. Auto-waiting in Playwright handles the rest.
 */

import { expect, test } from "@playwright/test";

const PASSKEY = "e2e-passkey-123";

test.describe("TriageGuard triage — happy path", () => {
  test("nurse signs into TriageGuard and escalates to ER", async ({
    page,
  }) => {
    // ── Beat 1: root redirects to /login ──
    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/);

    await expect(
      page.getByRole("heading", { name: "Sign in" }),
    ).toBeVisible();

    // ── Beat 2: log in with the test passkey ──
    const passkeyInput = page.getByLabel("Passkey");
    await passkeyInput.fill(PASSKEY);

    const signInButton = page.getByRole("button", { name: "Sign in" });
    await expect(signInButton).toBeEnabled();
    await signInButton.click();

    await expect(page).toHaveURL(/\/triage$/, { timeout: 10_000 });

    // The selector header is the cue that the protected page mounted.
    await expect(
      page.getByRole("heading", { name: "Start a triage session" }),
    ).toBeVisible();

    // ── Beat 3: red_flag_chest_pain is selected by default ──
    const chestPainCard = page.getByRole("radio", {
      name: /Chest pain.*possible STEMI/i,
    });
    await expect(chestPainCard).toBeVisible();
    await expect(chestPainCard).toHaveAttribute("aria-checked", "true");

    // ── Beat 4: start the triage session ──
    const startButton = page.getByRole("button", {
      name: /Start triage session/i,
    });
    await expect(startButton).toBeEnabled();
    await startButton.click();

    // Pipeline region — scope every step assertion here. The topbar
    // also surfaces "Awaiting your triage decision" text once the
    // gate fires, so an unscoped getByText would resolve to two
    // elements and trip strict mode.
    const pipeline = page.getByLabel("Triage session pipeline");
    await expect(
      pipeline.getByText("Listening to symptoms"),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      pipeline.getByText("Classifying triage level"),
    ).toBeVisible();
    await expect(
      pipeline.getByText("Checking for red flags"),
    ).toBeVisible();
    await expect(
      pipeline.getByText("Awaiting your triage decision"),
    ).toBeVisible();

    // ── Beat 5: HITL gate ──
    // The "Escalate to ER" button only renders inside ReviewGate, so
    // its visibility is the cleanest "approval_requested has landed
    // and is current" signal we have.
    const escalateButton = page.getByRole("button", {
      name: /Escalate to ER/i,
    });
    await expect(escalateButton).toBeVisible({ timeout: 30_000 });
    await expect(escalateButton).toBeEnabled();

    // The gate should surface the canonical chest-pain red-flag terms
    // from the fake detector, plus the recommended override = ER.
    await expect(
      page.getByText("chest pain", { exact: false }).first(),
    ).toBeVisible();
    await expect(
      page.getByText(/override:\s*ER/i),
    ).toBeVisible();

    // ── Beat 6: escalate to ER ──
    await escalateButton.click();

    // ── Beat 7: routed-screen hero ──
    // Generous timeout — the workflow has to commit the routing
    // record, close the bus, and let the SSE stream's terminal event
    // propagate through the snapshot poll before the page flips.
    await expect(
      page.getByRole("heading", { name: /Patient routed to ER\./i }),
    ).toBeVisible({ timeout: 30_000 });

    // ── Beat 8: audit-trail deep link opens in a new tab and points
    // at /actions/<record-id> on the Vera dashboard ──
    const auditLink = page.getByRole("link", {
      name: /View audit trail/i,
    });
    await expect(auditLink).toBeVisible();
    await expect(auditLink).toHaveAttribute("target", "_blank");
    const href = await auditLink.getAttribute("href");
    expect(href).not.toBeNull();
    expect(href!).toContain("/actions/");
  });
});
