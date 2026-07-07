import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import {
    type CustomTimeRange,
    getTimeRangeQueryParams,
    type TimeRangeValue,
} from "../../lib/time-range";
import type { MessageListPage } from "../types";

interface MessageListItemResponse {
    id: string;
    conversation_id: string;
    role: string;
    content: string;
    content_preview: string;
    content_length: number;
    conversation_title?: string | null;
    conversation_summary?: string | null;
    is_public: boolean;
    conversation_user_name?: string | null;
    conversation_user_email?: string | null;
    generation_time_ms?: number | null;
    input_tokens?: number | null;
    output_tokens?: number | null;
    tool_call_count: number;
    guardrail_failure_count: number;
    guardrails_blocked: boolean;
    trace_id?: string | null;
    span_id?: string | null;
    created_at: string;
    updated_at: string;
}

interface MessageListResponse {
    items: MessageListItemResponse[];
    total: number;
}

export const fetchMessageListPage = async (
    api: AuthenticatedApi,
    params: {
        search?: string;
        platform?: "internal" | "public";
        userEmail?: string;
        userGroup?: "staff" | "devs";
        role?: "user" | "assistant" | "all";
        limit: number;
        offset: number;
        sortBy?: string;
        descending?: boolean;
        timeRange: TimeRangeValue;
        customRange: CustomTimeRange;
    },
): Promise<MessageListPage> => {
    const query = new URLSearchParams();
    if (params.platform !== undefined) {
        query.set("platform", params.platform);
    }
    if (params.role !== undefined) {
        query.set("role", params.role);
    }
    query.set("limit", String(params.limit));
    query.set("offset", String(params.offset));
    if (params.search !== undefined && params.search.trim() !== "") {
        query.set("search", params.search.trim());
    }
    if (params.userEmail !== undefined && params.userEmail.trim() !== "") {
        query.set("user_email", params.userEmail.trim());
    }
    if (params.userGroup !== undefined) {
        query.set("user_group", params.userGroup);
    }
    if (params.sortBy !== undefined && params.sortBy !== "") {
        query.set("sort_by", params.sortBy);
    }
    if (params.descending !== undefined) {
        query.set("descending", String(params.descending));
    }

    const timeRangeParams = getTimeRangeQueryParams(
        params.timeRange,
        new Date(),
        params.customRange,
    );
    if (timeRangeParams.start !== undefined) {
        query.set("start", timeRangeParams.start);
    }
    if (timeRangeParams.end !== undefined) {
        query.set("end", timeRangeParams.end);
    }

    const response = await api.get<MessageListResponse>(
        `/messages?${query.toString()}`,
    );

    return {
        total: response.total,
        items: response.items.map((item) => ({
            id: item.id,
            conversationId: item.conversation_id,
            role: item.role,
            content: item.content,
            contentPreview: item.content_preview,
            contentLength: item.content_length,
            conversationTitle: item.conversation_title ?? undefined,
            conversationSummary: item.conversation_summary ?? undefined,
            isPublic: item.is_public,
            conversationUserName: item.conversation_user_name ?? undefined,
            conversationUserEmail: item.conversation_user_email ?? undefined,
            generationTimeMs: item.generation_time_ms ?? undefined,
            inputTokens: item.input_tokens ?? undefined,
            outputTokens: item.output_tokens ?? undefined,
            toolCallCount: item.tool_call_count,
            guardrailFailureCount: item.guardrail_failure_count,
            guardrailsBlocked: item.guardrails_blocked,
            traceId: item.trace_id ?? undefined,
            spanId: item.span_id ?? undefined,
            createdAt: item.created_at,
            updatedAt: item.updated_at,
        })),
    };
};
