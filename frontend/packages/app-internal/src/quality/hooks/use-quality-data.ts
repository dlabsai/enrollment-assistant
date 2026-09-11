import { useCallback } from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { useAsyncData } from "../../lib/hooks/use-async-data";
import type { CustomTimeRange, TimeRangeValue } from "../../lib/time-range";
import { type FetchedQualitySummary, fetchQualitySummary } from "../lib/api";
import type { QualityPlatform, QualitySummary } from "../types";

interface UseQualityDataResult {
    appliedRange: FetchedQualitySummary["appliedRange"] | undefined;
    summary: QualitySummary | undefined;
    loading: boolean;
    hasLoaded: boolean;
    error: string | undefined;
    refresh: () => void;
}

export const useQualityData = (
    platform: QualityPlatform,
    timeRange: TimeRangeValue,
    customRange: CustomTimeRange,
    userEmail?: string,
    userGroup?: "staff" | "devs",
): UseQualityDataResult => {
    const api = useAuthenticatedApi();
    const load = useCallback(
        async (signal: AbortSignal) =>
            fetchQualitySummary(
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
        FetchedQualitySummary | undefined
    >({
        errorMessage: "Failed to fetch quality data",
        initialData: undefined,
        load,
    });

    return {
        appliedRange: data?.appliedRange,
        summary: data?.summary,
        loading,
        hasLoaded,
        error,
        refresh,
    };
};
