import { logger } from "@va/shared/lib/logger";
import type { ChatMessage } from "@va/shared/types";
import { nanoid } from "nanoid";
import { useCallback, useRef, useState } from "react";

import { sendChatMessage } from "../lib/chat-api";
import {
    createChatHistory,
    fetchChatHistory,
    getChatId,
    getParentMessageId,
    setChatId as storeChatId,
    setParentMessageId as storeParentMessageId,
    updateStoredHistory,
} from "../lib/storage";

interface UseChatOptions {
    consentGiven: boolean;
    onConsentSubmit?: (chatId: string) => void;
}

export const useChat = ({
    consentGiven,
    onConsentSubmit,
}: UseChatOptions): {
    messages: ChatMessage[];
    isLoading: boolean;
    sendMessage: (userMessage: string) => Promise<void>;
    resetChat: () => void;
} => {
    const [messages, setMessages] = useState<ChatMessage[]>(() => {
        createChatHistory();
        try {
            return fetchChatHistory();
        } catch (error) {
            logger.error("Error loading chat history:", error);
            return [];
        }
    });
    const [isLoading, setIsLoading] = useState(false);

    const sessionRef = useRef(0);

    const addMessage = useCallback((message: ChatMessage): void => {
        setMessages((prev) => [...prev, message]);
    }, []);

    const sendMessage = useCallback(
        async (userMessage: string): Promise<void> => {
            if (!consentGiven) {
                return;
            }

            const requestSession = sessionRef.current;

            const userChatMessage: ChatMessage = {
                id: `user-${nanoid(7)}`,
                role: "user",
                content: userMessage,
                timestamp: Date.now(),
            };

            addMessage(userChatMessage);
            updateStoredHistory(userChatMessage);
            setIsLoading(true);

            try {
                const chatId = getChatId();
                const parentMessageId = getParentMessageId();

                await sendChatMessage({
                    userMessage,
                    chatId,
                    parentMessageId,
                    callbacks: {
                        onAssistantMessage: (message) => {
                            addMessage(message);
                            updateStoredHistory(message);
                        },
                        onChatUpdate: (newChatId) => {
                            const previousChatId = getChatId();
                            const isNewChat = previousChatId !== newChatId;

                            storeChatId(newChatId);

                            if (isNewChat && onConsentSubmit) {
                                onConsentSubmit(newChatId);
                            }
                        },
                        onParentMessageUpdate: (newParentMessageId) => {
                            storeParentMessageId(newParentMessageId);
                        },
                        onError: (message) => {
                            addMessage(message);
                        },
                    },
                });
            } catch (error) {
                logger.error("Error sending message:", error);
            } finally {
                if (sessionRef.current === requestSession) {
                    setIsLoading(false);
                }
            }
        },
        [addMessage, consentGiven, onConsentSubmit],
    );

    const resetChat = useCallback((): void => {
        setMessages([]);
        sessionRef.current += 1;
    }, []);

    return {
        messages,
        isLoading,
        sendMessage,
        resetChat,
    };
};
