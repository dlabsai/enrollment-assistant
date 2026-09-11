import assert from "node:assert/strict";

import { test } from "vitest";

import { toggleVisibleSeries } from "../src/lib/chart-series";

test("series visibility allows one or all series but never none", () => {
    const both = new Set(["median", "p95"]);

    const medianOnly = toggleVisibleSeries(both, "p95");
    assert.deepEqual([...medianOnly], ["median"]);
    assert.deepEqual([...both], ["median", "p95"]);

    assert.equal(toggleVisibleSeries(medianOnly, "median"), medianOnly);
    assert.deepEqual(
        [...toggleVisibleSeries(medianOnly, "p95")],
        ["median", "p95"],
    );
});
