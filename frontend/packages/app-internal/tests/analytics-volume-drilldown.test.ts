import assert from "node:assert/strict";

import { test } from "vitest";

import type { AuthenticatedApi } from "../src/auth/hooks/use-authenticated-api";
import {
    getChatVolumeDrilldownSearch,
    getTurnsVolumeDrilldownSearch,
} from "../src/chat-analytics/lib/drilldown";
import { fetchChatListPage, fetchChatsExport } from "../src/chats/lib/api";
import { validateChatsSearch } from "../src/chats/lib/search-state";
import { fetchMessageListPage } from "../src/messages/lib/api";
import { validateMessagesSearch } from "../src/messages/lib/search-state";

const point = {
    bucket_start: "2026-08-10T00:00:00.000Z",
    bucket_end: "2026-08-11T00:00:00.000Z",
    conversations: 3,
    turns: 5,
};
const cohort = {
    start: "2026-08-01T12:00:00.000Z",
    end: "2026-08-31T12:00:00.000Z",
};

test("chat volume sends creation-only scope through pagination and export", async () => {
    const route = validateChatsSearch({
        ...getChatVolumeDrilldownSearch(point, "internal", {
            userGroup: "staff",
        }),
    });
    const requests: URL[] = [];
    const api = {
        get: async <T>(endpoint: string): Promise<T> => {
            requests.push(new URL(endpoint, "http://testserver"));
            return { items: [], total: 3 } as T;
        },
        getBlob: async (endpoint: string) => {
            requests.push(new URL(endpoint, "http://testserver"));
            return { blob: new Blob() };
        },
    } satisfies Pick<AuthenticatedApi, "get" | "getBlob">;
    const filters = {
        platform: route.platform,
        userGroup: route.userGroup,
        analyticsFilter: {
            start: route.analyticsStart,
            endBefore: route.analyticsEndBefore,
            minTurns: route.minTurns,
            maxTurns: route.maxTurns,
        },
        timeRange: "30d" as const,
        customRange: {},
    };
    for (const offset of [0, 20]) {
        await fetchChatListPage(api, { ...filters, limit: 20, offset });
    }
    await fetchChatsExport(api, {
        ...filters,
        chatUrlBase: "http://testserver/#/chats",
        locale: "en-US",
        timeZone: "America/New_York",
    });
    for (const { searchParams } of requests) {
        assert.equal(searchParams.get("analytics_start"), point.bucket_start);
        assert.equal(
            searchParams.get("analytics_end_before"),
            point.bucket_end,
        );
        assert.equal(searchParams.get("platform"), "internal");
        assert.equal(searchParams.get("user_group"), "staff");
        // Ordinary activity dates or a length constraint would change this cohort.
        for (const key of ["start", "end", "min_turns", "max_turns"]) {
            assert.equal(searchParams.has(key), false);
        }
    }
    assert.equal(requests[1].searchParams.get("offset"), "20");
});

test("turn volume preserves a clipped exclusive end and the full chat cohort", async () => {
    const clicked = { ...point, bucket_end: "2026-08-10T12:00:00.000001Z" };
    const route = validateMessagesSearch({
        ...getTurnsVolumeDrilldownSearch(clicked, cohort, "public", {
            userEmail: "lead@example.com",
        }),
    });
    assert.ok(route.start);
    assert.ok(route.endBefore);
    const requests: URL[] = [];
    const api = {
        get: async <T>(endpoint: string): Promise<T> => {
            requests.push(new URL(endpoint, "http://testserver"));
            return { items: [], total: 5 } as T;
        },
    };
    for (const offset of [0, 20]) {
        await fetchMessageListPage(api, {
            ...route,
            timeRange: "custom",
            customRange: {
                start: new Date(route.start),
                end: new Date(route.endBefore),
            },
            limit: 20,
            offset,
        });
    }
    for (const { searchParams } of requests) {
        assert.equal(searchParams.get("role"), "user");
        assert.equal(searchParams.get("start"), point.bucket_start);
        assert.equal(searchParams.get("end_before"), clicked.bucket_end);
        assert.equal(searchParams.has("end"), false);
        assert.equal(searchParams.get("conversation_start"), cohort.start);
        assert.equal(searchParams.get("conversation_end"), cohort.end);
        assert.equal(searchParams.get("platform"), "public");
        assert.equal(searchParams.get("user_email"), "lead@example.com");
    }
});

test.each([
    ["2026-11-01T05:15:00.000Z", "2026-11-01T06:00:00.000Z"],
    ["2026-08-10T00:00:00.000Z", "2026-08-17T00:00:00.000Z"],
    ["2026-08-01T00:00:00.000Z", "2026-08-31T12:00:00.000001Z"],
])("volume links trust clipped hour/week/month bounds: %s", (start, end) => {
    const bucket = { ...point, bucket_start: start, bucket_end: end };
    const chats = getChatVolumeDrilldownSearch(bucket, "both", {});
    const turns = getTurnsVolumeDrilldownSearch(bucket, {}, "both", {});
    assert.equal(chats.analyticsStart, start);
    assert.equal(chats.analyticsEndBefore, end);
    assert.equal(turns.start, start);
    assert.equal(turns.endBefore, end);
    assert.equal(turns.conversationStart, undefined);
    assert.equal(turns.conversationEnd, undefined);
    assert.equal(chats.platform, undefined);
    assert.equal(turns.platform, undefined);
});

test("creation scopes allow one-sided ranges and reject malformed or reversed dates", () => {
    for (const range of [{ start: cohort.start }, { end: cohort.end }]) {
        const route = validateMessagesSearch({
            ...getTurnsVolumeDrilldownSearch(point, range, "internal", {}),
        });
        assert.equal(route.conversationStart, range.start);
        assert.equal(route.conversationEnd, range.end);
        const chats = validateChatsSearch({
            analyticsStart: range.start,
            analyticsEnd: range.end,
        });
        assert.equal(chats.analyticsStart, range.start);
        assert.equal(chats.analyticsEnd, range.end);
    }
    for (const range of [
        { start: "bad", end: cohort.end },
        { start: cohort.start, end: "" },
        { start: cohort.end, end: cohort.start },
        { start: 42 },
    ]) {
        const messages = validateMessagesSearch({
            conversationStart: range.start,
            conversationEnd: range.end,
        });
        assert.equal(messages.conversationStart, undefined);
        assert.equal(messages.conversationEnd, undefined);
        const chats = validateChatsSearch({
            analyticsStart: range.start,
            analyticsEnd: range.end,
            platform: "internal",
        });
        assert.equal(chats.analyticsStart, undefined);
        assert.equal(chats.analyticsEnd, undefined);
        assert.equal(chats.platform, undefined);
    }
    assert.equal(
        validateChatsSearch({ minTurns: "bad", analyticsStart: cohort.start })
            .analyticsStart,
        undefined,
    );
});
