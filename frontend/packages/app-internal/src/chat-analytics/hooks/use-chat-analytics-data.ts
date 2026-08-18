import { useCallback } from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { useAsyncData } from "../../lib/hooks/use-async-data";
import type { CustomTimeRange, TimeRangeValue } from "../../lib/time-range";
import type { ChatAnalyticsSummary } from "../../usage/types";
import {
    type ChatAnalyticsPlatform,
    fetchChatAnalyticsSummary,
} from "../lib/api";

interface UseChatAnalyticsDataResult {
    summary: ChatAnalyticsSummary | undefined;
    loading: boolean;
    hasLoaded: boolean;
    error: string | undefined;
    refresh: () => void;
}

export const useChatAnalyticsData = (
    platform: ChatAnalyticsPlatform,
    timeRange: TimeRangeValue,
    customRange: CustomTimeRange,
    userEmail?: string,
    userGroup?: "staff" | "devs",
): UseChatAnalyticsDataResult => {
    const api = useAuthenticatedApi();
    const load = useCallback(
        async (signal: AbortSignal) =>
            fetchChatAnalyticsSummary(
                api,
                platform,
                timeRange,
                customRange,
                userEmail,
                userGroup,
                signal,
            ),
        [api, customRange, platform, timeRange, userEmail, userGroup],
    );
    const { data, loading, hasLoaded, error, refresh } = useAsyncData<
        ChatAnalyticsSummary | undefined
    >({
        errorMessage: "Failed to fetch analytics data",
        initialData: undefined,
        load,
    });

    return { summary: data, loading, hasLoaded, error, refresh };
};
