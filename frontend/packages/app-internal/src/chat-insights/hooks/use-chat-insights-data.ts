import { useCallback, useEffect } from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { useAsyncData } from "../../lib/hooks/use-async-data";
import type { CustomTimeRange, TimeRangeValue } from "../../lib/time-range";
import {
    fetchChatInsightData,
    fetchLatestChatInsightRun,
} from "../lib/api";
import type { ChatInsightData } from "../types";

interface UseChatInsightsDataResult {
    data: ChatInsightData | undefined;
    loading: boolean;
    hasLoaded: boolean;
    error: string | undefined;
    refresh: () => void;
}

const activeStatuses = new Set(["queued", "running"]);

export const useChatInsightsData = (
    timeRange: TimeRangeValue,
    customRange: CustomTimeRange,
): UseChatInsightsDataResult => {
    const api = useAuthenticatedApi();
    const load = useCallback(
        async (signal: AbortSignal) => fetchChatInsightData(
                api,
                timeRange,
                customRange,
                signal,
            ),
        [api, customRange, timeRange],
    );
    const { data, loading, hasLoaded, error, refresh } = useAsyncData<
        ChatInsightData | undefined
    >({
        errorMessage: "Failed to fetch chat topics and sources",
        initialData: undefined,
        load,
    });

    useEffect(() => {
        const currentRunId = data?.summary.latest_run?.id;
        const currentStatus = data?.summary.latest_run?.status ?? "";
        if (!activeStatuses.has(currentStatus)) {
            return (): void => undefined;
        }

        const controller = new AbortController();
        let timer: number | undefined;
        const poll = (): void => {
            timer = window.setTimeout(() => {
                void fetchLatestChatInsightRun(api, controller.signal).then(
                    (run) => {
                        if (controller.signal.aborted) {
                            return;
                        }
                        const nextStatus = run?.status ?? "";
                        if (
                            run?.id !== currentRunId ||
                            nextStatus !== currentStatus ||
                            !activeStatuses.has(nextStatus)
                        ) {
                            refresh();
                            return;
                        }
                        poll();
                    },
                    () => {
                        if (!controller.signal.aborted) {
                            poll();
                        }
                    },
                );
            }, 5000);
        };
        poll();
        return (): void => {
            controller.abort();
            if (timer !== undefined) {
                window.clearTimeout(timer);
            }
        };
    }, [
        api,
        data?.summary.latest_run?.id,
        data?.summary.latest_run?.status,
        refresh,
    ]);

    return { data, loading, hasLoaded, error, refresh };
};
