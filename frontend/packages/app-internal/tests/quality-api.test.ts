import assert from "node:assert/strict";

import { afterEach, test, vi } from "vitest";

import type { AuthenticatedApi } from "../src/auth/hooks/use-authenticated-api";
import { fetchQualitySummary } from "../src/quality/lib/api";
import {
    getQualityDrilldownRange,
    getResponsivenessDurationSearch,
} from "../src/quality/lib/drilldown";
import type { QualitySummary } from "../src/quality/types";

const summary: QualitySummary = {
    summary: {
        assistant_responses: 0,
        retry_observed_responses: 0,
        retry_affected_responses: 0,
        retry_attempts: 0,
        blocked_responses: 0,
        ratings: 0,
        thumbs_up: 0,
        thumbs_down: 0,
        retry_affected_rate: null,
        blocked_rate: null,
        positive_rate: null,
        response_samples: 0,
        median_response_seconds: null,
        p95_response_seconds: null,
        failed_generations: 0,
        tracked_generation_attempts: 0,
        generation_failure_rate: null,
    },
    time_granularity: "day",
    series: [],
    responsiveness_series: [],
    failure_series: [],
    response_time_buckets: [],
};

afterEach(() => {
    vi.useRealTimers();
});

test("Quality fetches and captures exact rolling bounds", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-31T12:00:00.000Z"));
    let endpoint = "";
    const api = {
        get: async <T>(requestedEndpoint: string): Promise<T> => {
            endpoint = requestedEndpoint;
            return summary as T;
        },
    } satisfies Pick<AuthenticatedApi, "get">;

    const result = await fetchQualitySummary(api, "both", "30d", {});

    assert.deepEqual(result.appliedRange, {
        start: "2026-08-01T12:00:00.000Z",
        end: "2026-08-31T12:00:00.000Z",
        timeRange: "custom",
    });
    assert.equal(result.summary, summary);
    const requestUrl = new URL(endpoint, "http://testserver");
    assert.equal(
        requestUrl.searchParams.get("start"),
        result.appliedRange.start,
    );
    assert.equal(requestUrl.searchParams.get("end"), result.appliedRange.end);
});

test("Quality drill-downs use authoritative returned bounds", () => {
    const appliedRange = {
        start: "2026-08-01T12:00:00.000Z",
        end: "2026-08-31T12:00:00.000Z",
        timeRange: "custom",
    } as const;
    const firstDay = {
        bucket_start: "2026-08-01T12:00:00.000Z",
        bucket_end: "2026-08-02T00:00:00.000Z",
    };

    assert.deepEqual(getQualityDrilldownRange(appliedRange), appliedRange);
    assert.deepEqual(getQualityDrilldownRange(appliedRange, firstDay), {
        start: firstDay.bucket_start,
        endBefore: firstDay.bucket_end,
        timeRange: "custom",
    });
});

test("Responsiveness drill-downs include only timed responses", () => {
    assert.deepEqual(getResponsivenessDurationSearch(), {
        minGenerationTimeMs: 0,
        maxGenerationTimeMs: undefined,
    });
    assert.deepEqual(
        getResponsivenessDurationSearch({
            lower_bound: 20,
            upper_bound: 25,
        }),
        {
            minGenerationTimeMs: 20_000,
            maxGenerationTimeMs: 25_000,
        },
    );
    assert.deepEqual(
        getResponsivenessDurationSearch({
            lower_bound: 100,
            upper_bound: null,
        }),
        {
            minGenerationTimeMs: 100_000,
            maxGenerationTimeMs: undefined,
        },
    );
});
