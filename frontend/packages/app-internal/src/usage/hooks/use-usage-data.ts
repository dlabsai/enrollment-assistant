import { useCallback, useEffect, useState } from "react";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import type { CustomTimeRange, TimeRangeValue } from "../../lib/time-range";
import { fetchUsageOverview, type UsagePlatformFilter } from "../lib/api";
import type {
    ModelUsage,
    UsageDaily,
    UsageOverviewApi,
    UsageSummary,
    UsageTraceBasic,
} from "../types";

interface UsageDataParams {
    platform: UsagePlatformFilter;
    timeRange: TimeRangeValue;
    customRange: CustomTimeRange;
    modelFilters: string[];
    referenceDate?: Date;
}

interface UsageDataState {
    summary: UsageSummary;
    dailyData: UsageDaily[];
    modelData: ModelUsage[];
    latestTraces: UsageTraceBasic[];
}

interface UseUsageDataResult extends UsageDataState {
    loading: boolean;
    hasLoaded: boolean;
    error: string | undefined;
    refresh: () => Promise<void>;
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
    dailyData: [],
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
    dailyData: data.daily.map((entry) => ({
        date: entry.date,
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
    referenceDate,
}: UsageDataParams): UseUsageDataResult => {
    const api = useAuthenticatedApi();
    const [data, setData] = useState(emptyState);
    const [loading, setLoading] = useState(true);
    const [hasLoaded, setHasLoaded] = useState(false);
    const [error, setError] = useState<string | undefined>();

    const refresh = useCallback(async () => {
        setLoading(true);
        setError(undefined);
        try {
            const response = await fetchUsageOverview(api, {
                platform,
                timeRange,
                customRange,
                modelFilters,
                referenceDate,
            });
            setData(mapOverviewResponse(response));
        } catch (error_) {
            setError(
                error_ instanceof Error
                    ? error_.message
                    : "Failed to fetch usage data",
            );
        } finally {
            setLoading(false);
            setHasLoaded(true);
        }
    }, [api, customRange, modelFilters, platform, referenceDate, timeRange]);

    useEffect(() => {
        void refresh();
    }, [refresh]);

    return { ...data, loading, hasLoaded, error, refresh };
};
