import type { TimeGranularity } from "../../lib/time-series";

export interface AdoptionTimeSeriesPoint {
    bucket_start: string;
    bucket_end: string;
    active_users: number;
    monthly_active_users: number;
}

export interface AdoptionSummary {
    latest_daily_active_users: number;
    monthly_active_users: number;
    average_daily_active_users: number;
    stickiness: number;
    time_granularity: TimeGranularity;
    series: AdoptionTimeSeriesPoint[];
}
