import { useCallback } from "react";

import {
    type AuthenticatedApi,
    useAuthenticatedApi,
} from "../../auth/hooks/use-authenticated-api";
import { useAsyncData } from "../../lib/hooks/use-async-data";
import type { TraceDetail } from "../types";

interface UseTraceDetailLoaderOptions {
    clearDetailOnError?: boolean;
}

interface UseTraceDetailLoaderResult {
    detail: TraceDetail | undefined;
    loading: boolean;
    error: string | undefined;
    refresh: () => void;
}

type TraceDetailFetcher = (
    api: AuthenticatedApi,
    id: string,
    signal: AbortSignal,
) => Promise<TraceDetail>;

export const useTraceDetailLoader = (
    id: string | undefined,
    fetcher: TraceDetailFetcher,
    options: UseTraceDetailLoaderOptions = {},
): UseTraceDetailLoaderResult => {
    const api = useAuthenticatedApi();
    const enabled = id !== undefined && id.trim() !== "";
    const load = useCallback(
        async (signal: AbortSignal): Promise<TraceDetail> => {
            if (id === undefined || id.trim() === "") {
                throw new Error("A trace identifier is required");
            }
            return fetcher(api, id, signal);
        },
        [api, fetcher, id],
    );
    const { data, loading, error, refresh } = useAsyncData<
        TraceDetail | undefined
    >({
        clearDataOnError: options.clearDetailOnError,
        enabled,
        errorMessage: "Failed to fetch trace",
        initialData: undefined,
        load,
    });

    return { detail: data, loading, error, refresh };
};
