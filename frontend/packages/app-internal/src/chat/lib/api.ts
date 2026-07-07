import { API_URL } from "@va/shared/config";
import { isRecord } from "@va/shared/lib/type-guards";
import type {
    GroundingSourceStatus,
    MessageSourceUsed,
} from "@va/shared/types";

import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import type {
    ChatDetailResponse,
    ChatListItem,
    ChatSearchResult,
    ConversationDetailTreeResponse,
    MessageFeedback,
    MessageGenerationTiming,
    MessageGuardrailsFailure,
    MessageResponseCostBreakdown,
    MessageResponseUsage,
    ModelOverrides,
    Rating,
} from "../types";
import { parseServerGuardrailsFailures } from "./guardrails";

const CHATS_BASE = "/conversations";

export type ChatCollectionKind = "chat" | "investigation";

export const fetchChats = async (
    api: AuthenticatedApi,
    kind: ChatCollectionKind = "chat",
): Promise<ChatListItem[]> =>
    api.get<ChatListItem[]>(
        kind === "investigation"
            ? `${CHATS_BASE}?kind=investigation`
            : CHATS_BASE,
    );

export const fetchChatDetail = async (
    api: AuthenticatedApi,
    chatId: string,
    options?: {
        source?:
            | "chat"
            | "chats"
            | "messages"
            | "investigate"
            | "investigations";
        targetMessageId?: string;
    },
): Promise<ChatDetailResponse> => {
    const query = new URLSearchParams();
    query.set("source", options?.source ?? "chat");
    if (options?.targetMessageId !== undefined) {
        query.set("target_message_id", options.targetMessageId);
    }
    return api.get<ChatDetailResponse>(
        `${CHATS_BASE}/${chatId}?${query.toString()}`,
    );
};

export const deleteChat = async (
    api: AuthenticatedApi,
    chatId: string,
): Promise<void> => {
    await api.delete(`${CHATS_BASE}/${chatId}`);
};

export const createInvestigationChat = async (
    api: AuthenticatedApi,
    params: {
        conversationId: string;
        messageId: string;
        feedbackId?: string;
    },
): Promise<string> => {
    const response: { conversation_id: string } = await api.post(
        `${CHATS_BASE}/investigations`,
        {
            conversation_id: params.conversationId,
            message_id: params.messageId,
            feedback_id: params.feedbackId,
        },
    );
    return response.conversation_id;
};

export const renameChatTitle = async (
    api: AuthenticatedApi,
    chatId: string,
    title: string,
): Promise<string> => {
    const response: { title: string } = await api.put(
        `${CHATS_BASE}/${chatId}/title`,
        {
            title,
        },
    );
    return response.title;
};

export const regenerateChatTitle = async (
    api: AuthenticatedApi,
    chatId: string,
): Promise<string> => {
    const response: { title: string } = await api.post(
        `${CHATS_BASE}/${chatId}/title/regenerate`,
        {},
    );
    return response.title;
};

interface ChatSearchResultResponse {
    id: string;
    title?: string | null;
    snippet: string;
    updated_at: string;
}

export const searchChats = async (
    api: AuthenticatedApi,
    params: {
        search: string;
        limit?: number;
        offset?: number;
    },
): Promise<ChatSearchResult[]> => {
    const query = new URLSearchParams();
    query.set("search", params.search.trim());
    if (params.offset !== undefined) {
        query.set("offset", String(params.offset));
    }
    if (params.limit !== undefined) {
        query.set("limit", String(params.limit));
    }

    const response = await api.get<ChatSearchResultResponse[]>(
        `${CHATS_BASE}/search?${query.toString()}`,
    );

    return response.map((item) => ({
        id: item.id,
        title: item.title ?? undefined,
        snippet: item.snippet,
        updatedAt: item.updated_at,
    }));
};

export const fetchInternalModels = async (
    api: AuthenticatedApi,
): Promise<string[]> => api.get<string[]>("/models");

export const fetchConversationTree = async (
    api: AuthenticatedApi,
    chatId: string,
): Promise<ConversationDetailTreeResponse> =>
    api.get<ConversationDetailTreeResponse>(`/conversations/${chatId}/tree`);

