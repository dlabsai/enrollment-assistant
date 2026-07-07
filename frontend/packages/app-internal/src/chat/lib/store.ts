import { logger } from "@va/shared/lib/logger";
import type {
    LoadingActivityItem,
    LoadingActivityLogEntry,
} from "@va/shared/types";
import { nanoid } from "nanoid";
import { createStore } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";
import type { Mutate, StateCreator, StoreApi } from "zustand/vanilla";

import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { fetchTraceDetailByMessageId } from "../../traces/lib/api";
import type {
    Chat,
    ChatDetailResponse,
    ChatListItem,
    ConversationDetailTreeResponse,
    Message,
    MessageFeedback,
    ModelOverrides,
    Rating,
} from "../types";
import {
    type ChatCollectionKind,
    deleteChat as apiDeleteChat,
    deleteMessageFeedback as apiDeleteMessageFeedback,
    fetchChatDetail,
    fetchChats,
    fetchConversationTree,
    fetchMessageFeedback as apiFetchMessageFeedback,
    regenerateChatTitle as apiRegenerateChatTitle,
    renameChatTitle as apiRenameChatTitle,
    sendMessageStream as apiSendMessageStream,
    submitMessageFeedback as apiSubmitMessageFeedback,
    updateMessageActiveChild as apiUpdateMessageActiveChild,
} from "./api";
import { mapServerGuardrailsFailures } from "./guardrails";
import {
    buildActivityLogFromTrace,
    mergeActivityLogWithStoredToolCalls,
} from "./trace-activity";

interface ChatState {
    chats: Map<string, Chat>;
    chatsLoaded: boolean;
    chatsError?: string;

    conversationTrees: Map<string, ConversationTreeState>;
    conversationTreeLoading: Set<string>;

    messageFeedback: Map<string, MessageFeedback[]>;
    messageFeedbackLoading: Set<string>;
    messageActivityLog: Map<string, LoadingActivityLogEntry[]>;
    messageActivityLogLoading: Set<string>;

    currentChatId?: string;
    currentSummary?: string;

    abortControllers: Map<string, AbortController>;

    drafts: Map<string, string>;
    activityLogCounter: number;
}

interface ConversationTreeState {
    messagesById: Map<string, Message>;
    childrenByParent: Map<string, string[]>;
    currentBranchPath: string[];
}

type SortedChatsSelectorState = Pick<ChatState, "chats">;

type CurrentChatSelectorState = Pick<ChatState, "chats" | "currentChatId">;

type CurrentDraftSelectorState = Pick<ChatState, "drafts" | "currentChatId">;

export interface ChatActions {
    loadChats: () => Promise<void>;

    selectChat: (chatId?: string) => Promise<void>;
    reloadChat: (chatId: string) => Promise<void>;
    loadConversationTree: (chatId: string) => Promise<void>;
    setActiveChild: (
        chatId: string,
        messageId: string,
        activeChildId: string,
    ) => Promise<void>;
    clearCurrentChat: () => void;

    sendMessage: (
        content: string,
        modelOverrides?: ModelOverrides,
        options?: {
            parentMessageId?: string;
            isRegeneration?: boolean;
            trimToMessageId?: string;
        },
    ) => Promise<void>;

    deleteChat: (chatId: string) => Promise<void>;

    renameChatTitle: (chatId: string, title: string) => Promise<void>;
    regenerateChatTitle: (chatId: string) => Promise<void>;

    markCurrentAsRead: () => void;

    setDraft: (chatId: string | undefined, draft: string) => void;

    updateChat: (id: string, updater: (chat: Chat) => Chat) => void;

    loadMessageFeedback: (
        messageId: string,
        source?: "chat" | "chats",
    ) => Promise<void>;
    initializeMessageFeedback: (
        entries: { messageId: string; feedback: MessageFeedback[] }[],
    ) => void;
    loadMessageActivityLog: (messageId: string) => Promise<void>;
    submitMessageFeedback: (
        messageId: string,
        rating: Rating,
        text?: string,
        source?: "chat" | "chats",
    ) => Promise<void>;
    removeMessageFeedback: (
        messageId: string,
        source?: "chat" | "chats",
    ) => Promise<void>;
}

const generateTempId = (): string => `__temp_${nanoid(7)}`;

const getDraftKey = (chatId?: string): string => chatId ?? "__new__";

const truncate = (text: string, length: number): string => {
    if (text.length <= length) {
        return text;
    }
    return `${text.slice(0, length)}...`;
};

type AgentStage = "chatbot" | "guardrails" | "investigation";

type AgentStageStatus = "start" | "end" | "error";

type ToolCallStatus = "start" | "end" | "error";

const AGENT_STAGE_LABELS: Record<AgentStage, string> = {
    chatbot: "Chatbot agent",
    guardrails: "Guardrails agent",
    investigation: "Investigation agent",
};

const MIN_TOOL_ACTIVITY_MS = 800;

const toActivityStatus = (
    status: AgentStageStatus | ToolCallStatus,
): LoadingActivityItem["status"] => {
    switch (status) {
        case "start": {
            return "in_progress";
        }
        case "end": {
            return "complete";
        }
        default: {
            return "error";
        }
    }
};

const toToolState = (
    status: ToolCallStatus,
    hasError: boolean,
): LoadingActivityItem["toolState"] => {
    if (status === "start") {
        return "input-available";
    }
    if (status === "error" || hasError) {
        return "output-error";
    }
    return "output-available";
};

const createErrorMessage = (content: string): Message =>
    ({
        id: `error-${nanoid(7)}`,
        role: "assistant",
        content,
        createdAt: Date.now(),
        isError: true,
    }) satisfies Message;

