import assert from "node:assert/strict";

import { test } from "vitest";

import { routeUserOption } from "../src/chats/lib/review-search-state";
import { validateFeedbackSearch } from "../src/feedback/lib/search-state";
import { validateMessagesSearch } from "../src/messages/lib/search-state";

test("message review search preserves URL-backed filters", () => {
    assert.deepEqual(
        validateMessagesSearch({
            excludeDraft: "true",
            guardrailStatus: "retried",
            minGenerationTimeMs: "20000",
            maxGenerationTimeMs: 25_000,
            platform: "internal",
            role: "assistant",
            search: "retry feedback",
            sortBy: "generation_time_ms",
            descending: "true",
            start: "2026-08-01T00:00:00.000Z",
            end: "2026-08-01T23:59:59.999Z",
            timeRange: "custom",
            userGroup: "staff",
        }),
        {
            excludeDraft: true,
            conversationStart: undefined,
            conversationEnd: undefined,
            guardrailStatus: "retried",
            minGenerationTimeMs: 20_000,
            maxGenerationTimeMs: 25_000,
            platform: "internal",
            role: "assistant",
            search: "retry feedback",
            sortBy: "generation_time_ms",
            descending: true,
            start: "2026-08-01T00:00:00.000Z",
            end: "2026-08-01T23:59:59.999Z",
            timeRange: "custom",
            endBefore: undefined,
            userEmail: undefined,
            userGroup: "staff",
        },
    );
});

test("feedback review search preserves Quality drill-down filters", () => {
    assert.deepEqual(
        validateFeedbackSearch({
            chat: "chat-id",
            excludeDraft: true,
            message: "message-id",
            platform: "public",
            rating: "thumbs_down",
            search: "incorrect answer",
            start: "2026-08-01T00:00:00.000Z",
            end: "2026-08-01T23:59:59.999Z",
            timeRange: "custom",
            userEmail: "person@example.com",
        }),
        {
            chat: "chat-id",
            excludeDraft: true,
            message: "message-id",
            platform: "public",
            rating: "thumbs_down",
            search: "incorrect answer",
            start: "2026-08-01T00:00:00.000Z",
            end: "2026-08-01T23:59:59.999Z",
            timeRange: "custom",
            userEmail: "person@example.com",
            userGroup: undefined,
        },
    );
});

test("review owner route values resolve groups and exact contacts", () => {
    assert.deepEqual(routeUserOption(undefined, "devs", undefined), {
        name: "Devs",
        email: "__owner_group:devs",
        platform: "internal",
        ownerGroup: "devs",
    });
    assert.deepEqual(routeUserOption("lead@example.com", undefined, "public"), {
        email: "lead@example.com",
        platform: "public",
    });
});