export const updateMessageActiveChild = async (
    api: AuthenticatedApi,
    messageId: string,
    activeChildId?: string,
): Promise<void> => {
    await api.put(`/conversations/messages/${messageId}/active-child`, {
        active_child_id: activeChildId ?? undefined,
    });
};

interface SendMessageCallbacks {
    onChatId: (
        chatId: string,
        parentMessageId?: string,
        chatTitle?: string,
    ) => void;
    onAssistantMessage: (payload: {
        assistantMessageId: string;
        content: string;
        parentMessageId?: string;
        userMessageId?: string;
        generationTimeMs?: number;
        generationTiming?: MessageGenerationTiming;
        responseCost?: number;
        responseUsage?: MessageResponseUsage;
        responseCostBreakdown?: MessageResponseCostBreakdown;
        guardrailsFailures?: MessageGuardrailsFailure[];
        guardrailsBlocked?: boolean;
        guardrailsBlockedMessage?: string;
        toolSourcesUsed?: MessageSourceUsed[];
        groundingSourcesUsed?: MessageSourceUsed[];
        groundingSourceStatus?: GroundingSourceStatus | null;
    }) => void;
    onGroundingSources?: (payload: {
        assistantMessageId: string;
        groundingSourcesUsed: MessageSourceUsed[];
        groundingSourceStatus: GroundingSourceStatus;
    }) => void;
    onError: (errorMessage: string) => void;
}

type ChatTitleStage = "initial" | "post_assistant";

type AgentStage = "chatbot" | "guardrails" | "investigation";

type AgentStageStatus = "start" | "end" | "error";

type ToolCallStatus = "start" | "end" | "error";

type ThinkingStatus = "start" | "delta" | "end";

interface AgentStageEvent {
    chatId: string;
    stage: AgentStage;
    status: AgentStageStatus;
    durationMs?: number;
    iteration?: number;
}

interface ToolCallEvent {
    chatId: string;
    stage?: AgentStage;
    status: ToolCallStatus;
    toolCallId: string;
    toolName?: string;
    toolInput?: unknown;
    toolOutput?: unknown;
    toolErrorText?: string;
    iteration?: number;
}

interface ThinkingEvent {
    chatId: string;
    status: ThinkingStatus;
    thinkingId: string;
    content?: string;
    stage?: AgentStage;
    iteration?: number;
}

interface SendMessageStreamCallbacks extends SendMessageCallbacks {
    onTitleUpdate: (
        chatId: string,
        title: string,
        stage: ChatTitleStage,
    ) => void;
    onAgentStage: (event: AgentStageEvent) => void;
    onToolCall: (event: ToolCallEvent) => void;
    onThinking: (event: ThinkingEvent) => void;
}

const parseSseEvent = (
    raw: string,
): {
    event: string;
    data: string;
} => {
    let event = "message";
    const dataLines: string[] = [];

    for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) {
            event = line.slice("event:".length).trim();
        } else if (line.startsWith("data:")) {
            dataLines.push(line.slice("data:".length).trim());
        }
    }

    return {
        event,
        data: dataLines.join("\n"),
    };
};

const parseSsePayload = (data: string): Record<string, unknown> | undefined => {
    try {
        const parsed: unknown = JSON.parse(data);
        return isRecord(parsed) ? parsed : undefined;
    } catch {
        return undefined;
    }
};

const isAgentStage = (value: unknown): value is AgentStage =>
    value === "chatbot" ||
    value === "guardrails" ||
    value === "investigation";

const isAgentStageStatus = (value: unknown): value is AgentStageStatus =>
    value === "start" || value === "end" || value === "error";

const isToolCallStatus = (value: unknown): value is ToolCallStatus =>
    value === "start" || value === "end" || value === "error";

const isThinkingStatus = (value: unknown): value is ThinkingStatus =>
    value === "start" || value === "delta" || value === "end";

const isMessageSourceType = (
    value: unknown,
): value is MessageSourceUsed["type"] =>
    value === "website_page" ||
    value === "website_program" ||
    value === "catalog_page" ||
    value === "catalog_program" ||
    value === "catalog_course" ||
    value === "training_material" ||
    value === "canned_response";