const convertServerChat = (item: ChatListItem): Chat => ({
    id: item.id,
    title: item.title ?? undefined,
    summary: item.summary ?? undefined,
    lastMessagePreview: item.last_message_preview ?? undefined,
    updatedAt: new Date(item.updated_at).getTime(),
    isPublic: item.is_public,
    userName: item.user_name ?? undefined,
    userEmail: item.user_email ?? undefined,
    investigationSourceConversationId: undefined,
    investigationSourceMessageId: undefined,
    investigationSourceFeedbackId: undefined,
    messages: [],
    isLoading: false,
    hasUnread: false,
    loadingActivity: [],
    loadingActivityLog: [],
    parentMessageId: undefined,
});

const getDisplayContent = (message: {
    content: string;
    guardrails_blocked?: boolean;
    guardrails_blocked_message?: string | null;
}): string =>
    message.guardrails_blocked === true &&
    typeof message.guardrails_blocked_message === "string" &&
    message.guardrails_blocked_message !== ""
        ? message.guardrails_blocked_message
        : message.content;

const convertServerMessages = (
    response: ChatDetailResponse,
): { messages: Message[]; parentMessageId?: string } => {
    const messages: Message[] = response.messages.map((message) => ({
        id: message.id,
        role: message.role,
        content: getDisplayContent(message),
        createdAt: new Date(message.created_at).getTime(),
        parentId: message.parent_id ?? undefined,
        guardrailsBlocked: message.guardrails_blocked ?? false,
        guardrailsBlockedMessage: message.guardrails_blocked_message ?? undefined,
        assistantToolCalls: message.assistant_tool_calls ?? undefined,
        generationTimeMs: message.generation_time_ms ?? undefined,
        responseCost: message.response_cost ?? undefined,
        responseUsage:
            message.response_usage === undefined || message.response_usage === null
                ? undefined
                : {
                      inputTokens: message.response_usage.input_tokens ?? undefined,
                      uncachedInputTokens:
                          message.response_usage.uncached_input_tokens ?? undefined,
                      cacheReadInputTokens:
                          message.response_usage.cache_read_input_tokens ?? undefined,
                      outputTokens: message.response_usage.output_tokens ?? undefined,
                  },
        responseCostBreakdown:
            message.response_cost_breakdown === undefined ||
            message.response_cost_breakdown === null
                ? undefined
                : {
                      inputCost: message.response_cost_breakdown.input_cost ?? undefined,
                      cacheReadInputCost:
                          message.response_cost_breakdown.cache_read_input_cost ?? undefined,
                      outputCost: message.response_cost_breakdown.output_cost ?? undefined,
                  },
        guardrailsFailures: mapServerGuardrailsFailures(message.guardrails_failures),
        toolSourcesUsed: message.tool_sources_used,
        groundingSourcesUsed: message.grounding_sources_used,
        groundingSourceStatus: message.grounding_source_status,
        generationTiming:
            message.generation_timing === undefined
                ? undefined
                : {
                      totalTimeMs:
                          message.generation_timing.total_time_ms ?? undefined,
                      chatbotTimeMs:
                          message.generation_timing.chatbot_time_ms ??
                          undefined,
                      guardrailTimeMs:
                          message.generation_timing.guardrail_time_ms ??
                          undefined,
                      chatbotTimesMs:
                          message.generation_timing.chatbot_times_ms ??
                          undefined,
                      guardrailTimesMs:
                          message.generation_timing.guardrail_times_ms ??
                          undefined,
                      chatbotModel:
                          message.generation_timing.chatbot_model ?? undefined,
                      guardrailModel:
                          message.generation_timing.guardrail_model ??
                          undefined,
                  },
    }));

    const lastAssistant = response.messages.findLast(
        (message) => message.role === "assistant",
    );

    return {
        messages,
        parentMessageId: lastAssistant?.id ?? undefined,
    };
};

type ConversationTreeNode =
    ConversationDetailTreeResponse["conversation_tree"]["message_tree_nodes"][string];

const convertConversationTree = (
    response: ConversationDetailTreeResponse,
): ConversationTreeState => {
    const messagesById = new Map<string, Message>();
    const childrenByParent = new Map<string, string[]>();

    const addNode = (node: ConversationTreeNode): void => {
        const { message, message_tree_nodes: messageTreeNodes } = node;
        const messageId = message.id;
        messagesById.set(messageId, {
            id: messageId,
            role: message.role,
            content: getDisplayContent(message),
            createdAt: new Date(message.created_at).getTime(),
            parentId: message.parent_id ?? undefined,
            guardrailsBlocked: message.guardrails_blocked ?? false,
            guardrailsBlockedMessage: message.guardrails_blocked_message ?? undefined,
        });

        const childIds = messageTreeNodes.map((child) => child.message.id);
        if (childIds.length > 0) {
            childrenByParent.set(messageId, childIds);
        }

        for (const child of messageTreeNodes) {
            addNode(child);
        }
    };

    const { conversation_tree: conversationTree } = response;

    for (const rootNode of Object.values(conversationTree.message_tree_nodes)) {
        addNode(rootNode);
    }

    for (const [parentId, childIds] of childrenByParent.entries()) {
        const sorted = childIds.toSorted((left, right) => {
            const leftMessage = messagesById.get(left);
            const rightMessage = messagesById.get(right);
            const leftTime = leftMessage?.createdAt ?? 0;
            const rightTime = rightMessage?.createdAt ?? 0;
            return leftTime - rightTime;
        });
        childrenByParent.set(parentId, sorted);
    }

    return {
        messagesById,
        childrenByParent,
        currentBranchPath: conversationTree.current_branch_path,
    };
};

