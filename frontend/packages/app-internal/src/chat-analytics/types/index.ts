import type { TimeGranularity } from "../../lib/time-series";

export interface ChatAnalyticsTimeSeriesPoint {
    bucket_start: string;
    bucket_end: string;
    conversations: number;
    turns: number;
}

export interface ChatAnalyticsBucket {
    label: string;
    conversations: number;
    min_turns: number;
    max_turns: number | null;
    overflow: boolean;
}

export interface ChatAnalyticsHourly {
    hour: number;
    turns: number;
}

export interface ChatAnalyticsStats {
    min: number | null;
    p50: number | null;
    avg: number | null;
    p75: number | null;
    p90: number | null;
    p95: number | null;
    p99: number | null;
    max: number | null;
}

export interface ChatAnalyticsSummary {
    total_conversations: number;
    total_turns: number;
    avg_turns_per_conversation: number;
    time_granularity: TimeGranularity;
    series: ChatAnalyticsTimeSeriesPoint[];
    length_buckets: ChatAnalyticsBucket[];
    hourly_activity: ChatAnalyticsHourly[];
    length_stats: ChatAnalyticsStats | null;
}
