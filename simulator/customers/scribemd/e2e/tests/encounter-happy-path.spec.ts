/**
 * Happy-path e2e — login through chart commit, in real chromium.
 *
 * Beats:
 *   1. `/` → redirect to `/login`
 *   2. fill passkey, click "Sign in" → land on `/encounter`
 *   3. select the pancreatitis fixture card
 *   4. click "Start encounter" → live pipeline renders
 *   5. wait for the approval gate (the "Sign and commit" button is a
 *      reliable signal that the workflow is parked at the HITL)
 *   6. assert diagnosis ("Acute pancreatitis"), med order ("Ondansetron"),
 *      risk pill (high|critical) all render
 *   7. click "Sign and commit"
 *   8. wait for the EHR mock — "Chart updated" headline
 *   9. assert "Note signed by Dr. Adams" is on the page
 *  10. assert the "View audit trail" link's href starts with
 *      `https://usevera.xyz/actions/`
 *
 * No `page.waitForTimeout` — every wait is anchored to a locator + a
 * tight timeout. Auto-waiting in Playwright handles the rest.
 */

import { expect, test } from "@playwright/test";

const PASSKEY = "test-passkey-123";

test.describe("ScribeMD encounter — happy path", () => {
  test("clinician signs into ScribeMD and commits a note", async ({
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

    await expect(page).toHaveURL(/\/encounter$/, { timeout: 10_000 });

    // The selector header is the cue that the protected page mounted.
    await expect(
      page.getByRole("heading", { name: "Start an encounter" }),
    ).toBeVisible();

    // ── Beat 3: select the pancreatitis fixture ──
    const pancreatitisCard = page.getByRole("radio", {
      name: /Acute pancreatitis/i,
    });
    await expect(pancreatitisCard).toBeVisible();
    await pancreatitisCard.click();
    await expect(pancreatitisCard).toHaveAttribute("aria-checked", "true");

    // ── Beat 4: start the encounter ──
    const startButton = page.getByRole("button", { name: /Start encounter/i });
    await expect(startButton).toBeEnabled();
    await startButton.click();

    // The live pipeline renders the four step labels. Scope to the
    // pipeline region — "Awaiting your sign-off" also appears in the
    // topbar status banner once the HITL gate fires, so an unscoped
    // getByText would resolve to two elements and trip strict mode.
    const pipeline = page.getByLabel("Encounter pipeline");
    await expect(
      pipeline.getByText("Listening to the visit"),
    ).toBeVisible({ timeout: 10_000 });
    await expect(pipeline.getByText("Drafting note")).toBeVisible();
    await expect(pipeline.getByText("Extracting orders")).toBeVisible();
    await expect(pipeline.getByText("Awaiting your sign-off")).toBeVisible();

    // ── Beat 5: wait for the HITL gate ──
    // The "Sign and commit" button only renders inside the ApprovalGate
    // card, so its visibility is the cleanest "approval_requested has
    // landed and is current" signal we have.
    const signAndCommit = page.getByRole("button", {
      name: /Sign and commit/i,
    });
    await expect(signAndCommit).toBeVisible({ timeout: 30_000 });
    await expect(signAndCommit).toBeEnabled();

    // ── Beat 6: gate content matches the canned Anthropic stub ──
    // Diagnoses + medication orders + lab orders all come straight from
    // FakeAnthropicLLM's deterministic JSON payload.
    await expect(page.getByText("Acute pancreatitis")).toBeVisible();
    await expect(
      page.getByText("Ondansetron 4mg IV q6h PRN"),
    ).toBeVisible();
    await expect(page.getByText("Lipase").first()).toBeVisible();

    // Risk pill should read "high" (pancreatitis fixture's expected risk)
    // or "critical" if the policy escalated it. Either is fine for the
    // happy path — the assertion is "we showed *some* elevated risk."
    const riskPill = page.locator(
      'text=/^(high|critical)$/i',
    ).first();
    await expect(riskPill).toBeVisible();

    // ── Beat 7: sign and commit ──
    await signAndCommit.click();

    // ── Beat 8: EHR mock renders ──
    await expect(
      page.getByRole("heading", { name: /Chart updated/i }),
    ).toBeVisible({ timeout: 30_000 });

    // ── Beat 9: signer line names the user from /api/auth/me ──
    await expect(
      page.getByText(/Note signed by\s+Dr\.\s*Adams/i),
    ).toBeVisible();

    // ── Beat 10: audit-trail deep link opens in a new tab and points
    // at /actions/<record-id> on the Vera dashboard ──
    const auditLink = page.getByRole("link", { name: /View audit trail/i });
    await expect(auditLink).toBeVisible();
    await expect(auditLink).toHaveAttribute("target", "_blank");
    const href = await auditLink.getAttribute("href");
    expect(href).not.toBeNull();
    expect(href!).toContain("/actions/");
    expect(href!).toMatch(/^https:\/\/usevera\.xyz\/actions\//);
  });
});
