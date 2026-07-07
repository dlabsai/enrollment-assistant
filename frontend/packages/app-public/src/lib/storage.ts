import { logger } from "@va/shared/lib/logger";
import { isRecord } from "@va/shared/lib/type-guards";
import type { ChatMessage } from "@va/shared/types";

const CHAT_HISTORY_KEY = "chat_history";
const CONSENT_DATA_KEY = "chat_consent_data";
const VISITOR_ID_KEY = "chat_visitor_id";

interface StoredChatHistory {
    messages: ChatMessage[];
    chatId?: string;
    parentMessageId?: string;
}

const isValidStoredChatHistory = (
    value: unknown,
): value is StoredChatHistory => {
    if (!isRecord(value)) {
        return false;
    }

    if (!Array.isArray(value.messages)) {
        return false;
    }

    return true;
};

const getStoredChatHistory = (): StoredChatHistory | undefined => {
    try {
        const raw = localStorage.getItem(CHAT_HISTORY_KEY) ?? undefined;
        if (raw === undefined) {
            return undefined;
        }

        const parsed: unknown = JSON.parse(raw) ?? undefined;
        if (!isValidStoredChatHistory(parsed)) {
            logger.warn("Invalid chat history format in storage");
            return undefined;
        }

        return parsed;
    } catch (error) {
        logger.error("Error reading chat history from storage:", error);
        return undefined;
    }
};

const saveStoredChatHistory = (history: StoredChatHistory): boolean => {
    try {
        localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(history));
        return true;
    } catch (error) {
        logger.error("Error saving chat history to storage:", error);
        return false;
    }
};

const updateStoredChatHistoryField = <K extends keyof StoredChatHistory>(
    field: K,
    value: StoredChatHistory[K],
): void => {
    const history = getStoredChatHistory();
    if (history === undefined) {
        const newHistory: StoredChatHistory = { messages: [], [field]: value };
        saveStoredChatHistory(newHistory);
    } else {
        history[field] = value;
        saveStoredChatHistory(history);
    }
};

export const createChatHistory = (): void => {
    try {
        const localChatHistory =
            localStorage.getItem(CHAT_HISTORY_KEY) ?? undefined;
        if (localChatHistory !== undefined) {
            try {
                const parsed: unknown =
                    JSON.parse(localChatHistory) ?? undefined;
                if (parsed !== undefined && typeof parsed === "object") {
                    return;
                }
            } catch {
                logger.warn("Found invalid chat history, recreating");
            }
        }

        const storedChatHistory: StoredChatHistory = {
            messages: [],
        };
        localStorage.setItem(
            CHAT_HISTORY_KEY,
            JSON.stringify(storedChatHistory),
        );
    } catch (error) {
        logger.error("Error creating chat history:", error);
    }
};

export const fetchChatHistory = (): ChatMessage[] => {
    const history = getStoredChatHistory();
    if (history === undefined) {
        return [];
    }
    return history.messages;
};

export const updateStoredHistory = (message: ChatMessage): void => {
    const messageWithTimestamp: ChatMessage = {
        ...message,
        timestamp: message.timestamp,
    };

    const existing = getStoredChatHistory();
    const history = existing ?? { messages: [] };
    history.messages.push(messageWithTimestamp);
    saveStoredChatHistory(history);
};

export const getChatId = (): string | undefined => {
    const history = getStoredChatHistory();
    return history?.chatId ?? undefined;
};

export const setChatId = (chatId: string): void => {
    updateStoredChatHistoryField("chatId", chatId);
};

export const getParentMessageId = (): string | undefined => {
    const history = getStoredChatHistory();
    return history?.parentMessageId ?? undefined;
};

export const setParentMessageId = (parentMessageId: string): void => {
    updateStoredChatHistoryField("parentMessageId", parentMessageId);
};

export interface ConsentData {
    firstName: string;
    lastName: string;
    email: string;
    phone: string;
    zip: string;
    timestamp: number;
}

const isValidConsentData = (value: unknown): value is ConsentData => {
    if (!isRecord(value)) {
        return false;
    }
    return (
        "firstName" in value &&
        typeof value.firstName === "string" &&
        "lastName" in value &&
        typeof value.lastName === "string" &&
        "email" in value &&
        typeof value.email === "string" &&
        "phone" in value &&
        typeof value.phone === "string" &&
        "zip" in value &&
        typeof value.zip === "string" &&
        "timestamp" in value &&
        typeof value.timestamp === "number"
    );
};

export const hasCompleteConsentData = (): boolean => {
    try {
        const raw = localStorage.getItem(CONSENT_DATA_KEY) ?? undefined;
        if (raw === undefined || raw === "") {
            return false;
        }

        const parsed: unknown = JSON.parse(raw) ?? undefined;
        if (!isValidConsentData(parsed)) {
            return false;
        }

        const visitorId = localStorage.getItem(VISITOR_ID_KEY) ?? undefined;
        return visitorId !== undefined && visitorId !== "";
    } catch (error) {
        logger.error("Error checking consent data:", error);
        return false;
    }
};

export const setConsentData = (data: ConsentData): void => {
    try {
        localStorage.setItem(CONSENT_DATA_KEY, JSON.stringify(data));
    } catch (error) {
        logger.error("Error setting consent data:", error);
    }
};

export const getConsentData = (): ConsentData | undefined => {
    try {
        const raw = localStorage.getItem(CONSENT_DATA_KEY) ?? undefined;
        if (raw === undefined) {
            return undefined;
        }
        const parsed: unknown = JSON.parse(raw) ?? undefined;
        return isValidConsentData(parsed) ? parsed : undefined;
    } catch (error) {
        logger.error("Error getting consent data:", error);
        return undefined;
    }
};

const generateUUID = (): string => crypto.randomUUID();

export const getVisitorId = (): string => {
    try {
        const existingVisitorId = localStorage.getItem(VISITOR_ID_KEY) ?? undefined;
        if (existingVisitorId !== undefined && existingVisitorId !== "") {
            return existingVisitorId;
        }

        const newVisitorId = generateUUID();
        localStorage.setItem(VISITOR_ID_KEY, newVisitorId);
        return newVisitorId;
    } catch (error) {
        logger.error("Error getting/setting visitor ID:", error);
        return generateUUID();
    }
};
