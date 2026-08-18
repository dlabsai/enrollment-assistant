import { useCallback } from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { useAsyncData } from "../../lib/hooks/use-async-data";
import type { CustomTimeRange, TimeRangeValue } from "../../lib/time-range";
import { fetchPublicUsageSummary } from "../../public-analytics/lib/api";
import type { PublicUsageSummary } from "../types";

interface UsePublicUsageDataResult {
    summary: PublicUsageSummary | undefined;
    loading: boolean;
    hasLoaded: boolean;
    error: string | undefined;
    refresh: () => void;
}

export const usePublicUsageData = (
    timeRange: TimeRangeValue,
    customRange: CustomTimeRange,
): UsePublicUsageDataResult => {
    const api = useAuthenticatedApi();
    const load = useCallback(
        async (signal: AbortSignal) =>
            fetchPublicUsageSummary(api, timeRange, customRange, signal),
        [api, customRange, timeRange],
    );
    const { data, loading, hasLoaded, error, refresh } = useAsyncData<
        PublicUsageSummary | undefined
    >({
        errorMessage: "Failed to fetch public usage data",
        initialData: undefined,
        load,
    });

    return { summary: data, loading, hasLoaded, error, refresh };
};
