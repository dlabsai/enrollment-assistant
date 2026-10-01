import type { TimeGranularity } from "../../lib/time-series";

export interface AdoptionTimeSeriesPoint {
    bucket_start: string;
    bucket_end: string;
    new_accounts: number;
    active_users: number;
    monthly_active_users: number;
}

export interface AdoptionSummary {
    new_accounts: number;
    active_new_accounts: number;
    latest_daily_active_users: number;
    monthly_active_users: number;
    average_daily_active_users: number;
    stickiness: number;
    time_granularity: TimeGranularity;
    series: AdoptionTimeSeriesPoint[];
}
