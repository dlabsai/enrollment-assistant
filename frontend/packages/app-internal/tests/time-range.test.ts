import assert from "node:assert/strict";
import test from "node:test";

import { getTimeRangeQueryParams } from "../src/lib/time-range.ts";

const getCustomQuery = (start: Date, end?: Date): Record<string, string> =>
    Object.fromEntries(
        new URLSearchParams(
            getTimeRangeQueryParams("custom", new Date(0), { start, end }),
        ),
    );

test("a custom range query uses the selected boundaries", () => {
    const start = new Date("2026-05-10T09:15:00.000Z");
    const end = new Date("2026-05-10T10:45:59.999Z");

    assert.deepEqual(getCustomQuery(start, end), {
        start: "2026-05-10T09:15:00.000Z",
        end: "2026-05-10T10:45:59.999Z",
    });
});

test("a partial custom range query serializes its selected start", () => {
    const start = new Date("2026-05-10T09:15:00.000Z");

    assert.deepEqual(getCustomQuery(start), {
        start: "2026-05-10T09:15:00.000Z",
    });
});
