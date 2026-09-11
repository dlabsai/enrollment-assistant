import assert from "node:assert/strict";

import { afterEach, test, vi } from "vitest";

import type { AuthenticatedApi } from "../src/auth/hooks/use-authenticated-api";
import { fetchChatAnalyticsSummary } from "../src/chat-analytics/lib/api";
import { getChatLengthDrilldownSearch } from "../src/chat-analytics/lib/drilldown";
import type { ChatAnalyticsSummary } from "../src/chat-analytics/types";
import { fetchChatListPage } from "../src/chats/lib/api";
import { validateChatsSearch } from "../src/chats/lib/search-state";

const summary: ChatAnalyticsSummary = {
    total_conversations: 0,
    total_turns: 0,
    avg_turns_per_conversation: 0,
    time_granularity: "day",
    series: [],
    length_buckets: [],
    hourly_activity: [],
    length_stats: null,
};

afterEach(() => {
    vi.useRealTimers();
});

test("Chat Analytics captures the exact range used by a turn drill-down", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-31T12:00:00.000Z"));
    let endpoint = "";
    const api = {
        get: async <T>(requestedEndpoint: string): Promise<T> => {
            endpoint = requestedEndpoint;
            return summary as T;
        },
    } satisfies Pick<AuthenticatedApi, "get">;

    const result = await fetchChatAnalyticsSummary(
        api as AuthenticatedApi,
        "internal",
        "30d",
        {},
        undefined,
        "staff",
    );

    assert.deepEqual(result.appliedRange, {
        start: "2026-08-01T12:00:00.000Z",
        end: "2026-08-31T12:00:00.000Z",
    });
    assert.equal(result.summary, summary);
    const requestUrl = new URL(endpoint, "http://testserver");
    assert.equal(requestUrl.searchParams.get("platform"), "internal");
    assert.equal(requestUrl.searchParams.get("user_group"), "staff");
    assert.equal(
        requestUrl.searchParams.get("start"),
        result.appliedRange.start,
    );
    assert.equal(requestUrl.searchParams.get("end"), result.appliedRange.end);
});

test("Chats sends exact cohort and turn bounds without its activity-time filter", async () => {
    let endpoint = "";
    const api = {
        get: async <T>(requestedEndpoint: string): Promise<T> => {
            endpoint = requestedEndpoint;
            return { items: [], total: 0 } as T;
        },
    } satisfies Pick<AuthenticatedApi, "get">;

    await fetchChatListPage(api, {
        limit: 20,
        offset: 0,
        timeRange: "30d",
        customRange: {},
        analyticsFilter: {
            minTurns: 3,
            maxTurns: 3,
            start: "2026-08-01T12:00:00.000Z",
            end: "2026-08-31T12:00:00.000Z",
        },
    });

    const requestUrl = new URL(endpoint, "http://testserver");
    assert.equal(requestUrl.searchParams.get("min_turns"), "3");
    assert.equal(requestUrl.searchParams.get("max_turns"), "3");
    assert.equal(
        requestUrl.searchParams.get("analytics_start"),
        "2026-08-01T12:00:00.000Z",
    );
    assert.equal(
        requestUrl.searchParams.get("analytics_end"),
        "2026-08-31T12:00:00.000Z",
    );
    assert.equal(requestUrl.searchParams.has("start"), false);
    assert.equal(requestUrl.searchParams.has("end"), false);
});

test("Chat length buckets map numeric bounds and scope into Chats search", () => {
    const appliedRange = {
        start: "2026-08-01T12:00:00.000Z",
        end: "2026-08-31T12:00:00.000Z",
    } as const;

    assert.deepEqual(
        getChatLengthDrilldownSearch(
            {
                label: "3",
                conversations: 12,
                min_turns: 3,
                max_turns: 3,
                overflow: false,
            },
            appliedRange,
            "internal",
            { userGroup: "staff" },
        ),
        {
            chat: undefined,
            minTurns: 3,
            maxTurns: 3,
            platform: "internal",
            analyticsStart: appliedRange.start,
            analyticsEnd: appliedRange.end,
            userEmail: undefined,
            userGroup: "staff",
        },
    );
    assert.equal(
        getChatLengthDrilldownSearch(
            {
                label: ">17",
                conversations: 2,
                min_turns: 18,
                max_turns: null,
                overflow: true,
            },
            appliedRange,
            "both",
            {},
        ).maxTurns,
        undefined,
    );
});

test("Chats validates nonnegative integer turn drill-down parameters", () => {
    assert.deepEqual(
        validateChatsSearch({
            minTurns: "3",
            maxTurns: "3",
            platform: "internal",
            analyticsStart: "2026-08-01T12:00:00.000Z",
            analyticsEnd: "2026-08-31T12:00:00.000Z",
            userGroup: "staff",
        }),
        {
            chat: undefined,
            minTurns: 3,
            maxTurns: 3,
            platform: "internal",
            analyticsStart: "2026-08-01T12:00:00.000Z",
            analyticsEnd: "2026-08-31T12:00:00.000Z",
            analyticsEndBefore: undefined,
            userEmail: undefined,
            userGroup: "staff",
        },
    );
    assert.equal(validateChatsSearch({ minTurns: "1.5" }).minTurns, undefined);
    assert.deepEqual(
        validateChatsSearch({
            minTurns: "3",
            maxTurns: "2",
            platform: "internal",
            analyticsStart: "2026-08-01T12:00:00.000Z",
            userGroup: "staff",
        }),
        {
            chat: undefined,
            minTurns: undefined,
            maxTurns: undefined,
            platform: undefined,
            analyticsStart: undefined,
            analyticsEnd: undefined,
            analyticsEndBefore: undefined,
            userEmail: undefined,
            userGroup: undefined,
        },
    );
    assert.equal(
        validateChatsSearch({ minTurns: "3", analyticsStart: "not-a-date" })
            .minTurns,
        undefined,
    );
    assert.equal(
        validateChatsSearch({
            minTurns: "3",
            analyticsStart: "2026-08-31T12:00:00.000Z",
            analyticsEnd: "2026-08-01T12:00:00.000Z",
        }).minTurns,
        undefined,
    );
});
