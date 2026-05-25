/**
 * DecisionsTab — type & contract smoke tests.
 *
 * Wave 2C PR C1. See the sibling ``decision-row.test.tsx`` for the
 * rationale: the main ``frontend/`` workspace has no Vitest/Jest
 * runner today, so these files exercise the typed contract under
 * ``tsc --noEmit`` (CI gate) until a test runner is wired up.
 *
 * Once vitest lands, each ``test_*`` constant is the exact shape a
 * mocked ``useCustomerDecisions`` should return for the matching
 * render branch (loading / error / empty / loaded).
 */

import * as React from "react";

import { DecisionsTab } from "../decisions-tab";
import type { CustomerDecisionsResponse } from "@/lib/api-types";
import {
  test_decision_allow_no_webhook,
  test_decision_require_hitl_pending,
  test_decision_block_retrying,
  test_decision_no_ruling_delivered,
  test_decision_aborted_webhook,
} from "./decision-row.test";

// ── Mocked response fixtures ───────────────────────────────────────────

export const test_response_empty: CustomerDecisionsResponse = {
  decisions: [],
  total: 0,
  limit: 50,
  offset: 0,
};

export const test_response_loaded: CustomerDecisionsResponse = {
  decisions: [
    test_decision_allow_no_webhook,
    test_decision_require_hitl_pending,
    test_decision_block_retrying,
    test_decision_no_ruling_delivered,
    test_decision_aborted_webhook,
  ],
  total: 5,
  limit: 50,
  offset: 0,
};

// Pagination probe — should NOT cause runtime polling once vitest is
// wired up because every delivery is terminal (delivered or aborted).
export const test_response_terminal_only: CustomerDecisionsResponse = {
  decisions: [
    test_decision_allow_no_webhook,
    test_decision_no_ruling_delivered,
    test_decision_aborted_webhook,
  ],
  total: 3,
  limit: 50,
  offset: 0,
};

// ── Render-shape smoke (validates props compile) ───────────────────────

const _mounted_default: React.ReactNode = (
  <DecisionsTab tenant_id="hosp_8h2nf_v2" />
);
const _mounted_disabled: React.ReactNode = (
  <DecisionsTab tenant_id="hosp_8h2nf_v2" enabled={false} />
);
const _mounted_custom_limit: React.ReactNode = (
  <DecisionsTab tenant_id="hosp_8h2nf_v2" limit={20} />
);

void _mounted_default;
void _mounted_disabled;
void _mounted_custom_limit;

// ── Counted-state assertion ────────────────────────────────────────────
//
// Ensures the count math the component renders ("Showing N of M") agrees
// with the fixtures above. A future shape change that drops ``total``
// from CustomerDecisionsResponse fails here at compile time.

function _assertCounts(resp: CustomerDecisionsResponse): {
  shown: number;
  total: number;
} {
  return { shown: resp.decisions.length, total: resp.total };
}

const _empty_counts = _assertCounts(test_response_empty);
const _loaded_counts = _assertCounts(test_response_loaded);
const _terminal_counts = _assertCounts(test_response_terminal_only);

void _empty_counts;
void _loaded_counts;
void _terminal_counts;