/**
 * Factory for a memoized selector that returns a stable array reference
 * as long as the chats Map instance doesn't change.
 */
export const createSelectSortedChats = () => {
    let lastChats = new Map<string, Chat>();
    let lastResult: Chat[] = [];

    return (state: SortedChatsSelectorState): Chat[] => {
        if (state.chats === lastChats) {
            return lastResult;
        }

        lastChats = state.chats;
        lastResult = [...state.chats.values()].toSorted(
            (left, right) => right.updatedAt - left.updatedAt,
        );
        return lastResult;
    };
};

export const selectCurrentChat = (
    state: CurrentChatSelectorState,
): Chat | undefined =>
    state.currentChatId === undefined
        ? undefined
        : (state.chats.get(state.currentChatId) ?? undefined);

export const selectCurrentDraft = (state: CurrentDraftSelectorState): string =>
    state.drafts.get(getDraftKey(state.currentChatId)) ?? "";

export const selectIsCurrentLoading = (
    state: CurrentChatSelectorState,
): boolean => {
    const chat = selectCurrentChat(state);
    return chat?.isLoading ?? false;
};

export type ChatStoreState = ChatState & ChatActions;

type ChatStoreMutators = [["zustand/subscribeWithSelector", never]];

export type ChatStore = Mutate<StoreApi<ChatStoreState>, ChatStoreMutators>;

type ChatSetState = Parameters<StateCreator<ChatStoreState>>[0];
type ChatGetState = Parameters<StateCreator<ChatStoreState>>[1];

const createInitialChatState = (): ChatState => ({
    chats: new Map(),
    chatsLoaded: false,
    chatsError: undefined,

    conversationTrees: new Map(),
    conversationTreeLoading: new Set(),

    messageFeedback: new Map(),
    messageFeedbackLoading: new Set(),
    messageActivityLog: new Map(),
    messageActivityLogLoading: new Set(),
    currentChatId: undefined,
    currentSummary: undefined,
    abortControllers: new Map(),
    drafts: new Map(),
    activityLogCounter: 0,
});

interface ChatStoreOptions {
    collectionKind?: ChatCollectionKind;
}

