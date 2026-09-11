import type { TimeGranularity } from "../../lib/time-series";

export interface PublicAnalyticsTimeSeriesPoint {
    bucket_start: string;
    bucket_end: string;
    leads: number;
}

interface PublicAnalyticsDepthBucket {
    label: string;
    conversations: number;
    overflow: boolean;
}

export interface PublicAnalyticsSummary {
    total_leads: number;
    time_granularity: TimeGranularity;
    series: PublicAnalyticsTimeSeriesPoint[];
    depth_buckets: PublicAnalyticsDepthBucket[];
}
