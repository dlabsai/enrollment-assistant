import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
    createMessageRetryRequest,
    trimMessagesToMessageId,
} from "../src/chat/lib/message-retry.ts";
import type {
    Message,
    ModelOverrides,
} from "../src/chat/types/index.ts";

describe("message retry", () => {
    it("snapshots all authoring options for an exact regeneration retry", () => {
        const modelOverrides: ModelOverrides = {
            chatbotModel: "chat-model",
            guardrailReasoningEffort: "high",
        };
        const draftPromptTemplates = [
            { filename: "system.jinja", content: "Draft instructions" },
        ];

        const retry = createMessageRetryRequest({
            content: "Original prompt",
            modelOverrides,
            parentMessageId: "user-1",
            isRegeneration: true,
            trimToMessageId: "user-1",
            draftPromptTemplates,
        });
        modelOverrides.chatbotModel = "changed";
        draftPromptTemplates[0].content = "changed";

        assert.deepEqual(retry, {
            content: "Original prompt",
            modelOverrides: {
                chatbotModel: "chat-model",
                guardrailReasoningEffort: "high",
            },
            options: {
                parentMessageId: "user-1",
                isRegeneration: true,
                trimToMessageId: "user-1",
                draftPromptTemplates: [
                    {
                        filename: "system.jinja",
                        content: "Draft instructions",
                    },
                ],
            },
        });
    });

    it("preserves omitted and explicit-root parent semantics", () => {
        const omittedParent = createMessageRetryRequest({
            content: "Continue",
            parentMessageId: undefined,
            isRegeneration: false,
            trimToMessageId: undefined,
        });
        const rootParent = createMessageRetryRequest({
            content: "Start a root",
            parentMessageId: null,
            isRegeneration: false,
            trimToMessageId: undefined,
        });

        assert.equal(omittedParent.options.parentMessageId, undefined);
        assert.equal(omittedParent.options.trimToMessageId, undefined);
        assert.equal(rootParent.options.parentMessageId, null);
        assert.equal(rootParent.options.trimToMessageId, null);
    });

    it("trims the failed optimistic tail before retrying", () => {
        const messages: Message[] = [
            {
                id: "assistant-parent",
                role: "assistant",
                content: "Previous answer",
                createdAt: 1,
            },
            {
                id: "optimistic-user",
                role: "user",
                content: "Failed prompt",
                createdAt: 2,
            },
            {
                id: "error-1",
                role: "assistant",
                content: "Failed",
                createdAt: 3,
                isError: true,
            },
        ];

        assert.deepEqual(
            trimMessagesToMessageId(messages, "assistant-parent").map(
                (entry) => entry.id,
            ),
            ["assistant-parent"],
        );
    });
});