const createChatActions = (
    api: AuthenticatedApi,
    set: ChatSetState,
    get: ChatGetState,
    options: ChatStoreOptions = {},
): ChatActions => {
    const collectionKind = options.collectionKind ?? "chat";
    const getStoredToolCallsForMessage = (
        messageId: string,
    ): Message["assistantToolCalls"] | undefined => {
        for (const chat of get().chats.values()) {
            const message = chat.messages.find(
                (entry) => entry.id === messageId,
            );
            if (message?.assistantToolCalls !== undefined) {
                return message.assistantToolCalls;
            }
        }

        return undefined;
    };

    const hydrateMessageActivityLogFromTrace = async (
        messageId: string,
    ): Promise<void> => {
        const state = get();
        if (state.messageActivityLog.has(messageId)) {
            return;
        }
        if (state.messageActivityLogLoading.has(messageId)) {
            return;
        }

        const loading = new Set(state.messageActivityLogLoading);
        loading.add(messageId);
        set({ messageActivityLogLoading: loading });

        const storedToolCalls = getStoredToolCallsForMessage(messageId);

        try {
            const traceDetail = await fetchTraceDetailByMessageId(
                api,
                messageId,
                "chat_activity",
            );
            const activityLog = mergeActivityLogWithStoredToolCalls(
                buildActivityLogFromTrace(traceDetail),
                storedToolCalls,
            );
            const next = new Map(get().messageActivityLog);
            next.set(messageId, activityLog);
            set({ messageActivityLog: next });
        } catch (error) {
            logger.debug("Failed to hydrate activity log from trace", error);
            const next = new Map(get().messageActivityLog);
            next.set(
                messageId,
                mergeActivityLogWithStoredToolCalls([], storedToolCalls),
            );
            set({ messageActivityLog: next });
        } finally {
            const nextLoading = new Set(get().messageActivityLogLoading);
            nextLoading.delete(messageId);
            set({ messageActivityLogLoading: nextLoading });
        }
    };

    const applyChatDetail = (
        chatId: string,
        detail: ChatDetailResponse,
    ): void => {
        const { messages, parentMessageId } = convertServerMessages(detail);

        const nextMessageFeedback = new Map(get().messageFeedback);
        for (const message of detail.messages) {
            nextMessageFeedback.set(message.id, message.feedback ?? []);
        }

        const newChats = new Map(get().chats);
        const chat = newChats.get(chatId);

        newChats.set(chatId, {
            id: chatId,
            title: detail.title ?? chat?.title,
            summary: detail.summary ?? undefined,
            lastMessagePreview: chat?.lastMessagePreview,
            updatedAt: new Date(detail.updated_at).getTime(),
            isPublic: detail.is_public,
            userName: detail.user_name ?? undefined,
            userEmail: detail.user_email ?? undefined,
            investigationSourceConversationId:
                detail.investigation_source_conversation_id ?? undefined,
            investigationSourceMessageId:
                detail.investigation_source_message_id ?? undefined,
            investigationSourceFeedbackId:
                detail.investigation_source_feedback_id ?? undefined,
            messages,
            parentMessageId,
            isLoading: false,
            hasUnread: false,
            loadingActivity: [],
            loadingActivityLog: [],
        });
        set({
            chats: newChats,
            messageFeedback: nextMessageFeedback,
            currentSummary: detail.summary ?? undefined,
        });
    };

    return {
        loadChats: async (): Promise<void> => {
            set({ chatsError: undefined });

            try {
                const items = await fetchChats(api, collectionKind);
                const chats = new Map<string, Chat>();

                for (const item of items) {
                    chats.set(item.id, convertServerChat(item));
                }

                set({
                    chats,
                    chatsLoaded: true,
                });
            } catch (error) {
                const message =
                    error instanceof Error
                        ? error.message
                        : "Failed to load chats";
                set({ chatsError: message });
            }
        },

        selectChat: async (chatId?: string): Promise<void> => {
            const { chats } = get();

            if (chatId === undefined) {
                set({
                    currentChatId: undefined,
                    currentSummary: undefined,
                });
                return;
            }

            if (chatId.startsWith("__temp_")) {
                set({ currentChatId: chatId });
                get().markCurrentAsRead();
                return;
            }

            set({ currentChatId: chatId });
            get().markCurrentAsRead();

            if (!get().conversationTrees.has(chatId)) {
                void get().loadConversationTree(chatId);
            }

            const existing = chats.get(chatId);
            if (existing && existing.messages.length > 0) {
                set({ currentSummary: existing.summary });
                return;
            }

            try {
                const detail = await fetchChatDetail(api, chatId, {
                    source: collectionKind === "investigation" ? "investigate" : "chat",
                });
                applyChatDetail(chatId, detail);
            } catch (error) {
                logger.error("Failed to load chat detail:", error);
            }
        },

        reloadChat: async (chatId: string): Promise<void> => {
            if (chatId.startsWith("__temp_")) {
                return;
            }

            try {
                const detail = await fetchChatDetail(api, chatId, {
                    source: collectionKind === "investigation" ? "investigate" : "chat",
                });
                applyChatDetail(chatId, detail);
            } catch (error) {
                logger.error("Failed to reload chat detail:", error);
            }
        },

        loadConversationTree: async (chatId: string): Promise<void> => {
            if (chatId.startsWith("__temp_")) {
                return;
            }

            const state = get();
            if (state.conversationTreeLoading.has(chatId)) {
                return;
            }

            const loading = new Set(state.conversationTreeLoading);
            loading.add(chatId);
            set({ conversationTreeLoading: loading });

            try {
                const detail = await fetchConversationTree(api, chatId);
                const tree = convertConversationTree(detail);
                const nextTrees = new Map(get().conversationTrees);
                nextTrees.set(chatId, tree);
                set({ conversationTrees: nextTrees });
            } catch (error) {
                logger.error("Failed to load conversation tree:", error);
            } finally {
                const nextLoading = new Set(get().conversationTreeLoading);
                nextLoading.delete(chatId);
                set({ conversationTreeLoading: nextLoading });
            }
        },

        setActiveChild: async (
            chatId: string,
            messageId: string,
            activeChildId: string,
        ): Promise<void> => {
            try {
                await apiUpdateMessageActiveChild(
                    api,
                    messageId,
                    activeChildId,
                );
                await get().reloadChat(chatId);
                await get().loadConversationTree(chatId);
            } catch (error) {
                logger.error("Failed to switch branch:", error);
                throw error;
            }
        },

        clearCurrentChat: (): void => {
            set({ currentChatId: undefined, currentSummary: undefined });
        },

        sendMessage: async (
            content: string,
            modelOverrides?: ModelOverrides,
            options?: {
                parentMessageId?: string;
                isRegeneration?: boolean;
                trimToMessageId?: string;
            },
        ): Promise<void> => {
            const { currentChatId, chats, abortControllers } = get();

            const isRegeneration = options?.isRegeneration === true;
            const trimToMessageId = options?.trimToMessageId;
            const overrideParentMessageId = options?.parentMessageId;

            const isNewChat = currentChatId === undefined;
            const targetId = currentChatId ?? generateTempId();

            if (isRegeneration && isNewChat) {
                return;
            }

            const inferredParentMessageId = isNewChat
                ? undefined
                : (overrideParentMessageId ??
                  get().chats.get(targetId)?.parentMessageId ??
                  undefined);

            const existingController = abortControllers.get(targetId);
            if (existingController) {
                existingController.abort();
            }

            const abortController = new AbortController();
            const newAbortControllers = new Map(abortControllers);
            newAbortControllers.set(targetId, abortController);
            set({ abortControllers: newAbortControllers });

            const optimisticUserMessageId = `user-${nanoid(7)}`;
            const userMessage: Message = {
                id: optimisticUserMessageId,
                role: "user",
                content,
                createdAt: Date.now(),
                parentId: inferredParentMessageId,
            };

            const trimMessages = (messages: Message[]): Message[] => {
                if (trimToMessageId === undefined) {
                    return messages;
                }
                const trimIndex = messages.findIndex(
                    (message) => message.id === trimToMessageId,
                );
                if (trimIndex === -1) {
                    return messages;
                }
                return messages.slice(0, trimIndex + 1);
            };

            const newChats = new Map(chats);

            if (isNewChat) {
                const newChat: Chat = {
                    id: targetId,
                    title: truncate(content, 50),
                    summary: undefined,
                    lastMessagePreview: undefined,
                    updatedAt: Date.now(),
                    isPublic: false,
                    messages: [userMessage],
                    isLoading: true,
                    hasUnread: false,
                    loadingActivity: [],
                    loadingActivityLog: [],
                    parentMessageId: undefined,
                };
                newChats.set(targetId, newChat);
                set({
                    chats: newChats,
                    currentChatId: targetId,
                });
            } else {
                const existing = newChats.get(targetId);
                if (existing) {
                    const trimmedMessages = trimMessages(existing.messages);
                    const nextMessages = isRegeneration
                        ? trimmedMessages
                        : [...trimmedMessages, userMessage];
                    newChats.set(targetId, {
                        ...existing,
                        messages: nextMessages,
                        isLoading: true,
                        updatedAt: Date.now(),
                        loadingActivity: [],
                        loadingActivityLog: [],
                    });
                    set({
                        chats: newChats,
                    });
                }
            }

            // These variables are set in callbacks but TypeScript control flow doesn't track this
            // Start with the optimistic (local) id, then replace it if the API returns a real id.
            let realChatId = targetId;
            let newParentMessageId = "";

            const clearCurrentAbortController = (): void => {
                const controllers = get().abortControllers;
                const newControllers = new Map(controllers);
                for (const chatId of new Set([targetId, realChatId])) {
                    if (newControllers.get(chatId) === abortController) {
                        newControllers.delete(chatId);
                    }
                }
                if (newControllers.size !== controllers.size) {
                    set({ abortControllers: newControllers });
                }
            };

            const getActivityItem = (
                chatId: string,
                id: string,
            ): LoadingActivityItem | undefined =>
                get()
                    .chats.get(chatId)
                    ?.loadingActivity?.find((item) => item.id === id);

            const getActivityLogEntry = (
                chatId: string,
                id: string,
            ): LoadingActivityLogEntry | undefined =>
                get()
                    .chats.get(chatId)
                    ?.loadingActivityLog?.find((item) => item.id === id);

            const upsertLoadingActivity = (
                chatId: string,
                item: LoadingActivityItem,
            ): void => {
                get().updateChat(chatId, (chat) => {
                    const current = chat.loadingActivity ?? [];
                    const existingIndex = current.findIndex(
                        (entry) => entry.id === item.id,
                    );
                    if (existingIndex === -1) {
                        return {
                            ...chat,
                            loadingActivity: [...current, item],
                        };
                    }

                    const next = [...current];
                    next[existingIndex] = { ...next[existingIndex], ...item };
                    return {
                        ...chat,
                        loadingActivity: next,
                    };
                });
            };

            const nextActivityLogSequence = (): number => {
                const next = get().activityLogCounter + 1;
                set({ activityLogCounter: next });
                return next;
            };

            const upsertActivityLog = (
                chatId: string,
                entry: Omit<LoadingActivityLogEntry, "sequence">,
            ): void => {
                get().updateChat(chatId, (chat) => {
                    const current = chat.loadingActivityLog ?? [];
                    const existingIndex = current.findIndex(
                        (item) => item.id === entry.id,
                    );
                    if (existingIndex === -1) {
                        const sequence = nextActivityLogSequence();
                        const logEntry: LoadingActivityLogEntry = {
                            ...entry,
                            sequence,
                        };
                        return {
                            ...chat,
                            loadingActivityLog: [...current, logEntry],
                        };
                    }

                    const next = [...current];
                    next[existingIndex] = { ...next[existingIndex], ...entry };
                    return {
                        ...chat,
                        loadingActivityLog: next,
                    };
                });
            };

            const toolActivityStartTimes = new Map<string, number>();
            const thinkingLogIds = new Map<string, string>();

            try {
                const parentMessageId = inferredParentMessageId;

                await apiSendMessageStream(
                    api,
                    {
                        userMessage: content,
                        chatId: isNewChat ? undefined : currentChatId,
                        parentMessageId,
                        modelOverrides,
                        isRegeneration,
                        conversationKind: collectionKind,
                    },
                    {
                        onChatId: (chatId, parentMsgId, chatTitle) => {
                            realChatId = chatId;
                            newParentMessageId = parentMsgId ?? "";

                            if (isNewChat && chatId !== targetId) {
                                const currentChats = get().chats;
                                const tempChat = currentChats.get(targetId);

                                if (tempChat) {
                                    const updatedChats = new Map(currentChats);
                                    updatedChats.delete(targetId);
                                    updatedChats.set(chatId, {
                                        ...tempChat,
                                        id: chatId,
                                        title: chatTitle ?? tempChat.title,
                                    });

                                    const controllers = get().abortControllers;
                                    const controller =
                                        controllers.get(targetId);
                                    if (controller) {
                                        const newControllers = new Map(
                                            controllers,
                                        );
                                        newControllers.delete(targetId);
                                        newControllers.set(chatId, controller);
                                        set({
                                            abortControllers: newControllers,
                                        });
                                    }

                                    const { drafts } = get();
                                    const tempDraft = drafts.get(targetId);
                                    if (tempDraft !== undefined) {
                                        const newDrafts = new Map(drafts);
                                        newDrafts.delete(targetId);
                                        newDrafts.set(chatId, tempDraft);
                                        set({ drafts: newDrafts });
                                    }

                                    const currentId = get().currentChatId;
                                    if (currentId === targetId) {
                                        set({
                                            chats: updatedChats,
                                            currentChatId: chatId,
                                        });
                                    } else {
                                        set({
                                            chats: updatedChats,
                                        });
                                    }
                                }
                            } else if (chatTitle !== undefined) {
                                get().updateChat(chatId, (chat) => ({
                                    ...chat,
                                    title: chatTitle,
                                }));
                            }
                        },

                        onTitleUpdate: (chatId, title, stage) => {
                            void stage;
                            get().updateChat(chatId, (chat) => ({
                                ...chat,
                                title,
                            }));
                        },

                        onAgentStage: (event) => {
                            const label = AGENT_STAGE_LABELS[event.stage];
                            const activityId =
                                event.iteration === undefined
                                    ? `agent:${event.stage}`
                                    : `agent:${event.stage}:${event.iteration}`;
                            const status = toActivityStatus(event.status);
                            const existingLog = getActivityLogEntry(
                                event.chatId,
                                activityId,
                            );
                            const startedAtMs =
                                event.status === "start"
                                    ? Date.now()
                                    : existingLog?.startedAtMs;
                            const durationMs =
                                event.status === "start"
                                    ? undefined
                                    : (event.durationMs ??
                                      (startedAtMs === undefined
                                          ? undefined
                                          : Date.now() - startedAtMs));

                            upsertLoadingActivity(event.chatId, {
                                id: activityId,
                                label,
                                status,
                                kind: "agent",
                            });

                            upsertActivityLog(event.chatId, {
                                id: activityId,
                                label,
                                status,
                                kind: "agent",
                                startedAtMs,
                                durationMs,
                            });
                        },

                        onToolCall: (event) => {
                            const activityId = `tool:${event.toolCallId}`;
                            const existing = getActivityItem(
                                event.chatId,
                                activityId,
                            );
                            const label =
                                event.toolName !== undefined &&
                                event.toolName !== ""
                                    ? `Using tool: ${event.toolName}`
                                    : (existing?.label ?? "Using tool");
                            const parentId =
                                event.stage === undefined
                                    ? undefined
                                    : `agent:${event.stage}${
                                          event.iteration === undefined
                                              ? ""
                                              : `:${event.iteration}`
                                      }`;
                            const nextStatus = toActivityStatus(event.status);
                            const toolErrorText =
                                event.toolErrorText ?? existing?.toolErrorText;
                            const toolInput =
                                event.toolInput ?? existing?.toolInput;
                            const toolOutput =
                                event.toolOutput ?? existing?.toolOutput;
                            const toolName =
                                event.toolName ?? existing?.toolName;
                            const toolState = toToolState(
                                event.status,
                                Boolean(toolErrorText),
                            );

                            const nextItem: LoadingActivityItem = {
                                id: activityId,
                                label,
                                status: nextStatus,
                                parentId,
                                kind: "tool",
                                toolState,
                                toolName,
                                toolInput,
                                toolOutput,
                                toolErrorText,
                            };

                            const applyUpdate = (): void => {
                                upsertLoadingActivity(event.chatId, nextItem);
                                upsertActivityLog(event.chatId, {
                                    id: activityId,
                                    label,
                                    status: nextStatus,
                                    kind: "tool",
                                    parentId,
                                    toolState,
                                    toolName,
                                    toolInput,
                                    toolOutput,
                                    toolErrorText,
                                });
                            };

                            if (event.status === "start") {
                                toolActivityStartTimes.set(
                                    activityId,
                                    Date.now(),
                                );
                                applyUpdate();
                                return;
                            }

                            const startedAt =
                                toolActivityStartTimes.get(activityId) ??
                                Date.now();
                            const elapsedMs = Date.now() - startedAt;
                            const delayMs = Math.max(
                                0,
                                MIN_TOOL_ACTIVITY_MS - elapsedMs,
                            );

                            if (delayMs === 0) {
                                applyUpdate();
                                return;
                            }

                            setTimeout(() => {
                                applyUpdate();
                            }, delayMs);
                        },

                        onThinking: (event) => {
                            const activityId = `thinking:${event.thinkingId}`;
                            const existing = getActivityItem(
                                event.chatId,
                                activityId,
                            );
                            const label =
                                event.stage === undefined
                                    ? "Reasoning"
                                    : `${AGENT_STAGE_LABELS[event.stage]} reasoning`;
                            const parentId =
                                event.stage === undefined
                                    ? undefined
                                    : `agent:${event.stage}${
                                          event.iteration === undefined
                                              ? ""
                                              : `:${event.iteration}`
                                      }`;
                            const nextStatus =
                                event.status === "end"
                                    ? "complete"
                                    : "in_progress";
                            const nextContent =
                                event.content ?? existing?.thinkingContent;
                            const currentLogId = thinkingLogIds.get(
                                event.thinkingId,
                            );
                            const existingLog =
                                currentLogId === undefined
                                    ? undefined
                                    : get()
                                          .chats.get(event.chatId)
                                          ?.loadingActivityLog?.find(
                                              (item) =>
                                                  item.id === currentLogId,
                                          );
                            const shouldStartNew =
                                event.status === "start" ||
                                currentLogId === undefined ||
                                existingLog?.status === "complete";
                            const logId = shouldStartNew
                                ? `thinking:${event.thinkingId}:${nanoid(6)}`
                                : currentLogId;
                            thinkingLogIds.set(event.thinkingId, logId);

                            upsertLoadingActivity(event.chatId, {
                                id: activityId,
                                label: existing?.label ?? label,
                                status: nextStatus,
                                parentId,
                                kind: "thinking",
                                thinkingContent: nextContent,
                            });

                            upsertActivityLog(event.chatId, {
                                id: logId,
                                label: existing?.label ?? label,
                                status: nextStatus,
                                kind: "thinking",
                                parentId,
                                thinkingContent: nextContent,
                            });
                        },

                        onAssistantMessage: ({
                            assistantMessageId,
                            content: messageContent,
                            parentMessageId: assistantParentId,
                            userMessageId,
                            generationTimeMs,
                            generationTiming,
                            responseCost,
                            responseUsage,
                            responseCostBreakdown,
                            guardrailsFailures,
                            guardrailsBlocked,
                            guardrailsBlockedMessage,
                            toolSourcesUsed,
                            groundingSourcesUsed,
                            groundingSourceStatus,
                        }) => {
                            const finalChatId = realChatId;
                            const activeChat = get().chats.get(finalChatId);
                            if (
                                !isRegeneration &&
                                userMessageId !== undefined &&
                                activeChat !== undefined
                            ) {
                                const messages = activeChat.messages.map(
                                    (message) => {
                                        if (
                                            message.id !==
                                            optimisticUserMessageId
                                        ) {
                                            return message;
                                        }
                                        return {
                                            ...message,
                                            id: userMessageId,
                                        };
                                    },
                                );
                                get().updateChat(finalChatId, (chat) => ({
                                    ...chat,
                                    messages,
                                }));
                            }
                            const assistantMessage: Message = {
                                id: assistantMessageId,
                                role: "assistant",
                                content: messageContent,
                                createdAt: Date.now(),
                                parentId: assistantParentId,
                                generationTimeMs,
                                generationTiming,
                                responseCost,
                                responseUsage,
                                responseCostBreakdown,
                                guardrailsFailures,
                                guardrailsBlocked,
                                guardrailsBlockedMessage,
                                toolSourcesUsed,
                                groundingSourcesUsed,
                                groundingSourceStatus,
                            };

                            if (newParentMessageId === "") {
                                newParentMessageId = assistantMessageId;
                            }

                            get().updateChat(finalChatId, (chat) => ({
                                ...chat,
                                messages: [...chat.messages, assistantMessage],
                                isLoading: false,
                                hasUnread: get().currentChatId !== finalChatId,
                                lastMessagePreview: truncate(
                                    messageContent,
                                    50,
                                ),
                                parentMessageId: newParentMessageId,
                                updatedAt: Date.now(),
                            }));

                            if (
                                !get().messageFeedback.has(assistantMessageId)
                            ) {
                                const nextMessageFeedback = new Map(
                                    get().messageFeedback,
                                );
                                nextMessageFeedback.set(assistantMessageId, []);
                                set({ messageFeedback: nextMessageFeedback });
                            }

                            const activityLogSnapshot =
                                get().chats.get(finalChatId)
                                    ?.loadingActivityLog ?? [];
                            if (activityLogSnapshot.length > 0) {
                                const nextActivityLog = new Map(
                                    get().messageActivityLog,
                                );
                                nextActivityLog.set(assistantMessageId, [
                                    ...activityLogSnapshot,
                                ]);
                                set({ messageActivityLog: nextActivityLog });
                            }

                            clearCurrentAbortController();

                            void get().loadConversationTree(finalChatId);
                        },

                        onGroundingSources: ({
                            assistantMessageId,
                            groundingSourcesUsed,
                            groundingSourceStatus,
                        }) => {
                            const finalChatId = realChatId;
                            get().updateChat(finalChatId, (chat) => ({
                                ...chat,
                                messages: chat.messages.map((message) =>
                                    message.id === assistantMessageId
                                        ? {
                                              ...message,
                                              groundingSourcesUsed,
                                              groundingSourceStatus,
                                          }
                                        : message,
                                ),
                            }));
                        },

                        onError: (errorMessage) => {
                            const finalChatId = realChatId;
                            const errorMsg = createErrorMessage(errorMessage);
                            get().updateChat(finalChatId, (chat) => ({
                                ...chat,
                                messages: [...chat.messages, errorMsg],
                                isLoading: false,
                                hasUnread: get().currentChatId !== finalChatId,
                            }));
                        },
                    },
                    abortController.signal,
                );
            } catch (error) {
                const isAbortError =
                    error instanceof Error && error.name === "AbortError";
                if (!isAbortError) {
                    logger.error("Error sending message:", error);

                    const finalChatId = realChatId;
                    const errorMsg = createErrorMessage(
                        "Sorry, I encountered an error processing your request. Please try again.",
                    );
                    get().updateChat(finalChatId, (chat) => ({
                        ...chat,
                        messages: [...chat.messages, errorMsg],
                        isLoading: false,
                        hasUnread: get().currentChatId !== finalChatId,
                    }));
                }
            } finally {
                clearCurrentAbortController();
            }
        },

        deleteChat: async (chatId: string): Promise<void> => {
            const { chats, currentChatId } = get();

            const newChats = new Map(chats);
            newChats.delete(chatId);

            const { drafts } = get();
            const newDrafts = new Map(drafts);
            newDrafts.delete(chatId);

            const newTrees = new Map(get().conversationTrees);
            newTrees.delete(chatId);

            const nextTreeLoading = new Set(get().conversationTreeLoading);
            nextTreeLoading.delete(chatId);
            set({
                chats: newChats,
                drafts: newDrafts,
                conversationTrees: newTrees,
                conversationTreeLoading: nextTreeLoading,
            });

            if (currentChatId === chatId) {
                set({
                    currentChatId: undefined,
                    currentSummary: undefined,
                });
            }

            try {
                await apiDeleteChat(api, chatId);
            } catch (error) {
                logger.error("Failed to delete chat:", error);
                const oldChat = chats.get(chatId);
                if (oldChat) {
                    const restoredChats = new Map(get().chats);
                    restoredChats.set(chatId, oldChat);
                    set({
                        chats: restoredChats,
                    });
                }
                throw error;
            }
        },

        renameChatTitle: async (
            chatId: string,
            title: string,
        ): Promise<void> => {
            const trimmed = title.trim();
            if (trimmed === "") {
                return;
            }

            const updatedTitle = await apiRenameChatTitle(api, chatId, trimmed);

            get().updateChat(chatId, (chat) => ({
                ...chat,
                title: updatedTitle,
            }));
        },

        regenerateChatTitle: async (chatId: string): Promise<void> => {
            const updatedTitle = await apiRegenerateChatTitle(api, chatId);

            get().updateChat(chatId, (chat) => ({
                ...chat,
                title: updatedTitle,
            }));
        },

        markCurrentAsRead: (): void => {
            const { currentChatId, chats } = get();
            if (currentChatId === undefined) {
                return;
            }

            const chat = chats.get(currentChatId);
            if (chat?.hasUnread === true) {
                get().updateChat(currentChatId, (chat) => ({
                    ...chat,
                    hasUnread: false,
                }));
            }
        },

        setDraft: (chatId: string | undefined, draft: string): void => {
            const key = getDraftKey(chatId);
            const current = get().drafts.get(key) ?? "";
            if (current === draft) {
                return;
            }

            const nextDrafts = new Map(get().drafts);
            if (draft === "") {
                nextDrafts.delete(key);
            } else {
                nextDrafts.set(key, draft);
            }
            set({ drafts: nextDrafts });
        },

        updateChat: (id: string, updater: (chat: Chat) => Chat): void => {
            const { chats } = get();
            const chat = chats.get(id);
            if (!chat) {
                return;
            }

            const newChats = new Map(chats);
            newChats.set(id, updater(chat));
            set({
                chats: newChats,
            });
        },

        loadMessageFeedback: async (
            messageId: string,
            source: "chat" | "chats" = "chat",
        ): Promise<void> => {
            if (messageId.startsWith("error-")) {
                return;
            }

            const state = get();
            if (state.messageFeedback.has(messageId)) {
                return;
            }

            const loading = new Set(state.messageFeedbackLoading);
            loading.add(messageId);
            set({ messageFeedbackLoading: loading });

            try {
                const list = await apiFetchMessageFeedback(
                    api,
                    messageId,
                    source,
                );

                const next = new Map(get().messageFeedback);
                next.set(messageId, list);
                set({ messageFeedback: next });
            } catch (error) {
                logger.error("Failed to load message feedback:", error);
                const next = new Map(get().messageFeedback);
                next.set(messageId, []);
                set({ messageFeedback: next });
            } finally {
                const nextLoading = new Set(get().messageFeedbackLoading);
                nextLoading.delete(messageId);
                set({ messageFeedbackLoading: nextLoading });
            }
        },

        initializeMessageFeedback: (
            entries: { messageId: string; feedback: MessageFeedback[] }[],
        ): void => {
            if (entries.length === 0) {
                return;
            }

            const next = new Map(get().messageFeedback);
            for (const entry of entries) {
                if (!entry.messageId.startsWith("error-")) {
                    next.set(entry.messageId, entry.feedback);
                }
            }
            set({ messageFeedback: next });
        },

        loadMessageActivityLog: async (messageId: string): Promise<void> => {
            if (messageId.startsWith("error-")) {
                return;
            }

            await hydrateMessageActivityLogFromTrace(messageId);
        },

        submitMessageFeedback: async (
            messageId: string,
            rating: Rating,
            text?: string,
            source: "chat" | "chats" = "chat",
        ): Promise<void> => {
            if (messageId.startsWith("error-")) {
                return;
            }

            const loading = new Set(get().messageFeedbackLoading);
            loading.add(messageId);
            set({ messageFeedbackLoading: loading });

            try {
                const saved = await apiSubmitMessageFeedback(
                    api,
                    messageId,
                    {
                        rating,
                        text,
                    },
                    source,
                );

                const next = new Map(get().messageFeedback);
                const existing = next.get(messageId) ?? [];
                const updatedList = existing.filter(
                    (item) => !item.is_current_user,
                );
                updatedList.push(saved);
                next.set(messageId, updatedList);
                set({ messageFeedback: next });
            } catch (error) {
                logger.error("Failed to submit message feedback:", error);
            } finally {
                const nextLoading = new Set(get().messageFeedbackLoading);
                nextLoading.delete(messageId);
                set({ messageFeedbackLoading: nextLoading });
            }
        },

        removeMessageFeedback: async (
            messageId: string,
            source: "chat" | "chats" = "chat",
        ): Promise<void> => {
            if (messageId.startsWith("error-")) {
                return;
            }

            const feedbackList = get().messageFeedback.get(messageId) ?? [];
            const currentUserFeedback = feedbackList.find(
                (item) => item.is_current_user,
            );
            if (!currentUserFeedback) {
                return;
            }

            const loading = new Set(get().messageFeedbackLoading);
            loading.add(messageId);
            set({ messageFeedbackLoading: loading });

            try {
                await apiDeleteMessageFeedback(
                    api,
                    currentUserFeedback.id,
                    source,
                );
                const next = new Map(get().messageFeedback);
                const updatedList = feedbackList.filter(
                    (item) => !item.is_current_user,
                );
                next.set(messageId, updatedList);
                set({ messageFeedback: next });
            } catch (error) {
                logger.error("Failed to remove message feedback:", error);
            } finally {
                const nextLoading = new Set(get().messageFeedbackLoading);
                nextLoading.delete(messageId);
                set({ messageFeedbackLoading: nextLoading });
            }
        },
    };
};

export const createChatStore = (
    api: AuthenticatedApi,
    options: ChatStoreOptions = {},
): ChatStore =>
    createStore<ChatStoreState>()(
        subscribeWithSelector((set, get) => ({
            ...createInitialChatState(),
            ...createChatActions(api, set, get, options),
        })),
    );
