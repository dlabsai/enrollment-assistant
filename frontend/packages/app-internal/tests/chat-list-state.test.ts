import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { mergeChatListItems } from "../src/chat/lib/chat-list-state.ts";
import type { Chat, ChatListItem } from "../src/chat/types/index.ts";

const createListItem = (
    overrides: Partial<ChatListItem> = {},
): ChatListItem => ({
    id: "chat-1",
    title: "List title",
    summary: "List summary",
    last_message_preview: "Latest preview",
    message_count: 2,
    created_at: "2026-08-04T09:00:00Z",
    updated_at: "2026-08-04T10:00:00Z",
    is_public: false,
    prompt_source: "live",
    user_name: "List owner",
    user_email: "owner@example.com",
    ...overrides,
});

describe("chat list state", () => {
    it("preserves hydrated state while applying refreshed list metadata", () => {
        const hydratedChat: Chat = {
            id: "chat-1",
            title: "Detail title",
            summary: "Detail summary",
            updatedAt: 100,
            isPublic: false,
            investigationSourceConversationId: "source-chat",
            investigationSourceMessageId: "source-message",
            messages: [
                {
                    id: "message-1",
                    role: "assistant",
                    content: "Hydrated transcript",
                    createdAt: 100,
                },
            ],
            isLoading: true,
            hasUnread: true,
            loadingActivity: [
                {
                    id: "agent:chatbot",
                    label: "Chatbot agent",
                    status: "in_progress",
                },
            ],
            loadingActivityLog: [
                {
                    id: "agent:chatbot",
                    sequence: 1,
                    label: "Chatbot agent",
                    status: "in_progress",
                },
            ],
            parentMessageId: "message-1",
        };

        const chats = mergeChatListItems(
            [createListItem()],
            new Map([[hydratedChat.id, hydratedChat]]),
        );
        const mergedChat = chats.get(hydratedChat.id);

        assert.equal(mergedChat?.title, "List title");
        assert.equal(mergedChat?.summary, "List summary");
        assert.equal(mergedChat?.lastMessagePreview, "Latest preview");
        assert.equal(
            mergedChat?.updatedAt,
            new Date("2026-08-04T10:00:00Z").getTime(),
        );
        assert.equal(mergedChat?.promptSource, "live");
        assert.equal(mergedChat?.userName, "List owner");
        assert.equal(mergedChat?.userEmail, "owner@example.com");
        assert.deepEqual(mergedChat?.messages, hydratedChat.messages);
        assert.equal(mergedChat?.isLoading, true);
        assert.equal(mergedChat?.hasUnread, true);
        assert.deepEqual(
            mergedChat?.loadingActivity,
            hydratedChat.loadingActivity,
        );
        assert.deepEqual(
            mergedChat?.loadingActivityLog,
            hydratedChat.loadingActivityLog,
        );
        assert.equal(mergedChat?.parentMessageId, "message-1");
        assert.equal(
            mergedChat?.investigationSourceConversationId,
            "source-chat",
        );
        assert.equal(
            mergedChat?.investigationSourceMessageId,
            "source-message",
        );
    });

    it("initializes local state for conversations not already in the store", () => {
        const item = createListItem({ id: "chat-2" });

        const chat = mergeChatListItems([item], new Map()).get(item.id);

        assert.deepEqual(chat?.messages, []);
        assert.equal(chat?.isLoading, false);
        assert.equal(chat?.hasUnread, false);
        assert.equal(chat?.title, item.title);
    });

    it("reconciles the store to the conversations in the response", () => {
        const staleChat: Chat = {
            id: "stale-chat",
            updatedAt: 100,
            isPublic: false,
            messages: [],
            isLoading: false,
            hasUnread: false,
        };

        const chats = mergeChatListItems(
            [createListItem()],
            new Map([[staleChat.id, staleChat]]),
        );

        assert.equal(chats.has(staleChat.id), false);
    });
});
