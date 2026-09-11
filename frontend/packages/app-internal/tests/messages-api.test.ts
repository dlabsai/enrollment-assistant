import assert from "node:assert/strict";

import { test } from "vitest";

import type { AuthenticatedApi } from "../src/auth/hooks/use-authenticated-api";
import { fetchMessageListPage } from "../src/messages/lib/api";

test("Messages API encodes response-time bounds and slowest-first sorting", async () => {
    let endpoint = "";
    const api = {
        get: async <T>(requestedEndpoint: string): Promise<T> => {
            endpoint = requestedEndpoint;
            return { items: [], total: 0 } as T;
        },
    } satisfies Pick<AuthenticatedApi, "get">;

    await fetchMessageListPage(api, {
        customRange: {
            start: new Date("2026-08-01T00:00:00.000Z"),
            end: new Date("2026-08-02T00:00:00.000Z"),
        },
        descending: true,
        excludeDraft: true,
        limit: 20,
        maxGenerationTimeMs: 25_000,
        minGenerationTimeMs: 20_000,
        offset: 0,
        role: "assistant",
        sortBy: "generation_time_ms",
        timeRange: "custom",
    });

    const url = new URL(endpoint, "http://testserver");
    assert.equal(url.searchParams.get("min_generation_time_ms"), "20000");
    assert.equal(url.searchParams.get("max_generation_time_ms"), "25000");
    assert.equal(url.searchParams.get("sort_by"), "generation_time_ms");
    assert.equal(url.searchParams.get("descending"), "true");
    assert.equal(url.searchParams.get("exclude_draft"), "true");
});
