import type { ApiBlobResponse } from "@va/shared/lib/api-client";

import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import type { Rating } from "../../chat/types";
import {
    type CustomTimeRange,
    getTimeRangeQueryParams,
    type TimeRangeValue,
} from "../../lib/time-range";
import type { FeedbackListPage } from "../types";

interface FeedbackListItemResponse {
    id: string;
    message_id: string;
    conversation_id: string;
    rating: Rating;
    text?: string | null;
    message_role: string;
    message_preview: string;
    conversation_title?: string | null;
    conversation_summary?: string | null;
    is_public: boolean;
    conversation_user_name?: string | null;
    conversation_user_email?: string | null;
    feedback_user_name: string;
    feedback_user_email: string;
    created_at: string;
    updated_at: string;
}

interface FeedbackListResponse {
    items: FeedbackListItemResponse[];
    total: number;
}

interface FeedbackBaseParams {
    search?: string;
    platform?: "internal" | "public";
    userEmail?: string;
    userGroup?: "staff" | "devs";
    rating?: Rating;
    sortBy?: string;
    descending?: boolean;
    timeRange: TimeRangeValue;
    customRange: CustomTimeRange;
}

interface FeedbackListParams extends FeedbackBaseParams {
    limit: number;
    offset: number;
}

interface FeedbackExportParams extends FeedbackBaseParams {
    messageUrlBase: string;
    browserTimeZone: string;
    browserLocale: string;
}

const appendFeedbackListQueryParams = (
    query: URLSearchParams,
    params: FeedbackBaseParams,
): void => {
    if (params.platform !== undefined) {
        query.set("platform", params.platform);
    }
    if (params.rating !== undefined) {
        query.set("rating", params.rating);
    }
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
};

const buildFeedbackListQuery = (params: FeedbackListParams): URLSearchParams => {
    const query = new URLSearchParams();
    query.set("limit", String(params.limit));
    query.set("offset", String(params.offset));
    appendFeedbackListQueryParams(query, params);
    return query;
};

const buildFeedbackExportQuery = (params: FeedbackExportParams): URLSearchParams => {
    const query = new URLSearchParams();
    appendFeedbackListQueryParams(query, params);
    query.set("message_url_base", params.messageUrlBase);
    query.set("browser_time_zone", params.browserTimeZone);
    query.set("browser_locale", params.browserLocale);
    return query;
};

export const fetchFeedbackListPage = async (
    api: AuthenticatedApi,
    params: FeedbackListParams,
): Promise<FeedbackListPage> => {
    const query = buildFeedbackListQuery(params);
    const response = await api.get<FeedbackListResponse>(
        `/feedback?${query.toString()}`,
    );

    return {
        total: response.total,
        items: response.items.map((item) => ({
            id: item.id,
            messageId: item.message_id,
            conversationId: item.conversation_id,
            rating: item.rating,
            text: item.text ?? undefined,
            messageRole: item.message_role,
            messagePreview: item.message_preview,
            conversationTitle: item.conversation_title ?? undefined,
            conversationSummary: item.conversation_summary ?? undefined,
            isPublic: item.is_public,
            conversationUserName: item.conversation_user_name ?? undefined,
            conversationUserEmail: item.conversation_user_email ?? undefined,
            feedbackUserName: item.feedback_user_name,
            feedbackUserEmail: item.feedback_user_email,
            createdAt: item.created_at,
            updatedAt: item.updated_at,
        })),
    };
};

export const fetchFeedbackExport = async (
    api: AuthenticatedApi,
    params: FeedbackExportParams,
): Promise<ApiBlobResponse> => {
    const query = buildFeedbackExportQuery(params);
    return api.getBlob(`/feedback/export?${query.toString()}`, {
        headers: {
            Accept: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
    });
};
