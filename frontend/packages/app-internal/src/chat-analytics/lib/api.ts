import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import {
    type CustomTimeRange,
    getTimeRangeQueryParams,
    type TimeRangeValue,
} from "../../lib/time-range";
import { getAppFormatSettings } from "../../lib/time-zone";
import type { ChatAnalyticsSummary } from "../types";

export type ChatAnalyticsPlatform = "both" | "internal" | "public";

export interface FetchedChatAnalyticsSummary {
    appliedRange: {
        start?: string;
        end?: string;
    };
    summary: ChatAnalyticsSummary;
}

export const fetchChatAnalyticsSummary = async (
    api: AuthenticatedApi,
    platform: ChatAnalyticsPlatform,
    timeRange: TimeRangeValue,
    customRange: CustomTimeRange,
    userEmail?: string,
    userGroup?: "staff" | "devs",
    signal?: AbortSignal,
): Promise<FetchedChatAnalyticsSummary> => {
    const range = getTimeRangeQueryParams(timeRange, new Date(), customRange);
    const params = new URLSearchParams(range);
    params.set("browser_time_zone", getAppFormatSettings().timeZone);
    if (platform !== "both") {
        params.set("platform", platform);
    }
    if (userEmail !== undefined && userEmail !== "") {
        params.set("user_email", userEmail);
    }
    if (userGroup !== undefined) {
        params.set("user_group", userGroup);
    }
    const summary = await api.get<ChatAnalyticsSummary>(
        `/analytics/conversations?${params.toString()}`,
        { signal },
    );
    return { appliedRange: range, summary };
};
