import { useCallback } from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { useAsyncData } from "../../lib/hooks/use-async-data";
import type { CustomTimeRange, TimeRangeValue } from "../../lib/time-range";
import { fetchAdoptionSummary } from "../lib/api";
import type { AdoptionSummary } from "../types";

interface UseAdoptionDataResult {
    summary: AdoptionSummary | undefined;
    loading: boolean;
    hasLoaded: boolean;
    error: string | undefined;
    refresh: () => void;
}

export const useAdoptionData = (
    timeRange: TimeRangeValue,
    customRange: CustomTimeRange,
    userEmail?: string,
    userGroup?: "staff" | "devs",
): UseAdoptionDataResult => {
    const api = useAuthenticatedApi();
    const load = useCallback(
        async (signal: AbortSignal) =>
            fetchAdoptionSummary(
                api,
                timeRange,
                customRange,
                userEmail,
                userGroup,
                signal,
            ),
        [api, customRange, timeRange, userEmail, userGroup],
    );
    const { data, loading, hasLoaded, error, refresh } = useAsyncData<
        AdoptionSummary | undefined
    >({
        errorMessage: "Failed to fetch adoption data",
        initialData: undefined,
        load,
    });

    return { summary: data, loading, hasLoaded, error, refresh };
};
