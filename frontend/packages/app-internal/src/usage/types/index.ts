import type { TimeGranularity } from "../../lib/time-series";

export interface UsageTraceBasic {
    created_at: string;
    model: string;
    prompt_tokens: number | null;
    completion_tokens: number | null;
    cost: number | null;
    duration: number | null;
    is_error: boolean;
    is_public: boolean | null;
}

export interface UsageTimeSeriesPoint {
    bucket_start: string;
    bucket_end: string;
    requests: number;
    tokens: number;
    cost: number;
    embeddingRequests: number;
    embeddingTokens: number;
    embeddingCost: number;
    errors: number;
    avgDuration: number;
}

export interface ModelUsage {
    model: string;
    requests: number;
    tokens: number;
    cost: number;
}

export interface UsageSummary {
    totalRequests: number;
    totalTokens: number;
    totalCost: number;
    totalEmbeddingRequests: number;
    totalEmbeddingTokens: number;
    totalEmbeddingCost: number;
    totalEmbeddingAvgDuration: number;
    totalErrors: number;
    avgDuration: number;
}

interface UsageTimeSeriesPointApi {
    bucket_start: string;
    bucket_end: string;
    requests: number;
    tokens: number;
    cost: number;
    embedding_requests: number;
    embedding_tokens: number;
    embedding_cost: number;
    errors: number;
    avg_duration: number | null;
}

interface UsageModelApi {
    model: string;
    requests: number;
    tokens: number;
    cost: number;
}

interface UsageSummaryApi {
    total_requests: number;
    total_tokens: number;
    total_cost: number;
    total_embedding_requests: number;
    total_embedding_tokens: number;
    total_embedding_cost: number;
    total_embedding_avg_duration: number | null;
    total_errors: number;
    avg_duration: number | null;
}

export interface UsageOverviewApi {
    summary: UsageSummaryApi;
    time_granularity: TimeGranularity;
    series: UsageTimeSeriesPointApi[];
    models: UsageModelApi[];
    latest_traces: UsageTraceBasic[];
}
