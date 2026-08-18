import { useCallback } from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { useAsyncData } from "../../lib/hooks/use-async-data";
import { fetchTraceIndex } from "../lib/api";
import type { TracePlatformFilter, TraceSummary } from "../types";

interface TraceIndexData {
    traces: TraceSummary[];
    total: number;
}

interface UseTraceIndexResult extends TraceIndexData {
    loading: boolean;
    error: string | undefined;
    refresh: () => void;
}

const initialTraceIndexData: TraceIndexData = {
    traces: [],
    total: 0,
};

export const useTraceIndex = (
    aiOnly: boolean,
    platform: TracePlatformFilter,
    pageIndex: number,
    pageSize: number,
    start: string | undefined,
    end: string | undefined,
    source: "runtime" | "evals" = "runtime",
): UseTraceIndexResult => {
    const api = useAuthenticatedApi();
    const load = useCallback(
        async (signal: AbortSignal): Promise<TraceIndexData> => {
            const response = await fetchTraceIndex(api, {
                aiOnly,
                limit: pageSize,
                offset: pageIndex * pageSize,
                platform,
                start,
                end,
                source,
                signal,
            });
            return { traces: response.items, total: response.total };
        },
        [api, end, aiOnly, pageIndex, pageSize, platform, source, start],
    );
    const { data, loading, error, refresh } = useAsyncData({
        errorMessage: "Failed to fetch traces",
        initialData: initialTraceIndexData,
        load,
    });

    return { ...data, loading, error, refresh };
};
