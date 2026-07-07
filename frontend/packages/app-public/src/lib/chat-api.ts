import { API_URL } from "@va/shared/config";
import { apiPost, isAbortError } from "@va/shared/lib/api-client";
import { logger } from "@va/shared/lib/logger";
import type { ChatMessage } from "@va/shared/types";
import { nanoid } from "nanoid";

const CHAT_ENDPOINT = "/chat/public/message";

interface ChatResponse {
    conversation_id: string;
    user_message_id: string;
    assistant_message_id: string;
    assistant_message: string;
    parent_message_id?: string;
    guardrails_blocked?: boolean;
    guardrails_blocked_message?: string | null;
}

interface SendChatCallbacks {
    onAssistantMessage: (message: ChatMessage) => void;
    onChatUpdate?: (chatId: string) => void;
    onParentMessageUpdate?: (parentMessageId: string) => void;
    onError: (message: ChatMessage) => void;
}

interface SendChatOptions {
    userMessage: string;
    chatId?: string;
    parentMessageId?: string;
    signal?: AbortSignal;
    callbacks: SendChatCallbacks;
}

export const sendChatMessage = async ({
    userMessage,
    chatId,
    parentMessageId,
    signal,
    callbacks,
}: SendChatOptions): Promise<{ success: boolean }> => {
    try {
        const body: Record<string, unknown> = {
            user_prompt: userMessage,
        };

        if (chatId !== undefined && chatId !== "") {
            body.conversation_id = chatId;
        }

        if (parentMessageId !== undefined && parentMessageId !== "") {
            body.parent_message_id = parentMessageId;
        }

        const data = await apiPost<ChatResponse>(CHAT_ENDPOINT, body, {
            signal,
            baseUrl: API_URL,
        });

        if (data.conversation_id !== "" && callbacks.onChatUpdate) {
            callbacks.onChatUpdate(data.conversation_id);
        }

        // Next turn should reference the latest assistant message as the parent.
        if (
            data.assistant_message_id !== "" &&
            callbacks.onParentMessageUpdate
        ) {
            callbacks.onParentMessageUpdate(data.assistant_message_id);
        }

        const assistantMessage: ChatMessage = {
            id: data.assistant_message_id || `assistant-${nanoid(7)}`,
            role: "assistant",
            content:
                data.guardrails_blocked === true &&
                typeof data.guardrails_blocked_message === "string" &&
                data.guardrails_blocked_message !== ""
                    ? data.guardrails_blocked_message
                    : data.assistant_message,
            timestamp: Date.now(),
        };

        callbacks.onAssistantMessage(assistantMessage);

        return { success: true };
    } catch (error) {
        if (isAbortError(error)) {
            return { success: false };
        }

        logger.error("Error sending message:", error);

        const errorMessage: ChatMessage = {
            id: `error-${nanoid(7)}`,
            role: "assistant",
            content:
                "Sorry, I encountered an error processing your request. Please try again.",
            timestamp: Date.now(),
        };

        callbacks.onError(errorMessage);

        return { success: false };
    }
};
