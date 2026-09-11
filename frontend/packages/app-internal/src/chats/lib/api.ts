import type { ApiBlobResponse } from "@va/shared/lib/api-client";

import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import {
    type CustomTimeRange,
    getTimeRangeQueryParams,
    type TimeRangeValue,
} from "../../lib/time-range";
import type {
    ChatAnalyticsFilter,
    ChatListPage,
    ChatUserOption,
} from "../types";

const CHATS_BASE = "/conversations";

export const fetchChatUsers = async (
    api: AuthenticatedApi,
    params: {
        search?: string;
        platform?: "internal" | "public";
        limit?: number;
        kind?: "chat" | "investigation";
    },
): Promise<ChatUserOption[]> => {
    const query = new URLSearchParams();
    if (params.search !== undefined && params.search.trim() !== "") {
        query.set("search", params.search.trim());
    }
    if (params.platform !== undefined) {
        query.set("platform", params.platform);
    }
    if (params.kind !== undefined) {
        query.set("kind", params.kind);
    }
    if (params.limit !== undefined) {
        query.set("limit", String(params.limit));
    }

    const endpoint = query.toString()
        ? `${CHATS_BASE}/users?${query.toString()}`
        : `${CHATS_BASE}/users`;

    return api.get<ChatUserOption[]>(endpoint);
};

interface ChatListPageResponseItem {
    id: string;
    title?: string;
    summary?: string;
    last_message_preview?: string | null;
    user_message_count: number;
    assistant_message_count: number;
    created_at: string;
    updated_at: string;
    is_public: boolean;
    prompt_source?: string | null;
    user_name?: string | null;
    user_email?: string | null;
    total_cost?: number | null;
    feedback_up?: number | null;
    feedback_down?: number | null;
}

interface ChatListPageResponse {
    items: ChatListPageResponseItem[];
    total: number;
}

interface ChatBaseParams {
    search?: string;
    phraseSearch?: boolean;
    platform?: "internal" | "public";
    userEmail?: string;
    userGroup?: "staff" | "devs";
    sortBy?: string;
    descending?: boolean;
    analyticsFilter?: ChatAnalyticsFilter;
    timeRange: TimeRangeValue;
    customRange: CustomTimeRange;
}

interface ChatListParams extends ChatBaseParams {
    limit: number;
    offset: number;
    kind?: "chat" | "investigation";
}

interface ChatExportParams extends ChatBaseParams {
    chatUrlBase: string;
    locale: string;
    timeZone: string;
}

const appendChatBaseQueryParams = (
    query: URLSearchParams,
    params: ChatBaseParams,
): void => {
    if (params.platform !== undefined) {
        query.set("platform", params.platform);
    }
    if (params.search !== undefined && params.search.trim() !== "") {
        query.set("search", params.search.trim());
        if (params.phraseSearch === true) {
            query.set("phrase_search", "true");
        }
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

    if (params.analyticsFilter !== undefined) {
        if (params.analyticsFilter.minTurns !== undefined) {
            query.set("min_turns", String(params.analyticsFilter.minTurns));
        }
        if (params.analyticsFilter.maxTurns !== undefined) {
            query.set("max_turns", String(params.analyticsFilter.maxTurns));
        }
        if (params.analyticsFilter.start !== undefined) {
            query.set("analytics_start", params.analyticsFilter.start);
        }
        if (params.analyticsFilter.end !== undefined) {
            query.set("analytics_end", params.analyticsFilter.end);
        }
        if (params.analyticsFilter.endBefore !== undefined) {
            query.set("analytics_end_before", params.analyticsFilter.endBefore);
        }
        return;
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
};

export const fetchChatListPage = async (
    api: Pick<AuthenticatedApi, "get">,
    params: ChatListParams,
): Promise<ChatListPage> => {
    const query = new URLSearchParams();
    query.set("limit", String(params.limit));
    query.set("offset", String(params.offset));
    if (params.kind !== undefined) {
        query.set("kind", params.kind);
    }
    appendChatBaseQueryParams(query, params);

    const response = await api.get<ChatListPageResponse>(
        `${CHATS_BASE}/paginated?${query.toString()}`,
    );

    return {
        total: response.total,
        items: response.items.map((item) => ({
            id: item.id,
            title: item.title ?? undefined,
            summary: item.summary ?? undefined,
            lastMessagePreview: item.last_message_preview ?? undefined,
            userMessageCount: item.user_message_count,
            assistantMessageCount: item.assistant_message_count,
            createdAt: item.created_at,
            updatedAt: item.updated_at,
            isPublic: item.is_public,
            promptSource: item.prompt_source ?? undefined,
            userName: item.user_name ?? undefined,
            userEmail: item.user_email ?? undefined,
            totalCost: item.total_cost ?? undefined,
            feedbackUp: item.feedback_up ?? 0,
            feedbackDown: item.feedback_down ?? 0,
        })),
    };
};

export const fetchChatsExport = async (
    api: Pick<AuthenticatedApi, "getBlob">,
    params: ChatExportParams,
): Promise<ApiBlobResponse> => {
    const query = new URLSearchParams();
    appendChatBaseQueryParams(query, params);
    query.set("chat_url_base", params.chatUrlBase);
    query.set("browser_time_zone", params.timeZone);
    query.set("browser_locale", params.locale);
    return api.getBlob(`${CHATS_BASE}/export?${query.toString()}`, {
        headers: { Accept: "application/zip" },
    });
};
