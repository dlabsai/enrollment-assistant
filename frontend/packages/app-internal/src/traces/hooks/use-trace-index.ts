import { useCallback, useEffect, useState } from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { fetchTraceIndex } from "../lib/api";
import type { TracePlatformFilter, TraceSummary } from "../types";

interface UseTraceIndexResult {
    traces: TraceSummary[];
    total: number;
    loading: boolean;
    error: string | undefined;
    refresh: () => Promise<void>;
}

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
    const [traces, setTraces] = useState<TraceSummary[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | undefined>();

    const refresh = useCallback(async () => {
        setLoading(true);
        setError(undefined);
        try {
            const data = await fetchTraceIndex(api, {
                aiOnly,
                limit: pageSize,
                offset: pageIndex * pageSize,
                platform,
                start,
                end,
                source,
            });
            // await new Promise((resolve) => {
            //     setTimeout(resolve, 5000);
            // });
            setTraces(data.items);
            setTotal(data.total);
        } catch (error_) {
            setError(
                error_ instanceof Error
                    ? error_.message
                    : "Failed to fetch traces",
            );
        } finally {
            setLoading(false);
        }
    }, [api, end, aiOnly, pageIndex, pageSize, platform, source, start]);

    useEffect(() => {
        void refresh();
    }, [refresh]);

    return { traces, total, loading, error, refresh };
};
