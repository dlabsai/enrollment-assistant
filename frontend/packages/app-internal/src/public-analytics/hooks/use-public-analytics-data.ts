import { useCallback } from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { useAsyncData } from "../../lib/hooks/use-async-data";
import type { CustomTimeRange, TimeRangeValue } from "../../lib/time-range";
import { fetchPublicAnalyticsSummary } from "../lib/api";
import type { PublicAnalyticsSummary } from "../types";

interface UsePublicAnalyticsDataResult {
    summary: PublicAnalyticsSummary | undefined;
    loading: boolean;
    hasLoaded: boolean;
    error: string | undefined;
    refresh: () => void;
}

export const usePublicAnalyticsData = (
    timeRange: TimeRangeValue,
    customRange: CustomTimeRange,
): UsePublicAnalyticsDataResult => {
    const api = useAuthenticatedApi();
    const load = useCallback(
        async (signal: AbortSignal) =>
            fetchPublicAnalyticsSummary(api, timeRange, customRange, signal),
        [api, customRange, timeRange],
    );
    const { data, loading, hasLoaded, error, refresh } = useAsyncData<
        PublicAnalyticsSummary | undefined
    >({
        errorMessage: "Failed to fetch Public Analytics data",
        initialData: undefined,
        load,
    });

    return { summary: data, loading, hasLoaded, error, refresh };
};
