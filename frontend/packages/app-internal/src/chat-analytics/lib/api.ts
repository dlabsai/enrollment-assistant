import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import {
    type CustomTimeRange,
    getTimeRangeQueryParams,
    type TimeRangeValue,
} from "../../lib/time-range";
import type { ChatAnalyticsSummary } from "../../usage/types";

export type ChatAnalyticsPlatform = "both" | "internal" | "public";

export const fetchChatAnalyticsSummary = async (
    api: AuthenticatedApi,
    platform: ChatAnalyticsPlatform,
    timeRange: TimeRangeValue,
    customRange: CustomTimeRange,
    userEmail?: string,
    userGroup?: "staff" | "devs",
    signal?: AbortSignal,
): Promise<ChatAnalyticsSummary> => {
    const params = new URLSearchParams(
        getTimeRangeQueryParams(timeRange, new Date(), customRange),
    );
    if (platform !== "both") {
        params.set("platform", platform);
    }
    if (userEmail !== undefined && userEmail !== "") {
        params.set("user_email", userEmail);
    }
    if (userGroup !== undefined) {
        params.set("user_group", userGroup);
    }
    return api.get<ChatAnalyticsSummary>(
        `/analytics/conversations?${params.toString()}`,
        { signal },
    );
};
