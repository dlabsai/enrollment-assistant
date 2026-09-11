import { useCallback } from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import { useAsyncData } from "../../lib/hooks/use-async-data";
import type { CustomTimeRange, TimeRangeValue } from "../../lib/time-range";
import type { TimeGranularity } from "../../lib/time-series";
import { fetchUsageOverview, type UsagePlatformFilter } from "../lib/api";
import type {
    ModelUsage,
    UsageOverviewApi,
    UsageSummary,
    UsageTimeSeriesPoint,
    UsageTraceBasic,
} from "../types";

interface UsageDataParams {
    platform: UsagePlatformFilter;
    timeRange: TimeRangeValue;
    customRange: CustomTimeRange;
    modelFilters: string[];
    userEmail?: string;
    userGroup?: "staff" | "devs";
    referenceDate?: Date;
}

interface UsageDataState {
    summary: UsageSummary;
    timeGranularity: TimeGranularity;
    seriesData: UsageTimeSeriesPoint[];
    modelData: ModelUsage[];
    latestTraces: UsageTraceBasic[];
}

interface UseUsageDataResult extends UsageDataState {
    loading: boolean;
    hasLoaded: boolean;
    error: string | undefined;
    refresh: () => void;
}

const emptySummary: UsageSummary = {
    totalRequests: 0,
    totalTokens: 0,
    totalCost: 0,
    totalEmbeddingRequests: 0,
    totalEmbeddingTokens: 0,
    totalEmbeddingCost: 0,
    totalEmbeddingAvgDuration: 0,
    totalErrors: 0,
    avgDuration: 0,
};

const emptyState: UsageDataState = {
    summary: emptySummary,
    timeGranularity: "day",
    seriesData: [],
    modelData: [],
    latestTraces: [],
};

const mapOverviewResponse = (data: UsageOverviewApi): UsageDataState => ({
    summary: {
        totalRequests: data.summary.total_requests,
        totalTokens: data.summary.total_tokens,
        totalCost: data.summary.total_cost,
        totalEmbeddingRequests: data.summary.total_embedding_requests,
        totalEmbeddingTokens: data.summary.total_embedding_tokens,
        totalEmbeddingCost: data.summary.total_embedding_cost,
        totalEmbeddingAvgDuration:
            data.summary.total_embedding_avg_duration ?? 0,
        totalErrors: data.summary.total_errors,
        avgDuration: data.summary.avg_duration ?? 0,
    },
    timeGranularity: data.time_granularity,
    seriesData: data.series.map((entry) => ({
        bucket_start: entry.bucket_start,
        bucket_end: entry.bucket_end,
        requests: entry.requests,
        tokens: entry.tokens,
        cost: entry.cost,
        embeddingRequests: entry.embedding_requests,
        embeddingTokens: entry.embedding_tokens,
        embeddingCost: entry.embedding_cost,
        errors: entry.errors,
        avgDuration: entry.avg_duration ?? 0,
    })),
    modelData: data.models.map((entry) => ({
        model: entry.model,
        requests: entry.requests,
        tokens: entry.tokens,
        cost: entry.cost,
    })),
    latestTraces: data.latest_traces,
});

export const useUsageData = ({
    platform,
    timeRange,
    customRange,
    modelFilters,
    userEmail,
    userGroup,
    referenceDate,
}: UsageDataParams): UseUsageDataResult => {
    const api = useAuthenticatedApi();
    const load = useCallback(
        async (signal: AbortSignal): Promise<UsageDataState> =>
            mapOverviewResponse(
                await fetchUsageOverview(api, {
                    platform,
                    timeRange,
                    customRange,
                    modelFilters,
                    userEmail,
                    userGroup,
                    referenceDate,
                    signal,
                }),
            ),
        [
            api,
            customRange,
            modelFilters,
            platform,
            referenceDate,
            timeRange,
            userEmail,
            userGroup,
        ],
    );
    const { data, loading, hasLoaded, error, refresh } = useAsyncData({
        errorMessage: "Failed to fetch usage data",
        initialData: emptyState,
        load,
    });

    return { ...data, loading, hasLoaded, error, refresh };
};