const isMessageSourceUsage = (
    value: unknown,
): value is MessageSourceUsed["usage"] =>
    value === "search" ||
    value === "lookup" ||
    value === "retrieved_by_id" ||
    value === "prompt";

const parseMessageSourcesUsed = (
    value: unknown,
    fieldName: "tool_sources_used" | "grounding_sources_used",
): MessageSourceUsed[] | undefined => {
    if (value === undefined || value === null) {
        return undefined;
    }
    if (!Array.isArray(value)) {
        throw new TypeError(`Invalid ${fieldName} payload`);
    }
    return value.map((item) => {
        if (!isRecord(item)) {
            throw new Error(`Invalid ${fieldName} item`);
        }
        if (
            !isMessageSourceType(item.type) ||
            typeof item.id !== "number" ||
            typeof item.key !== "string" ||
            typeof item.title !== "string" ||
            typeof item.url !== "string" ||
            !isMessageSourceUsage(item.usage) ||
            typeof item.tool_call_id !== "string" ||
            typeof item.tool_name !== "string" ||
            !(
                item.search_query === undefined ||
                item.search_query === null ||
                typeof item.search_query === "string"
            ) ||
            !(
                item.chunk === undefined ||
                item.chunk === null ||
                typeof item.chunk === "string"
            ) ||
            !(
                item.explanation === undefined ||
                item.explanation === null ||
                typeof item.explanation === "string"
            )
        ) {
            throw new Error(`Invalid ${fieldName} item`);
        }
        return {
            key: item.key,
            type: item.type,
            id: item.id,
            title: item.title,
            url: item.url,
            usage: item.usage,
            tool_call_id: item.tool_call_id,
            tool_name: item.tool_name,
            search_query: item.search_query,
            chunk: item.chunk,
            explanation: item.explanation,
        };
    });
};

const parseGroundingSourceStatus = (
    value: unknown,
): GroundingSourceStatus | null | undefined => {
    if (value === undefined) {
        return undefined;
    }
    if (value === null) {
        return null;
    }
    if (
        value === "pending" ||
        value === "selected" ||
        value === "no_selection"
    ) {
        return value;
    }
    throw new Error("Invalid grounding_source_status payload");
};

