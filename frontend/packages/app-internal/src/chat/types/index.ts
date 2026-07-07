import type {
    GroundingSourceStatus,
    LoadingActivityItem,
    LoadingActivityLogEntry,
    MessageSourceUsed,
} from "@va/shared/types";

export interface AssistantToolCallMessage {
    role: string;
    tool_calls?: {
        id?: string;
        function?: {
            name?: string;
            arguments?: string;
        };
    }[];
    tool_call_id?: string;
    name?: string;
    content?: string;
}

export interface MessageResponseUsage {
    inputTokens?: number;
    uncachedInputTokens?: number;
    cacheReadInputTokens?: number;
    outputTokens?: number;
}

export interface MessageResponseCostBreakdown {
    inputCost?: number;
    cacheReadInputCost?: number;
    outputCost?: number;
}

export interface MessageGuardrailsFailure {
    assistantMessage: string;
    llmGuardrailsFeedback?: string;
    invalidUrls?: string[];
}

export interface MessageGenerationTiming {
    totalTimeMs?: number;
    chatbotTimeMs?: number;
    guardrailTimeMs?: number;
    chatbotTimesMs?: number[];
    guardrailTimesMs?: number[];
    chatbotModel?: string;
    guardrailModel?: string;
}

export interface Message {
    id: string;
    role: "user" | "assistant";
    content: string;
    createdAt: number;
    parentId?: string;
    isError?: boolean;
    assistantToolCalls?: AssistantToolCallMessage[];
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
}

export type Rating = "thumbs_up" | "thumbs_down";

export interface MessageFeedback {
    id: string;
    rating: Rating;
    text?: string;
    user_id: string;
    user_name: string;
    is_current_user: boolean;
    created_at: string;
    updated_at: string;
}

export interface Chat {
    id: string;
    title?: string;
    summary?: string;
    lastMessagePreview?: string;
    updatedAt: number;
    isPublic: boolean;
    userName?: string;
    userEmail?: string;
    investigationSourceConversationId?: string;
    investigationSourceMessageId?: string;
    investigationSourceFeedbackId?: string;
    messages: Message[];
    isLoading: boolean;
    hasUnread: boolean;
    loadingActivity?: LoadingActivityItem[];
    loadingActivityLog?: LoadingActivityLogEntry[];
    parentMessageId?: string;
}

export interface ChatListItem {
    id: string;
    title?: string;
    summary?: string;
    last_message_preview?: string;
    message_count: number;
    created_at: string;
    updated_at: string;
    is_public: boolean;
    user_name?: string;
    user_email?: string;
}

export interface ChatDetailResponse {
    id: string;
    title?: string;
    summary?: string;
    is_public: boolean;
    user_name?: string;
    user_email?: string;
    investigation_source_conversation_id?: string | null;
    investigation_source_message_id?: string | null;
    investigation_source_feedback_id?: string | null;
    messages: {
        id: string;
        role: "user" | "assistant";
        content: string;
        guardrails_blocked?: boolean;
        guardrails_blocked_message?: string | null;
        parent_id?: string;
        created_at: string;
        assistant_tool_calls?: AssistantToolCallMessage[];
        generation_time_ms?: number;
        generation_timing?: {
            total_time_ms?: number;
            chatbot_time_ms?: number;
            guardrail_time_ms?: number;
            chatbot_times_ms?: number[];
            guardrail_times_ms?: number[];
            chatbot_model?: string;
            guardrail_model?: string;
        };
        response_cost?: number | null;
        response_usage?: {
            input_tokens?: number | null;
            uncached_input_tokens?: number | null;
            cache_read_input_tokens?: number | null;
            output_tokens?: number | null;
        } | null;
        response_cost_breakdown?: {
            input_cost?: number | null;
            cache_read_input_cost?: number | null;
            output_cost?: number | null;
        } | null;
        guardrails_failures?: {
            assistant_message: string;
            llm_guardrails_feedback?: string | null;
            invalid_urls?: string[] | null;
        }[] | null;
        tool_sources_used?: MessageSourceUsed[];
        grounding_sources_used?: MessageSourceUsed[];
        grounding_source_status?: GroundingSourceStatus | null;
        feedback?: MessageFeedback[];
    }[];
    created_at: string;
    updated_at: string;
}

interface ConversationTreeMessageResponse {
    id: string;
    role: "user" | "assistant";
    content: string;
    created_at: string;
    parent_id: string | null;
    guardrails_blocked?: boolean;
    guardrails_blocked_message?: string | null;
    feedback?: MessageFeedback[];
}

interface ConversationTreeNodeResponse {
    message: ConversationTreeMessageResponse;
    message_tree_nodes: ConversationTreeNodeResponse[];
}

export interface ConversationTreeResponse {
    message_tree_nodes: Record<string, ConversationTreeNodeResponse>;
    current_branch_path: string[];
    subtree_active_paths: Record<string, string[]>;
}

export interface ConversationDetailTreeResponse {
    id: string;
    title?: string;
    user: boolean;
    conversation_tree: ConversationTreeResponse;
    created_at: string;
    updated_at: string;
}

export interface ChatSearchResult {
    id: string;
    title?: string;
    snippet: string;
    updatedAt: string;
}

export interface ModelOverrides {
    chatbotModel?: string;
    guardrailModel?: string;
    chatbotReasoningEffort?: "none" | "low" | "medium" | "high" | "xhigh";
    guardrailReasoningEffort?: "none" | "low" | "medium" | "high" | "xhigh";
}
