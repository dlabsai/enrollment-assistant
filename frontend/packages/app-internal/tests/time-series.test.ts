import assert from "node:assert/strict";

import { test } from "vitest";

import { formatTimeSeriesTick } from "../src/lib/time-series";

test("hourly ticks distinguish the same hour on different days", () => {
    assert.notEqual(
        formatTimeSeriesTick("2026-08-01T09:00:00.000Z", "hour"),
        formatTimeSeriesTick("2026-08-02T09:00:00.000Z", "hour"),
    );
});