export const sendMessageStream = async (
    api: AuthenticatedApi,
    params: {
        userMessage: string;
        chatId?: string;
        parentMessageId?: string;
        promptSetVersionId?: string;
        modelOverrides?: ModelOverrides;
        isRegeneration?: boolean;
        conversationKind?: ChatCollectionKind;
    },
    callbacks: SendMessageStreamCallbacks,
    signal?: AbortSignal,
): Promise<void> => {
    const body: Record<string, unknown> = {
        user_prompt: params.userMessage,
    };

    if (params.chatId !== undefined) {
        body.conversation_id = params.chatId;
    }
    if (params.parentMessageId !== undefined) {
        body.parent_message_id = params.parentMessageId;
    }
    if (params.conversationKind === "investigation") {
        body.conversation_kind = "investigation";
    }
    if (
        params.promptSetVersionId !== undefined &&
        params.promptSetVersionId !== ""
    ) {
        body.prompt_set_version_id = params.promptSetVersionId;
    }
    const chatbotModel = params.modelOverrides?.chatbotModel;
    if (chatbotModel !== undefined && chatbotModel !== "") {
        body.chatbot_model = chatbotModel;
    }
    const guardrailModel = params.modelOverrides?.guardrailModel;
    if (guardrailModel !== undefined && guardrailModel !== "") {
        body.guardrail_model = guardrailModel;
    }
    const chatbotReasoningEffort =
        params.modelOverrides?.chatbotReasoningEffort;
    if (chatbotReasoningEffort !== undefined) {
        body.chatbot_reasoning_effort = chatbotReasoningEffort;
    }
    const guardrailReasoningEffort =
        params.modelOverrides?.guardrailReasoningEffort;
    if (guardrailReasoningEffort !== undefined) {
        body.guardrail_reasoning_effort = guardrailReasoningEffort;
    }
    if (params.isRegeneration === true) {
        body.is_regeneration = true;
    }

    const response = await api.postStream("/messages/internal/stream", body, {
        signal,
        baseUrl: API_URL,
    });

    const reader = response.body?.getReader();
    if (reader === undefined) {
        throw new Error("Missing streaming response body");
    }
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
        // eslint-disable-next-line no-await-in-loop
        const { value, done } = await reader.read();
        if (done) {
            break;
        }
        buffer += decoder.decode(value, { stream: true });
        buffer = buffer.replaceAll("\r\n", "\n");

        let splitIndex = buffer.indexOf("\n\n");
        while (splitIndex !== -1) {
            const rawEvent = buffer.slice(0, splitIndex).trim();
            buffer = buffer.slice(splitIndex + 2);
            splitIndex = buffer.indexOf("\n\n");

            if (rawEvent !== "") {
                const parsed = parseSseEvent(rawEvent);
                if (parsed.data !== "") {
                    const payload = parseSsePayload(parsed.data);
                    if (payload) {
                        switch (parsed.event) {
                            case "conversation": {
                                const chatId = payload.conversation_id;
                                if (typeof chatId === "string") {
                                    callbacks.onChatId(
                                        chatId,
                                        undefined,
                                        typeof payload.conversation_title ===
                                            "string"
                                            ? payload.conversation_title
                                            : undefined,
                                    );
                                }
                                break;
                            }
                            case "title_update": {
                                const {
                                    conversation_id: chatId,
                                    title,
                                    stage,
                                } = payload;
                                if (
                                    typeof chatId === "string" &&
                                    typeof title === "string" &&
                                    (stage === "initial" ||
                                        stage === "post_assistant")
                                ) {
                                    callbacks.onTitleUpdate(
                                        chatId,
                                        title,
                                        stage,
                                    );
                                }
                                break;
                            }
                            case "agent_stage": {
                                const {
                                    conversation_id: chatId,
                                    stage,
                                    status,
                                    duration_ms: durationMs,
                                    iteration,
                                } = payload;
                                if (
                                    typeof chatId === "string" &&
                                    isAgentStage(stage) &&
                                    isAgentStageStatus(status)
                                ) {
                                    callbacks.onAgentStage({
                                        chatId,
                                        stage,
                                        status,
                                        durationMs:
                                            typeof durationMs === "number"
                                                ? durationMs
                                                : undefined,
                                        iteration:
                                            typeof iteration === "number"
                                                ? iteration
                                                : undefined,
                                    });
                                }
                                break;
                            }
                            case "tool_call": {
                                const {
                                    conversation_id: chatId,
                                    tool_call_id: toolCallId,
                                    status,
                                    stage,
                                    tool_name: toolName,
                                    tool_input: toolInput,
                                    tool_output: toolOutput,
                                    tool_error_text: toolErrorText,
                                    iteration,
                                } = payload;
                                if (
                                    typeof chatId === "string" &&
                                    typeof toolCallId === "string" &&
                                    isToolCallStatus(status)
                                ) {
                                    callbacks.onToolCall({
                                        chatId,
                                        toolCallId,
                                        status,
                                        stage: isAgentStage(stage)
                                            ? stage
                                            : undefined,
                                        toolName:
                                            typeof toolName === "string"
                                                ? toolName
                                                : undefined,
                                        toolInput,
                                        toolOutput,
                                        toolErrorText:
                                            typeof toolErrorText === "string"
                                                ? toolErrorText
                                                : undefined,
                                        iteration:
                                            typeof iteration === "number"
                                                ? iteration
                                                : undefined,
                                    });
                                }
                                break;
                            }
                            case "thinking": {
                                const {
                                    conversation_id: chatId,
                                    status,
                                    thinking_id: thinkingId,
                                    content,
                                    stage,
                                    iteration,
                                } = payload;
                                if (
                                    typeof chatId === "string" &&
                                    typeof thinkingId === "string" &&
                                    isThinkingStatus(status)
                                ) {
                                    callbacks.onThinking({
                                        chatId,
                                        status,
                                        thinkingId,
                                        content:
                                            typeof content === "string"
                                                ? content
                                                : undefined,
                                        stage: isAgentStage(stage)
                                            ? stage
                                            : undefined,
                                        iteration:
                                            typeof iteration === "number"
                                                ? iteration
                                                : undefined,
                                    });
                                }
                                break;
                            }
                            case "assistant_message": {
                                const messageId = payload.assistant_message_id;
                                const content = payload.assistant_message;
                                const parentMessageId =
                                    payload.parent_message_id;
                                const userMessageId = payload.user_message_id;
                                const generationTimeMs =
                                    payload.generation_time_ms;
                                const generationTiming = isRecord(
                                    payload.generation_timing,
                                )
                                    ? payload.generation_timing
                                    : undefined;
                                const responseCost = payload.response_cost;
                                const responseUsage = isRecord(
                                    payload.response_usage,
                                )
                                    ? payload.response_usage
                                    : undefined;
                                const responseCostBreakdown = isRecord(
                                    payload.response_cost_breakdown,
                                )
                                    ? payload.response_cost_breakdown
                                    : undefined;
                                const guardrailsBlocked =
                                    payload.guardrails_blocked;
                                const guardrailsBlockedMessage =
                                    payload.guardrails_blocked_message;
                                const guardrailsFailures =
                                    parseServerGuardrailsFailures(
                                        payload.guardrails_failures,
                                    );
                                const toolSourcesUsed = parseMessageSourcesUsed(
                                    payload.tool_sources_used,
                                    "tool_sources_used",
                                );
                                const groundingSourcesUsed =
                                    parseMessageSourcesUsed(
                                        payload.grounding_sources_used,
                                        "grounding_sources_used",
                                    );
                                const groundingSourceStatus =
                                    parseGroundingSourceStatus(
                                        payload.grounding_source_status,
                                    );
                                if (
                                    typeof messageId === "string" &&
                                    typeof content === "string"
                                ) {
                                    callbacks.onAssistantMessage({
                                        assistantMessageId: messageId,
                                        content,
                                        parentMessageId:
                                            typeof parentMessageId === "string"
                                                ? parentMessageId
                                                : undefined,
                                        userMessageId:
                                            typeof userMessageId === "string"
                                                ? userMessageId
                                                : undefined,
                                        generationTimeMs:
                                            typeof generationTimeMs === "number"
                                                ? generationTimeMs
                                                : undefined,
                                        responseCost:
                                            typeof responseCost === "number"
                                                ? responseCost
                                                : undefined,
                                        responseUsage:
                                            responseUsage === undefined
                                                ? undefined
                                                : {
                                                      inputTokens:
                                                          typeof responseUsage.input_tokens ===
                                                          "number"
                                                              ? responseUsage.input_tokens
                                                              : undefined,
                                                      uncachedInputTokens:
                                                          typeof responseUsage.uncached_input_tokens ===
                                                          "number"
                                                              ? responseUsage.uncached_input_tokens
                                                              : undefined,
                                                      cacheReadInputTokens:
                                                          typeof responseUsage.cache_read_input_tokens ===
                                                          "number"
                                                              ? responseUsage.cache_read_input_tokens
                                                              : undefined,
                                                      outputTokens:
                                                          typeof responseUsage.output_tokens ===
                                                          "number"
                                                              ? responseUsage.output_tokens
                                                              : undefined,
                                                  },
                                        responseCostBreakdown:
                                            responseCostBreakdown === undefined
                                                ? undefined
                                                : {
                                                      inputCost:
                                                          typeof responseCostBreakdown.input_cost ===
                                                          "number"
                                                              ? responseCostBreakdown.input_cost
                                                              : undefined,
                                                      cacheReadInputCost:
                                                          typeof responseCostBreakdown.cache_read_input_cost ===
                                                          "number"
                                                              ? responseCostBreakdown.cache_read_input_cost
                                                              : undefined,
                                                      outputCost:
                                                          typeof responseCostBreakdown.output_cost ===
                                                          "number"
                                                              ? responseCostBreakdown.output_cost
                                                              : undefined,
                                                  },
                                        guardrailsFailures,
                                        guardrailsBlocked:
                                            typeof guardrailsBlocked ===
                                            "boolean"
                                                ? guardrailsBlocked
                                                : undefined,
                                        guardrailsBlockedMessage:
                                            typeof guardrailsBlockedMessage ===
                                            "string"
                                                ? guardrailsBlockedMessage
                                                : undefined,
                                        toolSourcesUsed,
                                        groundingSourcesUsed,
                                        groundingSourceStatus,
                                        generationTiming:
                                            generationTiming === undefined
                                                ? undefined
                                                : {
                                                      totalTimeMs:
                                                          typeof generationTiming.total_time_ms ===
                                                          "number"
                                                              ? generationTiming.total_time_ms
                                                              : undefined,
                                                      chatbotTimeMs:
                                                          typeof generationTiming.chatbot_time_ms ===
                                                          "number"
                                                              ? generationTiming.chatbot_time_ms
                                                              : undefined,
                                                      guardrailTimeMs:
                                                          typeof generationTiming.guardrail_time_ms ===
                                                          "number"
                                                              ? generationTiming.guardrail_time_ms
                                                              : undefined,
                                                      chatbotTimesMs:
                                                          Array.isArray(
                                                              generationTiming.chatbot_times_ms,
                                                          )
                                                              ? generationTiming.chatbot_times_ms.filter(
                                                                    (
                                                                        item,
                                                                    ): item is number =>
                                                                        typeof item ===
                                                                        "number",
                                                                )
                                                              : undefined,
                                                      guardrailTimesMs:
                                                          Array.isArray(
                                                              generationTiming.guardrail_times_ms,
                                                          )
                                                              ? generationTiming.guardrail_times_ms.filter(
                                                                    (
                                                                        item,
                                                                    ): item is number =>
                                                                        typeof item ===
                                                                        "number",
                                                                )
                                                              : undefined,
                                                      chatbotModel:
                                                          typeof generationTiming.chatbot_model ===
                                                          "string"
                                                              ? generationTiming.chatbot_model
                                                              : undefined,
                                                      guardrailModel:
                                                          typeof generationTiming.guardrail_model ===
                                                          "string"
                                                              ? generationTiming.guardrail_model
                                                              : undefined,
                                                  },
                                    });
                                }
                                break;
                            }
                            case "grounding_sources": {
                                const messageId = payload.assistant_message_id;
                                const groundingSourcesUsed =
                                    parseMessageSourcesUsed(
                                        payload.grounding_sources_used,
                                        "grounding_sources_used",
                                    );
                                const groundingSourceStatus =
                                    parseGroundingSourceStatus(
                                        payload.grounding_source_status,
                                    );
                                if (
                                    typeof messageId === "string" &&
                                    groundingSourcesUsed !== undefined &&
                                    groundingSourceStatus !== undefined &&
                                    groundingSourceStatus !== null
                                ) {
                                    callbacks.onGroundingSources?.({
                                        assistantMessageId: messageId,
                                        groundingSourcesUsed,
                                        groundingSourceStatus,
                                    });
                                }
                                break;
                            }
                            case "error": {
                                const { message } = payload;
                                if (typeof message === "string") {
                                    callbacks.onError(message);
                                }
                                break;
                            }
                            default: {
                                break;
                            }
                        }
                    }
                }
            }
        }
    }
};

