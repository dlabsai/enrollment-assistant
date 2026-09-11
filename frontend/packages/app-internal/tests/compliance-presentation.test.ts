import assert from "node:assert/strict";

import { test, vi } from "vitest";

import {
    decisionLabel,
    formatScreeningDateRange,
    formatScreeningPeriod,
    screeningLabel,
    serializeComplianceSearch,
    validateComplianceSearch,
} from "../src/compliance/lib/presentation";
import { screening } from "./compliance-fixtures";

test("screening periods use concrete Eastern dates without zone labels", () => {
    vi.stubGlobal("window", {
        localStorage: { getItem: () => "eastern" },
    });
    try {
        assert.equal(formatScreeningDateRange(screening), "Sep 1, 2026");
        assert.equal(
            formatScreeningPeriod(screening),
            "Sep 1, 2026, 12:00\u202fAM\u2009–\u200911:59\u202fPM",
        );
        assert.equal(
            formatScreeningDateRange({
                ...screening,
                start: new Date(0).toISOString(),
            }),
            "Dec 31, 1969\u2009–\u2009Sep 1, 2026",
        );
    } finally {
        vi.unstubAllGlobals();
    }
});

test("compliance URLs serialize optional one-based pagination", () => {
    assert.deepEqual(
        validateComplianceSearch({ page: 1, pageSize: 25 }),
        {},
    );
    assert.deepEqual(
        validateComplianceSearch({ page: 2, pageSize: 50 }),
        { page: 2, pageSize: 50 },
    );
    assert.deepEqual(serializeComplianceSearch(2, 25), {
        page: 3,
    });
});

test("screening status remains separate from flag decisions", () => {
    assert.equal(screeningLabel(screening), "Complete");
    assert.equal(
        screeningLabel({ ...screening, needs_review: 2 }),
        "Complete",
    );
    assert.equal(screeningLabel({ ...screening, pending: 1 }), "Processing");
    assert.equal(
        screeningLabel({ ...screening, screened: 9, errors: 1 }),
        "Incomplete",
    );
    assert.equal(
        screeningLabel({
            ...screening,
            messages: 0,
            conversations: 0,
            screened: 0,
            findings: 0,
            needs_review: 0,
        }),
        "No messages",
    );
    assert.equal(
        screeningLabel({
            ...screening,
            admission_error: "Too many messages.",
            messages: 0,
            conversations: 0,
            screened: 0,
            findings: 0,
            needs_review: 0,
        }),
        "Incomplete",
    );
    assert.equal(decisionLabel("confirmed"), "Confirmed");
});
