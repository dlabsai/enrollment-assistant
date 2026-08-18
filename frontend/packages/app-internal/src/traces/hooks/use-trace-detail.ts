import { useCallback } from "react";

import type { AuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { fetchTraceDetail } from "../lib/api";
import type { TraceDetail } from "../types";
import { useTraceDetailLoader } from "./use-trace-detail-loader";

interface UseTraceDetailResult {
    detail: TraceDetail | undefined;
    loading: boolean;
    error: string | undefined;
    refresh: () => void;
}

export const useTraceDetail = (
    traceId: string | undefined,
    source: "runtime" | "evals" = "runtime",
): UseTraceDetailResult => {
    const fetcher = useCallback(
        async (api: AuthenticatedApi, id: string, signal: AbortSignal) =>
            fetchTraceDetail(api, id, source, signal),
        [source],
    );
    return useTraceDetailLoader(traceId, fetcher);
};