export const fetchMessageFeedback = async (
    api: AuthenticatedApi,
    messageId: string,
    source: "chat" | "chats" = "chat",
): Promise<MessageFeedback[]> =>
    api
        .get<
            (Omit<MessageFeedback, "text"> & { text: string | null })[]
        >(`/conversations/messages/${messageId}/feedback?source=${source}`)
        .then((items) =>
            items.map((item) => ({
                ...item,
                text: item.text ?? undefined,
            })),
        );

export const submitMessageFeedback = async (
    api: AuthenticatedApi,
    messageId: string,
    feedback: {
        rating: Rating;
        text?: string;
    },
    source: "chat" | "chats" = "chat",
): Promise<MessageFeedback> =>
    api
        .post<Omit<MessageFeedback, "text"> & { text: string | null }>(
            `/conversations/messages/${messageId}/feedback?source=${source}`,
            {
                rating: feedback.rating,
                ...(feedback.text === undefined ? {} : { text: feedback.text }),
            },
        )
        .then((item) => ({
            ...item,
            text: item.text ?? undefined,
        }));

export const deleteMessageFeedback = async (
    api: AuthenticatedApi,
    feedbackId: string,
    source: "chat" | "chats" = "chat",
): Promise<void> => {
    await api.delete(
        `/conversations/messages/feedback/${feedbackId}?source=${source}`,
    );
};
