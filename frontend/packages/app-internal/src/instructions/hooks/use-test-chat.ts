import { logger } from "@va/shared/lib/logger";
import type { ChatMessage } from "@va/shared/types";
import { nanoid } from "nanoid";
import { useCallback, useRef, useState } from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { sendMessageStream } from "../../chat/lib/api";

interface UseTestChatOptions {
    chatId?: string;
    parentMessageId?: string;
    onChatChange?: (chatId: string, parentMessageId?: string) => void;
    onAddMessage?: (message: ChatMessage) => void;
    promptSetVersionId?: string;
}

const noop = (): void => undefined;

export const useTestChat = ({
    chatId,
    parentMessageId,
    onChatChange,
    onAddMessage,
    promptSetVersionId,
}: UseTestChatOptions): {
    isLoading: boolean;
    sendMessage: (message: string) => Promise<void>;
} => {
    const api = useAuthenticatedApi();
    const [isLoading, setIsLoading] = useState(false);
    const abortControllerRef = useRef<AbortController | undefined>(undefined);
    const chatIdRef = useRef(chatId);
    const parentMessageIdRef = useRef(parentMessageId);

    const handleSendMessage = useCallback(
        async (userMessage: string): Promise<void> => {
            if (abortControllerRef.current) {
                abortControllerRef.current.abort();
            }
            abortControllerRef.current = new AbortController();
            chatIdRef.current = chatId;
            parentMessageIdRef.current = parentMessageId;

            const userChatMessage: ChatMessage = {
                id: `user-${nanoid(7)}`,
                role: "user",
                content: userMessage,
                timestamp: Date.now(),
            };

            onAddMessage?.(userChatMessage);
            setIsLoading(true);

            try {
                if (
                    promptSetVersionId === undefined ||
                    promptSetVersionId.trim() === ""
                ) {
                    throw new Error("No prompt set version selected.");
                }

                await sendMessageStream(
                    api,
                    {
                        userMessage,
                        chatId: chatIdRef.current,
                        parentMessageId: parentMessageIdRef.current,
                        promptSetVersionId,
                    },
                    {
                        onChatId: (newChatId) => {
                            chatIdRef.current = newChatId;
                            onChatChange?.(newChatId);
                        },
                        onAssistantMessage: ({
                            assistantMessageId,
                            content,
                        }) => {
                            const fallbackId = `assistant-${nanoid(7)}`;
                            const assistantMessage: ChatMessage = {
                                id: assistantMessageId || fallbackId,
                                role: "assistant",
                                content,
                                timestamp: Date.now(),
                            };
                            onAddMessage?.(assistantMessage);

                            if (assistantMessageId !== "") {
                                parentMessageIdRef.current = assistantMessageId;
                                const activeChatId = chatIdRef.current;
                                if (
                                    activeChatId !== undefined &&
                                    activeChatId !== ""
                                ) {
                                    onChatChange?.(
                                        activeChatId,
                                        assistantMessageId,
                                    );
                                }
                            }
                        },
                        onError: (errorMessage) => {
                            const errorChatMessage: ChatMessage = {
                                id: `error-${nanoid(7)}`,
                                role: "assistant",
                                content: errorMessage,
                                timestamp: Date.now(),
                            };
                            onAddMessage?.(errorChatMessage);
                        },
                        onTitleUpdate: noop,
                        onAgentStage: noop,
                        onToolCall: noop,
                        onThinking: noop,
                    },
                    abortControllerRef.current.signal,
                );
            } catch (error) {
                if (error instanceof Error && error.name !== "AbortError") {
                    logger.error("Error sending message:", error);
                }
            } finally {
                setIsLoading(false);
            }
        },
        [
            chatId,
            parentMessageId,
            api,
            onChatChange,
            onAddMessage,
            promptSetVersionId,
        ],
    );

    return {
        isLoading,
        sendMessage: handleSendMessage,
    };
};
