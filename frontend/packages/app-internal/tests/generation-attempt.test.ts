import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
    type GenerationAttemptRecord,
    reconcileGenerationAttempt,
} from "../src/chat/lib/generation-attempt.ts";
import type { ChatDetailResponse } from "../src/chat/types/index.ts";

const attempt = (
    status: GenerationAttemptRecord["status"],
    assistantMessageId?: string,
): GenerationAttemptRecord => ({
    generation_attempt_id: "attempt-1",
    status,
    conversation_id: "chat-1",
    assistant_message_id: assistantMessageId,
});

const detail = (assistantMessageId: string): ChatDetailResponse => ({
    id: "chat-1",
    is_public: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    messages: [
        {
            id: assistantMessageId,
            role: "assistant",
            content: "Recovered",
            parent_id: "user-1",
            created_at: "2026-01-01T00:00:00Z",
        },
    ],
});

describe("generation attempt reconciliation", () => {
    it("recovers the exact durable assistant from a completed attempt", async () => {
        const result = await reconcileGenerationAttempt(
            async () => attempt("completed", "assistant-1"),
            async (conversationId, assistantMessageId) => {
                assert.equal(conversationId, "chat-1");
                assert.equal(assistantMessageId, "assistant-1");
                return detail(assistantMessageId);
            },
        );

        assert.equal(result.status, "recovered");
    });

    it("offers retry only for a durably failed attempt", async () => {
        const result = await reconcileGenerationAttempt(
            async () => attempt("failed"),
            async () => {
                throw new Error("detail should not load");
            },
        );

        assert.deepEqual(result, {
            status: "retryable",
            conversationId: "chat-1",
        });
    });

    it("keeps an in-progress attempt non-retryable", async () => {
        const result = await reconcileGenerationAttempt(
            async () => attempt("pending"),
            async () => {
                throw new Error("detail should not load");
            },
        );

        assert.deepEqual(result, {
            status: "pending",
            conversationId: "chat-1",
        });
    });

    it("preserves uncertainty when status or completed detail is unavailable", async () => {
        const statusUnavailable = await reconcileGenerationAttempt(
            async () => {
                throw new Error("status unavailable");
            },
            async () => detail("assistant-1"),
        );
        const detailUnavailable = await reconcileGenerationAttempt(
            async () => attempt("completed", "assistant-1"),
            async () => {
                throw new Error("detail unavailable");
            },
        );

        assert.equal(statusUnavailable.status, "unavailable");
        assert.equal(detailUnavailable.status, "unavailable");
    });
});
